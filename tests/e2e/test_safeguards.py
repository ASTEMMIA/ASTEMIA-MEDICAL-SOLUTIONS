"""Mental health safeguards (CEDA HS13, B11; ICRS 5.5.9-5.5.15): restrictive
practice logged and independently reviewed, legal status with history and
expiry, concerns answered by someone independent, and an access report for a
safeguarding lead or the patient's advocate."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import (
    Membership,
    MentalHealthLegalStatus,
    OutboxEvent,
    SafeguardingConcern,
)
from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import admit, register

NOW = datetime.now(UTC)


def if_match(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


def code(r: Any) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def ids(api: Api, *who: str) -> list[str]:
    return [str(api.tenant.practitioners[w]) for w in who]


def record(api: Api, pid: str, who: str = "clinician", **extra: Any) -> Any:
    body = {
        "patient_id": pid,
        "intervention_type": "seclusion",
        "reason": "Assaulted another patient; de-escalation and time out failed",
        "authorised_by_id": str(api.tenant.practitioners["clinician"]),
        "staff_ids": ids(api, "clinician", "nurse"),
        "started_at": (NOW - timedelta(hours=2)).isoformat(),
        **extra,
    }
    return api.post(who, "/v1/restrictive-interventions", body)


def legal(api: Api, pid: str, status: str, **extra: Any) -> Any:
    body = {
        "status": status,
        "valid_from": (NOW - timedelta(days=1)).isoformat(),
        "authorised_by_id": str(api.tenant.practitioners["clinician"]),
        "reason": "Assessed by two doctors; risk to others, refuses admission",
        **extra,
    }
    return api.post("clinician", f"/v1/patients/{pid}/legal-status", body)


def detained(api: Api, pid: str, days: float = 28) -> Any:
    r = legal(
        api,
        pid,
        "detained_treatment",
        legal_basis="National Mental Health Act 2021, treatment order",
        valid_until=(NOW + timedelta(days=days)).isoformat(),
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_legal_status_has_history_expiry_and_shows_on_the_chart(
    api: Api, factory: sessionmaker[Session]
) -> None:
    pid = register(api)
    admit(api, pid)
    assert code(legal(api, pid, "detained_assessment")) == (422, "legal_basis_required")
    assert code(legal(api, pid, "informal", valid_until=(NOW + timedelta(days=1)).isoformat())) == (
        422,
        "bad_time",
    )
    assert legal(api, pid, "informal").status_code == 201
    assert (
        api.post(
            "clinician2",
            f"/v1/patients/{pid}/legal-status",
            {
                "status": "informal",
                "valid_from": NOW.isoformat(),
                "authorised_by_id": ids(api, "clinician2")[0],
                "reason": "no relationship with this patient",
            },
        ).status_code
        == 404
    )
    order = detained(api, pid, days=2)  # expires within the 72-hour warning
    assert (order["current"], order["lapsed"], order["expiring"]) == (True, False, True)

    chart = api.get("clinician", f"/v1/patients/{pid}/chart").json()
    assert chart["legal_status"]["status"] == "detained_treatment"
    assert chart["legal_status"]["legal_basis"]  # shown for safety
    assert chart["legal_status"]["reason"] is None  # mental health detail, withheld
    admit(
        api,
        pid,
        visit="V-PSY",
        responsible_practitioner_id=str(api.tenant.practitioners["psychiatrist"]),
    )
    granted = api.get("psychiatrist", f"/v1/patients/{pid}/chart").json()
    assert granted["legal_status"]["reason"]  # with the mental health grant
    history = api.get("lead", f"/v1/patients/{pid}/legal-status").json()
    assert [(h["status"], h["current"]) for h in history] == [
        ("detained_treatment", True),
        ("informal", False),
    ]
    assert history[1]["ended_at"] is not None
    assert [x["id"] for x in api.get("lead", "/v1/legal-status/expiring").json()] == [order["id"]]
    assert api.get("clinician", "/v1/legal-status/expiring").status_code == 403

    # The power lapses with nothing recorded to replace it.
    with factory() as s, s.begin():
        s.execute(
            update(MentalHealthLegalStatus)
            .where(MentalHealthLegalStatus.id == uuid.UUID(order["id"]))
            .values(valid_until=NOW - timedelta(minutes=5))
        )
    chart = api.get("clinician", f"/v1/patients/{pid}/chart").json()
    assert chart["legal_status"]["lapsed"] is True
    # Judged at the moment it starts: an intervention after the lapse is flagged.
    flagged = record(api, pid, started_at=(NOW - timedelta(minutes=1)).isoformat()).json()
    assert flagged["flags"] == ["detention_lapsed"]
    with factory() as s:
        changes = s.scalars(
            select(OutboxEvent.payload).where(
                OutboxEvent.tenant_id == api.tenant.tenant_id,
                OutboxEvent.event_type == "mental_health_legal_status.changed",
            )
        ).all()
    assert [c["status"] for c in changes] == ["informal", "detained_treatment"]
    assert all("reason" not in c for c in changes)


def test_restrictive_interventions_are_logged_and_independently_reviewed(
    api: Api, factory: sessionmaker[Session]
) -> None:
    pid = register(api)
    enc = admit(api, pid)
    unrecorded = record(api, pid, encounter_id=enc["id"])
    assert unrecorded.status_code == 201, unrecorded.text
    assert unrecorded.json()["flags"] == ["no_legal_status"]

    legal(api, pid, "informal")
    informal = record(api, pid, intervention_type="physical_restraint").json()
    assert informal["flags"] == ["informal_patient"]  # restrained while not detained

    detained(api, pid)
    r = record(api, pid, staff_ids=ids(api, "nurse", "lead"))
    assert r.status_code == 201, r.text
    seclusion = r.json()
    assert seclusion["flags"] == [] and seclusion["recorded_by_id"] == ids(api, "clinician")[0]
    assert seclusion["review_overdue"] is False

    assert record(api, pid, who="clinician2").status_code == 404  # no care relationship
    assert record(api, pid, who="lead").status_code == 404  # leads do not record (concealed)
    future = (NOW + timedelta(hours=1)).isoformat()
    assert code(record(api, pid, started_at=future)) == (422, "bad_time")
    stranger = register(api, "70000000001")
    other_enc = admit(api, stranger, visit="V-OTHER")
    assert code(record(api, pid, encounter_id=other_enc["id"])) == (
        422,
        "encounter_patient_mismatch",
    )

    # Ending is recorded once; nothing else about the entry can change.
    end = f"/v1/restrictive-interventions/{seclusion['id']}/end"
    body = {
        "ended_at": (NOW - timedelta(minutes=30)).isoformat(),
        "debrief_offered": True,
        "injury": True,
        "injury_detail": "Graze to the left forearm",
    }
    assert code(api.post("clinician", end, body)) == (428, "precondition_required")
    ended = api.post("clinician", end, body, **if_match(1))
    assert ended.status_code == 200, ended.text
    assert (ended.json()["duration_minutes"], ended.json()["flags"]) == (90, ["injury"])
    assert code(api.post("clinician", end, body, **if_match(2))) == (422, "already_ended")
    assert api.post("clinician2", end, body, **if_match(2)).status_code == 404
    missing = f"/v1/restrictive-interventions/{uuid.uuid4()}/end"
    assert api.post("clinician", missing, body, **if_match(1)).status_code == 404

    queue = api.get("lead", "/v1/restrictive-interventions")
    assert queue.status_code == 200, queue.text
    assert len(queue.json()) == 3
    assert api.get("clinician", "/v1/restrictive-interventions").status_code == 403

    review = f"/v1/restrictive-interventions/{seclusion['id']}/review"
    verdict = {"outcome": "concerns", "note": "Seclusion ran on after the patient settled"}
    assert code(api.post("lead", review, verdict, **if_match(2))) == (
        422,
        "conflict_of_interest",
    )  # the lead took part
    assert code(api.post("unlinked_lead", review, verdict, **if_match(2))) == (
        403,
        "no_practitioner",
    )
    done = api.post("lead2", review, verdict, **if_match(2))
    assert done.status_code == 200, done.text
    assert (done.json()["review_outcome"], done.json()["reviewed_by_id"]) == (
        "concerns",
        ids(api, "lead2")[0],
    )
    assert code(api.post("lead2", review, verdict, **if_match(3))) == (422, "already_reviewed")
    reviewed = api.get("lead", "/v1/restrictive-interventions?reviewed=true").json()
    assert [x["id"] for x in reviewed] == [seclusion["id"]]

    # The care team and the patient's advocate see the log; others do not.
    log = f"/v1/patients/{pid}/restrictive-interventions"
    assert len(api.get("clinician", log).json()) == 3
    assert api.get("advocate", log).status_code == 404  # not yet appointed
    assert code(
        api.post(
            "lead",
            f"/v1/patients/{pid}/advocates",
            {"practitioner_id": ids(api, "nurse")[0]},
        )
    ) == (422, "not_an_advocate")
    # An advocate whose membership has lapsed cannot be appointed.
    with factory() as s, s.begin():
        s.execute(
            update(Membership)
            .where(
                Membership.tenant_id == api.tenant.tenant_id,
                Membership.subject == api.tenant.subject("advocate"),
            )
            .values(valid_to=datetime.now(UTC) - timedelta(days=1))
        )
    advocate = {"practitioner_id": ids(api, "advocate")[0]}
    assert code(api.post("lead", f"/v1/patients/{pid}/advocates", advocate)) == (
        422,
        "not_an_advocate",
    )
    with factory() as s, s.begin():
        s.execute(
            update(Membership)
            .where(
                Membership.tenant_id == api.tenant.tenant_id,
                Membership.subject == api.tenant.subject("advocate"),
            )
            .values(valid_to=None)
        )
    appointed = api.post("lead", f"/v1/patients/{pid}/advocates", advocate)
    assert appointed.status_code == 201, appointed.text
    assert len(api.get("advocate", log).json()) == 3
    assert api.get("advocate", f"/v1/patients/{pid}/chart").status_code == 404  # no chart
    assert len(api.get("advocate", f"/v1/patients/{pid}/legal-status").json()) == 2
    with factory() as s:
        payloads = s.scalars(
            select(OutboxEvent.payload).where(
                OutboxEvent.tenant_id == api.tenant.tenant_id,
                OutboxEvent.event_type == "restrictive_intervention.recorded",
            )
        ).all()
    assert len(payloads) == 3 and all("reason" not in p for p in payloads)


def test_concerns_are_answered_by_someone_independent(
    api: Api, factory: sessionmaker[Session]
) -> None:
    pid = register(api)

    def raise_(who: str, **extra: Any) -> Any:
        body = {
            "patient_id": pid,
            "raised_by": "family",
            "raised_by_name": "Bisi Adeyemi (mother)",
            "category": "dignity",
            "description": "My daughter was left in soiled clothes overnight",
            **extra,
        }
        return api.post(who, "/v1/safeguarding-concerns", body)

    about_clinician = raise_("registrar", about_practitioner_id=ids(api, "clinician")[0])
    assert about_clinician.status_code == 201, about_clinician.text
    ack = about_clinician.json()
    assert set(ack) == {"id", "status", "respond_by"}  # an acknowledgement, not the record
    about_lead = raise_("nurse", raised_by="staff", about_practitioner_id=ids(api, "lead")[0])
    assert about_lead.status_code == 201
    assert raise_("scheduler").status_code == 403
    assert code(raise_("registrar", patient_id=str(uuid.uuid4()))) == (404, "not_found")

    worklist = api.get("lead", "/v1/safeguarding-concerns")
    assert worklist.status_code == 200, worklist.text
    assert {c["id"] for c in worklist.json()} == {ack["id"], about_lead.json()["id"]}
    first = next(c for c in worklist.json() if c["id"] == ack["id"])
    assert first["recorded_by"] == api.tenant.subject("registrar")
    assert api.get("clinician", "/v1/safeguarding-concerns").status_code == 403

    outcome = {"outcome": "upheld", "note": "Night staff retrained; family informed"}
    path = f"/v1/safeguarding-concerns/{ack['id']}/outcome"
    closed = api.post("lead", path, outcome, **if_match(1))
    assert closed.status_code == 200, closed.text
    assert (closed.json()["status"], closed.json()["closed_by_id"]) == (
        "upheld",
        ids(api, "lead")[0],
    )
    assert code(api.post("lead", path, outcome, **if_match(2))) == (422, "invalid_transition")
    theirs = f"/v1/safeguarding-concerns/{about_lead.json()['id']}/outcome"
    assert code(api.post("lead", theirs, outcome, **if_match(1))) == (
        422,
        "conflict_of_interest",
    )
    upheld = api.get("lead", "/v1/safeguarding-concerns?status=upheld").json()
    assert [c["id"] for c in upheld] == [ack["id"]]

    with factory() as s, s.begin():
        s.execute(
            update(SafeguardingConcern)
            .where(SafeguardingConcern.id == uuid.UUID(about_lead.json()["id"]))
            .values(respond_by=NOW - timedelta(hours=1))
        )
    [late] = api.get("lead", "/v1/safeguarding-concerns").json()
    assert late["overdue"] is True
    no = api.post(
        "lead2", theirs, {"outcome": "not_upheld", "note": "CCTV reviewed"}, **if_match(1)
    )
    assert no.json()["status"] == "not_upheld"


def test_access_report_shows_who_touched_the_record(api: Api) -> None:
    pid = register(api)
    admit(api, pid)
    api.get("clinician", f"/v1/patients/{pid}/chart")
    api.get("clinician2", f"/v1/patients/{pid}/chart")  # refused
    grant = api.post(
        "clinician2",
        "/v1/emergency-grants",
        {"patient_id": pid, "purpose": "Covering the ward overnight, patient agitated"},
    )
    assert grant.status_code == 201, grant.text
    api.get("clinician2", f"/v1/patients/{pid}/chart")

    report = api.get("lead", f"/v1/patients/{pid}/access-report")
    assert report.status_code == 200, report.text
    out = report.json()
    by = {(e["actor_subject"], e["action"], e["outcome"]): e["flags"] for e in out["entries"]}
    clinician2 = api.tenant.subject("clinician2")
    assert "denied" in by[(clinician2, "chart.read", "denied")]
    assert "emergency_access" in by[(clinician2, "chart.read", "success")]
    summary = {a["actor_subject"]: a for a in out["by_actor"]}
    assert summary[clinician2]["flagged"] >= 2
    assert summary[api.tenant.subject("registrar")]["entries"] == 2  # register, admit
    assert out["flagged"] >= 2
    later = (NOW + timedelta(days=1)).isoformat().replace("+", "%2B")
    assert api.get("lead", f"/v1/patients/{pid}/access-report?from={later}").json()["entries"] == []
    # Only the safeguarding lead and the patient's own advocate see it.
    assert api.get("advocate", f"/v1/patients/{pid}/access-report").status_code == 404
    assert api.get("nurse", f"/v1/patients/{pid}/access-report").status_code == 404
    api.post("lead", f"/v1/patients/{pid}/advocates", {"practitioner_id": ids(api, "advocate")[0]})
    mine = api.get("advocate", f"/v1/patients/{pid}/access-report")
    assert mine.status_code == 200
    # Reading the report is itself on the record.
    actions = {e["action"] for e in mine.json()["entries"]}
    assert "access_report.read" in actions


def test_a_lead_cannot_read_a_patient_who_is_not_in_the_tenant(api: Api) -> None:
    """Tenant isolation: the lead's reads are not bound to a care relationship,
    so the patient's existence in the tenant is checked on its own."""
    unknown = uuid.uuid4()
    for path in ("restrictive-interventions", "legal-status", "access-report"):
        assert api.get("lead", f"/v1/patients/{unknown}/{path}").status_code == 404
