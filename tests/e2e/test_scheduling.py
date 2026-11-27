"""Appointments and referrals (CEDA UG01, HS04, HS05).

UG01 acceptance: two schedulers request the last slot concurrently; only one
receives confirmation; if the destination slot is taken, the original booking
survives; a stale hold token is refused and the slot is available again.
"""

import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import (
    Appointment,
    AuditEvent,
    LegitimateRelationship,
    Organisation,
    OrganisationSite,
    OutboxEvent,
    Party,
    Slot,
    SlotHold,
)
from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import admit, order, register, release

TOMORROW = (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0)


def if_match(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


def code(r: Any) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def make_slots(api: Api, count: int = 1, **extra: Any) -> list[dict[str, Any]]:
    body = {
        "facility_id": str(api.tenant.facility_id),
        "practitioner_id": str(api.tenant.practitioners["clinician"]),
        "service": "cardiology",
        "starts_at": TOMORROW.isoformat(),
        "minutes": 20,
        "count": count,
        **extra,
    }
    r = api.post("scheduler", "/v1/slots", body)
    assert r.status_code == 201, r.text
    return r.json()["slots"]


def hold(api: Api, who: str, slot_id: str) -> Any:
    return api.post(who, f"/v1/slots/{slot_id}/hold", {})


def book(api: Api, who: str, hold_id: str, patient_id: str, **extra: Any) -> Any:
    return api.post(
        who, "/v1/appointments", {"hold_id": hold_id, "patient_id": patient_id, **extra}
    )


def booked(api: Api, slot_id: str, patient_id: str, who: str = "scheduler") -> dict[str, Any]:
    h = hold(api, who, slot_id)
    assert h.status_code == 201, h.text
    r = book(api, who, h.json()["id"], patient_id)
    assert r.status_code == 201, r.text
    return r.json()


def expire_hold(factory: sessionmaker[Session], hold_id: str) -> None:
    with factory() as s, s.begin():
        s.execute(
            update(SlotHold)
            .where(SlotHold.id == uuid.UUID(hold_id))
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )


# -- slots ----------------------------------------------------------------------------


def test_slots_are_created_and_searched(api: Api) -> None:
    run = make_slots(api, count=3, slot_type="follow_up", modality="video")
    assert [s["status"] for s in run] == ["available"] * 3
    starts = [datetime.fromisoformat(s["starts_at"]) for s in run]
    assert starts[1] - starts[0] == timedelta(minutes=20)

    def search(query: str = "") -> list[str]:
        r = api.get("registrar", f"/v1/slots?service=cardiology{query}")
        assert r.status_code == 200, r.text
        return [s["id"] for s in r.json()]

    assert search() == [s["id"] for s in run]
    assert search("&slot_type=new") == []
    assert search(f"&practitioner_id={api.tenant.practitioners['clinician2']}") == []
    assert len(search(f"&facility_id={api.tenant.facility_id}&slot_type=follow_up")) == 3
    window = f"&from={(starts[1]).isoformat()}&to={(starts[2]).isoformat()}".replace("+", "%2B")
    assert search(window) == [run[1]["id"]]

    body = {
        "facility_id": str(api.tenant.facility_id),
        "practitioner_id": str(api.tenant.practitioners["clinician"]),
        "service": "cardiology",
        "starts_at": TOMORROW.isoformat(),
    }
    assert code(api.post("scheduler", "/v1/slots", body)) == (409, "slot_exists")
    past = {**body, "starts_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat()}
    assert code(api.post("scheduler", "/v1/slots", past)) == (422, "slot_in_past")
    assert code(api.post("scheduler", "/v1/slots", {**body, "minutes": 1})) == (
        422,
        "bad_slot_length",
    )
    assert code(api.post("scheduler", "/v1/slots", {**body, "count": 99})) == (
        422,
        "bad_slot_count",
    )
    assert code(api.post("scheduler", "/v1/slots", {**body, "timezone": "Mars/Base"})) == (
        422,
        "bad_timezone",
    )
    assert code(api.post("clinician", "/v1/slots", body)) == (403, "missing_capability")
    assert api.get("clinician", "/v1/slots").status_code == 403


# -- UG01 acceptance: the last slot ----------------------------------------------------


def test_two_schedulers_race_for_the_last_slot(api: Api) -> None:
    [slot] = make_slots(api)
    pid = register(api)
    clients = [TestClient(api.client.app) for _ in range(2)]
    start = threading.Barrier(2)
    results: dict[str, Any] = {}

    def attempt(who: str, client: TestClient) -> None:
        start.wait()
        results[who] = client.post(
            f"/v1/slots/{slot['id']}/hold", json={}, headers=api.headers(who)
        )

    threads = [
        threading.Thread(target=attempt, args=(who, c))
        for who, c in zip(("scheduler", "scheduler2"), clients, strict=True)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    statuses = sorted(r.status_code for r in results.values())
    assert statuses == [201, 409], {w: r.text for w, r in results.items()}
    winner = next(w for w, r in results.items() if r.status_code == 201)
    loser = next(w for w in results if w != winner)
    assert results[loser].json()["error"]["code"] == "slot_held"

    confirmed = book(api, winner, results[winner].json()["id"], pid)
    assert confirmed.status_code == 201, confirmed.text
    assert confirmed.json()["status"] == "booked"
    assert code(hold(api, loser, slot["id"])) == (409, "slot_booked")
    [listed] = api.get("registrar", "/v1/slots?service=cardiology").json()
    assert listed["status"] == "booked"
    assert api.get("registrar", "/v1/slots?service=cardiology&available_only=true").json() == []


def test_a_stale_hold_is_refused_and_the_slot_returns(
    api: Api, factory: sessionmaker[Session]
) -> None:
    [slot] = make_slots(api)
    pid = register(api)
    mine = hold(api, "scheduler", slot["id"]).json()
    assert datetime.fromisoformat(mine["expires_at"]) - datetime.now(UTC) <= timedelta(minutes=5)
    assert api.get("registrar", "/v1/slots?service=cardiology").json()[0]["status"] == "held"
    assert code(book(api, "scheduler2", mine["id"], pid)) == (403, "not_hold_owner")

    expire_hold(factory, mine["id"])
    assert code(book(api, "scheduler", mine["id"], pid)) == (409, "hold_expired")
    free = api.get("registrar", "/v1/slots?service=cardiology&available_only=true").json()
    assert [s["id"] for s in free] == [slot["id"]]  # availability restored

    theirs = hold(api, "scheduler2", slot["id"])
    assert theirs.status_code == 201, theirs.text  # clears the expired hold
    with factory() as s:
        stale = s.get(SlotHold, (api.tenant.tenant_id, uuid.UUID(mine["id"])))
        assert stale is not None and (stale.outcome, stale.live_marker) == ("expired", None)
    assert code(book(api, "scheduler", mine["id"], pid)) == (409, "hold_expired")
    first = book(api, "scheduler2", theirs.json()["id"], pid)
    assert first.status_code == 201
    assert code(book(api, "scheduler2", theirs.json()["id"], pid)) == (409, "hold_used")


def test_a_started_slot_cannot_be_held(api: Api, factory: sessionmaker[Session]) -> None:
    [slot] = make_slots(api)
    with factory() as s, s.begin():
        s.execute(
            update(Slot)
            .where(Slot.id == uuid.UUID(slot["id"]))
            .values(starts_at=datetime.now(UTC) - timedelta(minutes=1))
        )
    assert code(hold(api, "scheduler", slot["id"])) == (409, "slot_started")


# -- reschedule --------------------------------------------------------------------------


def test_reschedule_moves_the_booking_or_keeps_the_original(
    api: Api, factory: sessionmaker[Session]
) -> None:
    first, second, third = make_slots(api, count=3)
    pid = register(api)
    original = booked(api, first["id"], pid)
    target = hold(api, "scheduler", second["id"]).json()
    path = f"/v1/appointments/{original['id']}/reschedule"
    assert code(api.post("scheduler", path, {"hold_id": target["id"]})) == (
        428,
        "precondition_required",
    )
    moved = api.post("scheduler", path, {"hold_id": target["id"]}, **if_match(1))
    assert moved.status_code == 200, moved.text
    new = moved.json()
    assert (new["slot_id"], new["rescheduled_from_id"], new["status"]) == (
        second["id"],
        original["id"],
        "booked",
    )
    statuses = {
        s["id"]: s["status"] for s in api.get("registrar", "/v1/slots?service=cardiology").json()
    }
    assert statuses == {first["id"]: "available", second["id"]: "booked", third["id"]: "available"}

    # The destination is lost while this scheduler's hold runs out: the
    # reschedule is refused and the booking it would have moved survives.
    late = hold(api, "scheduler", third["id"]).json()
    expire_hold(factory, late["id"])
    booked(api, third["id"], register(api, "11122233344"), who="scheduler2")
    again = f"/v1/appointments/{new['id']}/reschedule"
    assert code(api.post("scheduler", again, {"hold_id": late["id"]}, **if_match(1))) == (
        409,
        "hold_expired",
    )
    with factory() as s:
        kept = s.get(Appointment, (api.tenant.tenant_id, uuid.UUID(new["id"])))
        old = s.get(Appointment, (api.tenant.tenant_id, uuid.UUID(original["id"])))
        events = s.scalars(
            select(OutboxEvent.event_type).where(
                OutboxEvent.tenant_id == api.tenant.tenant_id,
                OutboxEvent.event_type.like("appointment.%"),
            )
        ).all()
    assert kept is not None and (kept.status, kept.booked_marker) == ("booked", 1)
    assert old is not None and (old.status, old.booked_marker) == ("rescheduled", None)
    assert sorted(events) == sorted(
        ["appointment.booked", "appointment.rescheduled", "appointment.booked"]
    )


# -- cancel and attendance (HS04) --------------------------------------------------------


def test_cancel_frees_the_slot(api: Api) -> None:
    [slot] = make_slots(api)
    appt = booked(api, slot["id"], register(api))
    path = f"/v1/appointments/{appt['id']}/cancel"
    done = api.post("registrar", path, {"reason": "patient asked"}, **if_match(1))
    assert done.status_code == 200, done.text
    assert (done.json()["status"], done.json()["cancel_reason"]) == ("cancelled", "patient asked")
    assert api.get("registrar", "/v1/slots?available_only=true").json()[0]["id"] == slot["id"]
    assert code(api.post("registrar", path, {"reason": "again"}, **if_match(2))) == (
        422,
        "invalid_transition",
    )


def test_attendance_opens_the_visit_once(api: Api) -> None:
    in_person, other = make_slots(api, count=2)
    pid = register(api)
    appt = booked(api, in_person["id"], pid)
    path = f"/v1/appointments/{appt['id']}/attendance"
    assert code(api.post("registrar", path, {"outcome": "failed_connection"}, **if_match(1))) == (
        422,
        "not_remote",
    )
    body, headers = {"outcome": "attended"}, {"key": "attend-1", **if_match(1)}
    seen = api.post("registrar", path, body, **headers)
    assert seen.status_code == 200, seen.text
    encounter_id = seen.json()["encounter_id"]
    assert seen.json()["status"] == "attended" and encounter_id
    replay = api.post("registrar", path, body, **headers)
    assert replay.headers["Idempotent-Replay"] == "true"
    assert replay.json()["encounter_id"] == encounter_id  # the original visit, not a second
    assert code(api.post("registrar", path, body, **if_match(2))) == (422, "invalid_transition")
    # The clinic's clinician now has the patient in their care.
    chart = api.get("clinician", f"/v1/patients/{pid}/chart").json()
    [visit] = chart["encounters"]
    assert (visit["id"], visit["encounter_class"], visit["visit_authority"]) == (
        encounter_id,
        "ambulatory",
        "APPOINTMENT",
    )
    no_show = booked(api, other["id"], pid)
    r = api.post(
        "registrar",
        f"/v1/appointments/{no_show['id']}/attendance",
        {"outcome": "no_show"},
        **if_match(1),
    )
    assert (r.json()["status"], r.json()["encounter_id"]) == ("no_show", None)
    assert api.post("nurse", path, body, **if_match(2)).status_code == 403


def test_failed_video_call_is_not_care_and_can_be_rebooked(api: Api) -> None:
    first, second = make_slots(api, count=2, modality="video")
    pid = register(api)
    appt = booked(api, first["id"], pid)
    path = f"/v1/appointments/{appt['id']}/attendance"
    assert code(api.post("clinician", path, {"outcome": "attended"}, **if_match(1))) == (
        422,
        "identity_not_verified",
    )
    failed = api.post("clinician", path, {"outcome": "failed_connection"}, **if_match(1))
    assert failed.status_code == 200, failed.text
    assert (failed.json()["status"], failed.json()["encounter_id"]) == (
        "failed_connection",
        None,
    )
    rebooked = booked(api, second["id"], pid)
    done = api.post(
        "clinician",
        f"/v1/appointments/{rebooked['id']}/attendance",
        {"outcome": "attended", "identity_verified": True},
        **if_match(1),
    )
    assert done.status_code == 200, done.text
    chart = api.get("clinician", f"/v1/patients/{pid}/chart").json()
    assert [e["encounter_class"] for e in chart["encounters"]] == ["virtual"]


def test_a_closed_record_cannot_be_booked_or_referred(api: Api) -> None:
    [slot] = make_slots(api)
    pid = register(api)
    admit(api, pid)
    patient = api.get("steward", "/v1/patient-index?nin=12345678901").json()[0]
    closed = api.post(
        "steward",
        f"/v1/patients/{pid}/close",
        {"reason": "moved_away", "exit_date": datetime.now(UTC).date().isoformat()},
        **if_match(patient["version"]),
    )
    assert closed.status_code == 200, closed.text
    h = hold(api, "scheduler", slot["id"]).json()
    assert code(book(api, "scheduler", h["id"], pid)) == (409, "patient_not_bookable")
    assert code(refer(api, pid)) == (409, "patient_not_bookable")


# -- referral (HS05, WF06) ---------------------------------------------------------------


def facility(factory: sessionmaker[Session], api: Api, kind: str) -> str:
    """A synthetic organisation of the given care level, with one site."""
    tid, now = api.tenant.tenant_id, datetime.now(UTC)
    org, site = uuid.uuid7(), uuid.uuid7()
    with factory() as s, s.begin():
        s.add(Party(tenant_id=tid, id=org, recorded_at=now, party_type="organisation"))
        s.flush()
        s.add(
            Organisation(
                tenant_id=tid,
                id=org,
                recorded_at=now,
                organisation_code=f"{kind[:8].upper()}-{org.hex[-6:]}",
                organisation_name=f"Synthetic {kind.replace('_', ' ')}",
                organisation_type=kind,
            )
        )
        s.flush()
        s.add(
            OrganisationSite(
                tenant_id=tid,
                id=site,
                recorded_at=now,
                organisation_id=org,
                site_identifier=f"S-{site.hex[-10:]}",
                site_name="Main",
            )
        )
    return str(site)


def refer(api: Api, patient_id: str, who: str = "clinician", **extra: Any) -> Any:
    return api.post(
        who,
        "/v1/referrals",
        {
            "patient_id": patient_id,
            "referring_facility_id": str(api.tenant.facility_id),
            "receiving_facility_id": str(api.tenant.second_facility_id),
            "receiving_service": "cardiology",
            "requesting_service": "general_medicine",
            "reason": "Exertional chest pain, abnormal ECG",
            **extra,
        },
    )


def test_a_patient_without_care_records_cannot_be_referred(
    api: Api, factory: sessionmaker[Session]
) -> None:
    """CEDA revision 1.5: a referral, to a teaching hospital or anywhere else,
    carries the patient's existing care records. A patient with none is refused."""
    pid = register(api)
    # A care relationship exists (a team took the patient on), but nothing has
    # been recorded yet: no admission and no attended appointment.
    with factory() as s, s.begin():
        s.add(
            LegitimateRelationship(
                tenant_id=api.tenant.tenant_id,
                id=uuid.uuid7(),
                recorded_at=datetime.now(UTC),
                patient_id=uuid.UUID(pid),
                practitioner_id=api.tenant.practitioners["clinician"],
                start_at=datetime.now(UTC) - timedelta(minutes=5),
                creation_reason_code="team_allocation",
            )
        )
    refused = refer(api, pid, receiving_service="teaching_hospital_cardiology")
    assert code(refused) == (422, "no_care_records")
    assert "no care records" in refused.json()["error"]["message"]
    # Once there is a care episode, the same referral goes through with it.
    enc = admit(api, pid)
    accepted = refer(api, pid, receiving_service="teaching_hospital_cardiology")
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["source_encounter_id"] == enc["id"]


def test_referral_from_submission_to_closure(api: Api, factory: sessionmaker[Session]) -> None:
    pid = register(api)
    enc = admit(api, pid)
    other = register(api, "55566677788")
    other_enc = admit(api, other, visit="V-OTHER")
    assert refer(api, pid, who="clinician2").status_code == 404  # no care relationship
    assert code(refer(api, pid, encounter_id=other_enc["id"])) == (
        422,
        "encounter_patient_mismatch",
    )
    routine = refer(api, pid, encounter_id=enc["id"])
    assert routine.status_code == 201, routine.text
    ref = routine.json()
    assert (ref["status"], ref["source_encounter_id"]) == ("submitted", enc["id"])
    urgent = refer(api, other, priority="urgent").json()

    worklist = api.get("scheduler", "/v1/referrals?receiving_service=cardiology")
    assert worklist.status_code == 200, worklist.text
    assert [r["id"] for r in worklist.json()] == [urgent["id"], ref["id"]]  # urgent first
    assert api.get("clinician", "/v1/referrals").status_code == 403

    path = f"/v1/referrals/{ref['id']}/decision"
    assert code(api.post("scheduler", path, {"decision": "rejected"}, **if_match(1))) == (
        422,
        "reason_required",
    )
    accepted = api.post("scheduler", path, {"decision": "accepted"}, **if_match(1))
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["decided_by_id"] == str(api.tenant.practitioners["scheduler"])
    rejected = api.post(
        "scheduler",
        f"/v1/referrals/{urgent['id']}/decision",
        {"decision": "rejected", "reason": "Refer to chest pain clinic instead"},
        **if_match(1),
    )
    assert rejected.json()["status"] == "rejected"

    slot1, slot2 = make_slots(api, count=2)
    h = hold(api, "scheduler", slot1["id"]).json()
    assert code(book(api, "scheduler", h["id"], other, referral_id=ref["id"])) == (
        422,
        "referral_patient_mismatch",
    )
    appt = book(api, "scheduler", h["id"], pid, referral_id=ref["id"])
    assert appt.status_code == 201, appt.text
    assert [r["id"] for r in api.get("scheduler", "/v1/referrals?status=scheduled").json()] == [
        ref["id"]
    ]
    # Cancelling puts the referral back on the waiting list; attending closes it.
    api.post(
        "scheduler",
        f"/v1/appointments/{appt.json()['id']}/cancel",
        {"reason": "clinic cancelled"},
        **if_match(1),
    )
    assert [r["id"] for r in api.get("scheduler", "/v1/referrals?status=accepted").json()] == [
        ref["id"]
    ]
    again = booked_with_referral(api, slot2["id"], pid, ref["id"])
    done = api.post(
        "registrar",
        f"/v1/appointments/{again['id']}/attendance",
        {"outcome": "attended"},
        **if_match(1),
    )
    assert done.status_code == 200, done.text
    assert [r["id"] for r in api.get("scheduler", "/v1/referrals?status=closed").json()] == [
        ref["id"]
    ]
    # A referral not yet accepted cannot be booked against.
    fresh = refer(api, pid).json()
    [slot3] = make_slots(api, starts_at=(TOMORROW + timedelta(days=1)).isoformat())
    h3 = hold(api, "scheduler", slot3["id"]).json()
    assert code(book(api, "scheduler", h3["id"], pid, referral_id=fresh["id"])) == (
        422,
        "invalid_transition",
    )
    with factory() as s:
        events = s.scalars(
            select(OutboxEvent.payload).where(
                OutboxEvent.tenant_id == api.tenant.tenant_id,
                OutboxEvent.event_type == "referral.submitted",
            )
        ).all()
    assert all("reason" not in e for e in events)  # clinical text stays out of events


def booked_with_referral(api: Api, slot_id: str, pid: str, referral_id: str) -> dict[str, Any]:
    h = hold(api, "scheduler", slot_id).json()
    r = book(api, "scheduler", h["id"], pid, referral_id=referral_id)
    assert r.status_code == 201, r.text
    return r.json()


def test_the_patients_history_goes_with_every_referral(
    api: Api, factory: sessionmaker[Session]
) -> None:
    """CEDA revision 1.5: a referral from a primary health centre (or any
    provider) to a general, teaching or specialist hospital always carries the
    patient's historical records. The package is built when the referral is
    submitted; the referrer cannot leave it out."""
    phc = facility(factory, api, "primary_health_centre")
    teaching = facility(factory, api, "teaching_hospital")
    pid = register(api)
    first = admit(api, pid, visit="V-PHC-1", facility_id=phc)
    o = order(api, pid, first["id"])
    report = release(api, o["id"])
    second = admit(api, pid, visit="V-PHC-2", facility_id=phc)
    admit(api, pid, visit="V-MH-1", facility_id=phc, sensitivity="mental_health")

    body = {"referring_facility_id": phc, "receiving_facility_id": teaching}
    assert code(refer(api, pid, referring_facility_id=phc, receiving_facility_id=phc)) == (
        422,
        "same_facility",
    )
    assert code(refer(api, pid, **{**body, "receiving_facility_id": str(uuid.uuid4())})) == (
        404,
        "not_found",
    )
    sent = refer(api, pid, **body)
    assert sent.status_code == 201, sent.text
    ref = sent.json()
    assert (ref["referring_level"], ref["receiving_level"]) == (
        "primary_health_centre",
        "teaching_hospital",
    )
    assert ref["records_count"] == 3 + 1 + 1  # three encounters, one order, one report
    # Care recorded after the referral is not part of what was sent.
    admit(api, pid, visit="V-PHC-3", facility_id=phc)

    # The teaching hospital's triage team reads the history it received.
    path = f"/v1/referrals/{ref['id']}/records"
    received = api.get("scheduler", path)
    assert received.status_code == 200, received.text
    pack = received.json()
    assert {e["id"] for e in pack["encounters"]} == {first["id"], second["id"]}
    assert pack["withheld_records"] == 1  # the mental health encounter is withheld
    assert [x["id"] for x in pack["orders"]] == [o["id"]]
    assert [r["id"] for r in pack["reports"]] == [report["id"]]
    assert pack["reports"][0]["observations"][0]["flag"] == "H"
    assert pack["patient"]["identifiers"][0]["value"] == "*******8901"
    assert "identifier.value" in pack["masked_fields"]
    # The referrer sees what they sent, unmasked.
    mine = api.get("clinician", path).json()
    assert mine["patient"]["identifiers"][0]["value"] == "12345678901"
    # Sensitive records stay withheld unless the reader holds that access too.
    assert len(mine["encounters"]) == 2 and mine["withheld_records"] == 1
    assert api.get("clinician2", path).status_code == 403
    assert api.get("scheduler", f"/v1/referrals/{uuid.uuid4()}/records").status_code == 404

    # A rejected referral no longer opens the package to the receiving side.
    api.post(
        "scheduler",
        f"/v1/referrals/{ref['id']}/decision",
        {"decision": "rejected", "reason": "Refer to the cardiology clinic instead"},
        **if_match(1),
    )
    assert code(api.get("scheduler", path)) == (403, "referral_rejected")
    assert api.get("clinician", path).status_code == 200  # the referrer still can
    with factory() as s:
        reads = s.execute(
            select(AuditEvent.outcome, AuditEvent.actor_subject).where(
                AuditEvent.tenant_id == api.tenant.tenant_id,
                AuditEvent.action == "referral.records",
            )
        ).all()
    assert [o for o, _ in reads].count("success") == 3
    assert [o for o, _ in reads].count("denied") == 2
