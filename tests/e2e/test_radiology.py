"""Radiology and imaging (CEDA HS07, WF05 step 1; UAT WF05).

A request is vetted, scheduled, performed when its study arrives and reported.
A study joins the chart only when its accession number and patient identity
agree with the order; otherwise it waits for reconciliation. An addendum keeps
the original report. The PACS viewer opens only the study its token names.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import (
    ImagingRequest,
    ImagingStudy,
    ResultReview,
    ServiceRequest,
    Task,
)
from astemia.adapters.pacs import ViewerClaims, ViewerTokens
from astemia.config import Settings
from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import admit, register

NOW = datetime.now(UTC)
CHEST = {
    "code_system": "http://loinc.org",
    "code": "36643-5",
    "display": "XR Chest 2 Views",
    "modality": "DX",
    "body_site": "Chest",
    "laterality": "not_applicable",
    "clinical_note": "Cough for three weeks and weight loss",
}


def if_match(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


def code(r: Any) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def request(api: Api, pid: str, enc: dict[str, Any], who: str = "clinician", **x: Any) -> Any:
    return api.post(
        who, "/v1/imaging-requests", {"patient_id": pid, "encounter_id": enc["id"], **CHEST, **x}
    )


def step(api: Api, who: str, rid: str, verb: str, version: int, body: dict[str, Any]) -> Any:
    return api.post(who, f"/v1/imaging-requests/{rid}/{verb}", body, **if_match(version))


def scheduled(api: Api, pid: str, enc: dict[str, Any]) -> dict[str, Any]:
    rid = request(api, pid, enc).json()["id"]
    step(api, "radiologist", rid, "vet", 1, {"decision": "accepted", "protocol": "PA and lateral"})
    out = step(api, "radiographer", rid, "schedule", 2, {"scheduled_at": NOW.isoformat()})
    assert out.status_code == 200, out.text
    return out.json()


def study(api: Api, accession: str, nin: str = "12345678901", **x: Any) -> Any:
    return api.post(
        "radiographer",
        "/v1/imaging-studies",
        {
            "study_instance_uid": f"1.2.826.0.1.{uuid.uuid4().int % 10**12}",
            "accession_number": accession,
            "modality": "DX",
            "performed_at": NOW.isoformat(),
            "pacs_reference": "pacs://studies/abc",
            "patient_identifier": {"issuer": "NG-NIN", "value": nin},
            "birth_date": "1984-03-09",
            **x,
        },
    )


def test_a_request_is_vetted_scheduled_performed_and_reported(
    api: Api, factory: sessionmaker[Session]
) -> None:
    pid = register(api)
    enc = admit(api, pid)
    made = request(api, pid, enc)
    assert made.status_code == 201, made.text
    rid = made.json()["id"]
    assert made.json()["state"] == "requested"
    assert request(api, pid, enc, who="clinician2").status_code == 404  # not in their care
    waiting = api.get("radiologist", "/v1/imaging-requests?state=requested").json()
    assert [r["id"] for r in waiting] == [rid]
    assert api.get("clinician", "/v1/imaging-requests?state=requested").status_code == 403

    assert code(step(api, "radiologist", rid, "vet", 1, {"decision": "accepted"})) == (
        422,
        "protocol_required",
    )
    assert code(step(api, "radiographer", rid, "vet", 1, {"decision": "accepted"})) == (
        403,
        "missing_capability",
    )
    vetted = step(api, "radiologist", rid, "vet", 1, {"decision": "accepted", "protocol": "PA"})
    assert vetted.json()["state"] == "vetted" and vetted.json()["protocol"] == "PA"
    assert code(
        step(api, "radiologist", rid, "report", 2, {"findings": "x", "conclusion": "y"})
    ) == (
        422,
        "invalid_transition",
    )
    booked = step(api, "radiographer", rid, "schedule", 2, {"scheduled_at": NOW.isoformat()})
    accession = booked.json()["accession_number"]
    assert accession.startswith("ACC") and booked.json()["state"] == "scheduled"

    arrived = study(api, accession)
    assert arrived.status_code == 201, arrived.text
    assert arrived.json()["status"] == "linked" and arrived.json()["patient_id"] == pid
    assert arrived.json()["received_identifier"] is None  # identity only on reconciliation
    uid = arrived.json()["study_instance_uid"]
    assert code(study(api, accession, study_instance_uid=uid)) == (409, "study_exists")
    # A further series joins the performed request.
    assert study(api, accession).json()["status"] == "linked"
    current = api.get("radiologist", f"/v1/imaging-requests/{rid}").json()
    assert current["state"] == "performed" and len(current["studies"]) == 2

    findings = {"findings": "Lungs clear. Heart size normal.", "conclusion": "Normal chest."}
    # A report is signed by a named radiologist, never by an account without one.
    unsigned = step(api, "unlinked_radiologist", rid, "report", current["version"], findings)
    assert code(unsigned) == (403, "no_practitioner")
    signed = step(api, "radiologist", rid, "report", current["version"], findings)
    assert signed.status_code == 201, signed.text
    [rep] = signed.json()["reports"]
    assert (rep["status"], rep["presented_form"], rep["conclusion"]) == (
        "final",
        "Lungs clear. Heart size normal.",
        "Normal chest.",
    )
    v = signed.json()["version"]
    assert code(step(api, "radiologist", rid, "report", v, findings)) == (409, "already_reported")
    # On the chart, with one open review for the requesting clinician.
    chart = api.get("clinician", f"/v1/patients/{pid}/chart").json()
    assert [r["id"] for r in chart["reports"]] == [rep["id"]]
    with factory() as s:
        order = s.get(
            ServiceRequest, (api.tenant.tenant_id, uuid.UUID(signed.json()["service_request_id"]))
        )
        assert order is not None and order.status == "completed" and order.filler_id == accession
        reviews = s.scalars(
            select(ResultReview.state).where(ResultReview.report_id == uuid.UUID(rep["id"]))
        ).all()
    assert reviews == ["open"]


def test_an_addendum_keeps_the_original_report(api: Api, factory: sessionmaker[Session]) -> None:
    """CEDA HS07 acceptance."""
    pid = register(api)
    enc = admit(api, pid)
    req = scheduled(api, pid, enc)
    rid = req["id"]
    assert code(step(api, "radiologist", rid, "addenda", 3, {"text": "x"})) == (409, "not_reported")
    study(api, req["accession_number"])
    findings = {"findings": "No fracture.", "conclusion": "Normal."}
    first = step(api, "radiologist", rid, "report", 4, findings).json()
    added = step(
        api, "radiologist", rid, "addenda", 5, {"text": "Subtle fracture of the fifth rib."}
    )
    assert added.status_code == 201, added.text
    original, addendum = added.json()["reports"]
    assert original["id"] == first["reports"][0]["id"]
    assert original["presented_form"] == "No fracture."  # kept, unchanged
    assert (addendum["status"], addendum["prior_report_id"]) == ("amended", original["id"])
    assert addendum["conclusion"] == "Normal."
    quiet = step(
        api, "radiologist", rid, "addenda", 6, {"text": "Typo corrected.", "needs_review": False}
    )
    assert len(quiet.json()["reports"]) == 3
    with factory() as s:
        states = dict(
            s.execute(
                select(ResultReview.report_id, ResultReview.state).where(
                    ResultReview.patient_id == uuid.UUID(pid)
                )
            ).all()
        )
    # The addendum that needed review superseded the first review and opened
    # one; the one that did not left it alone.
    assert states == {
        uuid.UUID(original["id"]): "superseded",
        uuid.UUID(addendum["id"]): "open",
    }


def test_a_study_with_a_conflicting_identity_stays_off_the_chart(
    api: Api, factory: sessionmaker[Session]
) -> None:
    """CEDA HS07 acceptance; WF05 step 1: mismatches go to reconciliation."""
    pid = register(api)
    enc = admit(api, pid)
    req = scheduled(api, pid, enc)
    stranger = study(api, req["accession_number"], nin="71111111111")
    assert stranger.json()["status"] == "identity_conflict"
    assert stranger.json()["conflicts"] == ["identifier"]
    assert stranger.json()["patient_id"] is None
    wrong_date = study(api, req["accession_number"], birth_date="1990-01-01")
    assert wrong_date.json()["conflicts"] == ["birth_date"]
    lost = study(api, "ACC-NOWHERE")
    assert (lost.json()["status"], lost.json()["conflicts"]) == ("unmatched", ["accession_number"])
    current = api.get("clinician", f"/v1/imaging-requests/{req['id']}").json()
    assert current["studies"] == [] and current["state"] == "scheduled"
    assert api.get("clinician", f"/v1/patients/{pid}/chart").json()["reports"] == []
    # No viewer for a study kept off the chart.
    sid = stranger.json()["id"]
    assert api.post("clinician", f"/v1/imaging-studies/{sid}/viewer", {}).status_code == 404

    queue = api.get("radiographer", "/v1/imaging-studies/unlinked").json()
    assert [q["id"] for q in queue] == [sid, wrong_date.json()["id"], lost.json()["id"]]
    assert queue[0]["received_identifier"] == "71111111111"
    assert api.get("clinician", "/v1/imaging-studies/unlinked").status_code == 403

    # After checking with the patient, the radiographer links the dated study.
    linked = api.post(
        "radiographer",
        f"/v1/imaging-studies/{wrong_date.json()['id']}/link",
        {"imaging_request_id": req["id"], "reason": "Date of birth confirmed with the patient"},
        **if_match(1),
    )
    assert linked.status_code == 200, linked.text
    assert (linked.json()["status"], linked.json()["patient_id"]) == ("linked", pid)
    assert linked.json()["link_reason"] == "Date of birth confirmed with the patient"
    again = api.post(
        "radiographer",
        f"/v1/imaging-studies/{wrong_date.json()['id']}/link",
        {"imaging_request_id": req["id"], "reason": "again"},
        **if_match(2),
    )
    assert code(again) == (409, "already_linked")
    assert api.get("clinician", f"/v1/imaging-requests/{req['id']}").json()["state"] == "performed"

    # A request not yet booked takes no study, by accession or by link.
    early = request(api, pid, enc).json()
    assert code(
        api.post(
            "radiographer",
            f"/v1/imaging-studies/{lost.json()['id']}/link",
            {"imaging_request_id": early["id"], "reason": "x"},
            **if_match(1),
        )
    ) == (422, "request_state")
    with factory() as s, s.begin():
        s.execute(
            update(ImagingRequest)
            .where(ImagingRequest.id == uuid.UUID(early["id"]))
            .values(accession_number="ACC-EARLY")
        )
    assert study(api, "ACC-EARLY").json()["conflicts"] == ["request_state"]


def test_a_rejected_request_revokes_the_order_and_tells_the_requester(
    api: Api, factory: sessionmaker[Session]
) -> None:
    pid = register(api)
    enc = admit(api, pid)
    rid = request(api, pid, enc).json()["id"]
    assert code(step(api, "radiologist", rid, "vet", 1, {"decision": "rejected"})) == (
        422,
        "reason_required",
    )
    no = step(
        api,
        "radiologist",
        rid,
        "vet",
        1,
        {"decision": "rejected", "reason": "Ultrasound is the right first test"},
    )
    assert no.json()["state"] == "rejected"
    assert no.json()["vetting_note"] == "Ultrasound is the right first test"
    with factory() as s:
        order = s.get(
            ServiceRequest, (api.tenant.tenant_id, uuid.UUID(no.json()["service_request_id"]))
        )
        assert order is not None and order.status == "revoked"
        [task] = s.scalars(select(Task).where(Task.origin_id == uuid.UUID(rid))).all()
        assert task.assignee_id == api.tenant.practitioners["clinician"]
    assert code(
        step(api, "radiographer", rid, "schedule", 2, {"scheduled_at": NOW.isoformat()})
    ) == (
        422,
        "invalid_transition",
    )


def test_the_viewer_opens_only_the_study_its_token_names(
    api: Api, settings: Settings, factory: sessionmaker[Session]
) -> None:
    """UAT WF05: PACS access for a different patient is refused."""
    pid = register(api)
    enc = admit(api, pid)
    mine = study(api, scheduled(api, pid, enc)["accession_number"]).json()
    other_pid = register(api, "71111111111")
    other_enc = admit(api, other_pid, visit="V-2")
    theirs = study(api, scheduled(api, other_pid, other_enc)["accession_number"], nin="71111111111")
    theirs = theirs.json()

    access = api.post("clinician", f"/v1/imaging-studies/{mine['id']}/viewer", {})
    assert access.status_code == 200, access.text
    token = access.json()["token"]
    assert access.json()["url"].startswith(settings.pacs_viewer_url)
    ok = api.client.post(
        "/v1/pacs/check", json={"token": token, "study_instance_uid": mine["study_instance_uid"]}
    )
    assert ok.status_code == 200 and ok.json()["patient_id"] == pid
    refused = api.client.post(
        "/v1/pacs/check", json={"token": token, "study_instance_uid": theirs["study_instance_uid"]}
    )
    assert code(refused) == (403, "viewer_refused")
    forged = api.client.post(
        "/v1/pacs/check", json={"token": "x.y.z", "study_instance_uid": mine["study_instance_uid"]}
    )
    assert code(forged) == (403, "viewer_refused")
    stale, _, _ = ViewerTokens(settings).issue(
        ViewerClaims(
            api.tenant.tenant_id,
            uuid.UUID(pid),
            api.tenant.practitioners["clinician"],
            mine["study_instance_uid"],
        ),
        NOW - timedelta(hours=1),
    )
    expired = api.client.post(
        "/v1/pacs/check", json={"token": stale, "study_instance_uid": mine["study_instance_uid"]}
    )
    assert code(expired) == (403, "viewer_refused")
    # A study moved off the patient no longer opens with an earlier token.
    forged_patient, _, _ = ViewerTokens(settings).issue(
        ViewerClaims(
            api.tenant.tenant_id,
            uuid.UUID(other_pid),
            api.tenant.practitioners["clinician"],
            mine["study_instance_uid"],
        ),
        NOW,
    )
    moved = api.client.post(
        "/v1/pacs/check",
        json={"token": forged_patient, "study_instance_uid": mine["study_instance_uid"]},
    )
    assert code(moved) == (403, "viewer_refused")
    # Only the care team gets a viewer.
    assert api.post("clinician2", f"/v1/imaging-studies/{mine['id']}/viewer", {}).status_code == 404
    assert (
        api.post("clinician", f"/v1/imaging-studies/{uuid.uuid4()}/viewer", {}).status_code == 404
    )


def test_reads_follow_the_department_and_the_chart(
    api: Api, factory: sessionmaker[Session]
) -> None:
    pid = register(api)
    enc = admit(api, pid)
    req = scheduled(api, pid, enc)
    linked = study(api, req["accession_number"]).json()
    path = f"/v1/imaging-requests/{req['id']}"
    assert api.get("radiographer", path).status_code == 200  # the department
    assert api.get("clinician", path).status_code == 200  # the care team
    assert api.get("clinician2", path).status_code == 404
    assert api.get("clinician", f"/v1/imaging-requests/{uuid.uuid4()}").status_code == 404
    with factory() as s, s.begin():
        s.execute(
            update(ImagingRequest)
            .where(ImagingRequest.id == uuid.UUID(req["id"]))
            .values(sensitivity="sexual_health")
        )
        s.execute(
            update(ImagingStudy)
            .where(ImagingStudy.id == uuid.UUID(linked["id"]))
            .values(sensitivity="sexual_health")
        )
    assert api.get("clinician", path).status_code == 404
    assert (
        api.post("clinician", f"/v1/imaging-studies/{linked['id']}/viewer", {}).status_code == 404
    )
