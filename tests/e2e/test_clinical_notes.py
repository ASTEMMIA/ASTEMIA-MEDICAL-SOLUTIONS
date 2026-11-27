"""Clinical notes (CEDA SA-07; UG02, WF01 step 3, ST04): draft, sign, amend.

A signed revision never changes; a correction is a new revision that points at
the one it replaces, and the original keeps its text and author. Staff without
signing permission cannot finalise a note, and nothing is signed against an
unidentified chart."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import Encounter, LegitimateRelationship, OutboxEvent
from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import admit, register


def if_match(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


def code(r: Any) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def write(api: Api, encounter_id: str, who: str = "clinician", **extra: Any) -> Any:
    body = {
        "note_type": "consultation",
        "title": "Admission clerking",
        "body": "Chest pain for 2 hours. ECG: ST depression V4-V6. Plan: troponin.",
        **extra,
    }
    return api.post(who, f"/v1/encounters/{encounter_id}/entries", body)


def nurse_cares_for(api: Api, factory: sessionmaker[Session], patient_id: str) -> None:
    with factory() as s, s.begin():
        s.add(
            LegitimateRelationship(
                tenant_id=api.tenant.tenant_id,
                id=uuid.uuid7(),
                recorded_at=datetime.now(UTC),
                patient_id=uuid.UUID(patient_id),
                practitioner_id=api.tenant.practitioners["nurse"],
                start_at=datetime.now(UTC) - timedelta(minutes=1),
                creation_reason_code="named_nurse",
            )
        )


def test_a_note_is_drafted_signed_and_amended_without_losing_the_original(
    api: Api, factory: sessionmaker[Session]
) -> None:
    pid = register(api)
    enc = admit(api, pid)
    created = write(api, enc["id"])
    assert created.status_code == 201, created.text
    entry = created.json()
    assert (entry["status"], entry["note_type"]) == ("draft", "consultation")
    assert [r["status"] for r in entry["revisions"]] == ["draft"]
    eid = entry["id"]
    assert api.get("clinician", f"/v1/patients/{pid}/chart").json()["entries"] == []
    assert write(api, enc["id"], who="clinician2").status_code == 404  # not in their care

    nurse_cares_for(api, factory, pid)
    draft = f"/v1/entries/{eid}/draft"
    better = {"body": "Chest pain for 2 hours, radiating to the left arm. ECG: ST depression."}
    assert code(api.post("nurse", draft, better, **if_match(1))) == (403, "not_draft_author")
    edited = api.post("clinician", draft, better, **if_match(1))
    assert edited.status_code == 200, edited.text
    assert edited.json()["revisions"][0]["body"].endswith("ST depression.")
    # The nurse can read the chart but not the clinician's unsigned draft.
    assert api.get("nurse", f"/v1/entries/{eid}").json()["revisions"] == []

    sign = f"/v1/entries/{eid}/sign"
    assert code(api.post("clinician", sign, {})) == (428, "precondition_required")
    assert code(api.post("nurse", sign, {}, **if_match(2))) == (403, "no_signing_permission")
    signed = api.post("clinician", sign, {}, **if_match(2))
    assert signed.status_code == 200, signed.text
    assert signed.json()["status"] == "signed"
    first = signed.json()["revisions"][0]
    assert first["signed_by_id"] == str(api.tenant.practitioners["clinician"])
    assert code(api.post("clinician", draft, better, **if_match(3))) == (409, "no_draft")
    assert code(api.post("clinician", sign, {}, **if_match(3))) == (409, "no_draft")
    [shown] = api.get("clinician", f"/v1/patients/{pid}/chart").json()["entries"]
    assert (shown["id"], shown["revision_number"], shown["body"]) == (eid, 1, first["body"])

    # A correction is a new revision that points at the signed one.
    amend = f"/v1/entries/{eid}/amendments"
    fix = {"body": "Chest pain for 3 hours (not 2), radiating to the left arm.", "reason": "Time"}
    assert api.post("clinician", amend, {**fix, "reason": ""}, **if_match(3)).status_code == 422
    amended = api.post("nurse", amend, fix, **if_match(3))  # an authorised colleague
    assert amended.status_code == 200, amended.text
    second = amended.json()["revisions"][1]
    assert (second["status"], second["supersedes_id"]) == ("draft", first["id"])
    assert code(api.post("nurse", amend, fix, **if_match(4))) == (409, "draft_exists")
    # Until the correction is signed, the chart shows the signed text.
    assert (
        api.get("clinician", f"/v1/patients/{pid}/chart").json()["entries"][0]["body"]
        == (first["body"])
    )
    # The nurse drafted a consultation correction but cannot sign one.
    assert code(api.post("nurse", sign, {}, **if_match(4))) == (403, "no_signing_permission")
    assert code(api.post("clinician", sign, {}, **if_match(4))) == (403, "not_draft_author")
    assert api.post("clinician", amend, fix, **if_match(4)).status_code == 409


def test_an_amendment_is_signed_and_the_original_stays(
    api: Api, factory: sessionmaker[Session]
) -> None:
    pid = register(api)
    enc = admit(api, pid)
    eid = write(api, enc["id"]).json()["id"]
    api.post("clinician", f"/v1/entries/{eid}/sign", {}, **if_match(1))
    original = api.get("clinician", f"/v1/entries/{eid}").json()["revisions"][0]
    fix = {"body": "Troponin 85 ng/L: NSTEMI. Started on the ACS protocol.", "reason": "Result"}
    api.post("clinician", f"/v1/entries/{eid}/amendments", fix, **if_match(2))
    done = api.post("clinician", f"/v1/entries/{eid}/sign", {}, **if_match(3))
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "amended"
    first, second = done.json()["revisions"]
    assert first == original  # untouched: text, author and signature
    assert (second["revision_number"], second["amendment_reason"]) == (2, "Result")
    [shown] = api.get("clinician", f"/v1/patients/{pid}/chart").json()["entries"]
    assert (shown["status"], shown["revision_number"], shown["body"]) == (
        "amended",
        2,
        fix["body"],
    )
    with factory() as s:
        events = s.scalars(
            select(OutboxEvent.payload).where(
                OutboxEvent.tenant_id == api.tenant.tenant_id,
                OutboxEvent.event_type == "clinical_entry.signed",
            )
        ).all()
    assert [e["amendment"] for e in events] == [False, True]
    assert all("body" not in e for e in events)  # note text never in events


def test_nurses_sign_their_own_nursing_notes_only(api: Api, factory: sessionmaker[Session]) -> None:
    pid = register(api)
    enc = admit(api, pid)
    nurse_cares_for(api, factory, pid)
    note = write(api, enc["id"], who="nurse", note_type="nursing", body="Settled overnight.")
    assert note.status_code == 201, note.text
    signed = api.post("nurse", f"/v1/entries/{note.json()['id']}/sign", {}, **if_match(1))
    assert signed.status_code == 200, signed.text
    progress = write(api, enc["id"], who="nurse", note_type="progress", body="Ate lunch.")
    assert code(
        api.post("nurse", f"/v1/entries/{progress.json()['id']}/sign", {}, **if_match(1))
    ) == (403, "no_signing_permission")


def test_no_signed_note_against_an_unidentified_chart(api: Api) -> None:
    arrival = api.post(
        "registrar",
        "/v1/patients",
        {
            "family_name": "Unknown",
            "given_names": "Male",
            "birth_date": "1980-01-01",
            "birth_date_precision": "year",
            "administrative_sex": "male",
            "temporary": True,
        },
    ).json()
    enc = admit(api, arrival["id"], visit="V-UNK")
    draft = write(api, enc["id"])
    assert draft.status_code == 201  # drafting is allowed while identity is resolved
    amend = {"body": "Corrected", "reason": "Typo"}
    assert code(
        api.post("clinician", f"/v1/entries/{draft.json()['id']}/amendments", amend, **if_match(1))
    ) == (409, "not_signed")  # a draft is edited, not amended
    assert code(
        api.post("clinician", f"/v1/entries/{draft.json()['id']}/sign", {}, **if_match(1))
    ) == (422, "patient_unidentified")


def test_sensitive_notes_are_withheld_and_dead_encounters_refuse_notes(
    api: Api, factory: sessionmaker[Session]
) -> None:
    pid = register(api)
    enc = admit(api, pid)
    note = write(
        api,
        enc["id"],
        note_type="mental_health_assessment",
        body="Low mood, passive suicidal ideation, no plan.",
        sensitivity="mental_health",
    ).json()
    api.post("clinician", f"/v1/entries/{note['id']}/sign", {}, **if_match(1))
    chart = api.get("clinician", f"/v1/patients/{pid}/chart").json()
    assert chart["entries"] == [] and chart["withheld_records"] == 1
    assert api.get("clinician", f"/v1/entries/{note['id']}").status_code == 404
    assert api.get("clinician", f"/v1/entries/{uuid.uuid4()}").status_code == 404
    with factory() as s, s.begin():
        s.execute(
            update(Encounter).where(Encounter.id == uuid.UUID(enc["id"])).values(state="cancelled")
        )
    assert code(write(api, enc["id"])) == (422, "encounter_not_writable")
    assert write(api, str(uuid.uuid4())).status_code == 404
