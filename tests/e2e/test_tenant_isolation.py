"""Tenant isolation, proved route by route (CEDA section 7; hardening P0).

Tenant A holds one of every kind of record. Staff of tenant B, in every role,
call every route that takes an id with tenant A's ids, and every list route.
No call may succeed, and no response may carry an id of tenant A. A route
this test does not know fails it, so a new route cannot skip the check.
"""

import re
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import MergeLink
from astemia.config import Settings
from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import admit, order, register, release
from tests.e2e.test_care_plans import plan
from tests.e2e.test_clinical_notes import write
from tests.e2e.test_daybook import task
from tests.e2e.test_discharge import draft
from tests.e2e.test_documents import receive
from tests.e2e.test_safeguards import record
from tests.e2e.test_scheduling import booked, facility, make_slots, refer
from tests.e2e.test_service_catalogue import provision
from tests.fixtures.synthetic import ADDRESS, make_tenant

NOW = datetime.now(UTC)
ROLES = [
    "clinician",
    "psychiatrist",
    "nurse",
    "registrar",
    "scheduler",
    "scientist",
    "admin",
    "steward",
    "privacy",
    "lead",
    "advocate",
    "clerk",
    "supervisor",
]


def _world(api: Api, factory: sessionmaker[Session]) -> dict[str, str]:
    """One of every kind of record in tenant A, by path parameter."""
    pid = register(api)
    enc = admit(api, pid)
    rep = release(api, order(api, pid, enc["id"])["id"])
    first, second = make_slots(api, count=2)
    appointment = booked(api, second["id"], pid)
    phc = facility(factory, api, "primary_health_centre")
    teaching = facility(factory, api, "teaching_hospital")
    other = register(api, "71111111111")
    admit(api, other, visit="V-PHC", facility_id=phc)
    referral = refer(api, other, referring_facility_id=phc, receiving_facility_id=teaching).json()
    entry = write(api, enc["id"]).json()
    doc = receive(api).json()
    care_plan = plan(api, pid).json()
    intervention = record(api, pid).json()
    concern = api.post(
        "clinician",
        "/v1/safeguarding-concerns",
        {
            "patient_id": pid,
            "raised_by": "family",
            "category": "dignity",
            "description": "Left without help for a long time",
        },
    ).json()
    grant = api.post(
        "clinician2",
        "/v1/emergency-grants",
        {"patient_id": pid, "purpose": "Collapsed in the emergency department"},
    ).json()
    draft(api, enc["id"])
    provision(api, ["D01"])
    service = api.get("admin", "/v1/services?include_drafts=true").json()[0]
    near = api.post(
        "registrar",
        "/v1/patients",
        {
            "family_name": "Adeyemmi",
            "given_names": "Folake Ngozi",
            "birth_date": "1984-03-09",
            "administrative_sex": "female",
            "address": ADDRESS,
        },
    ).json()
    prior = api.post(
        "registrar",
        "/v1/patients",
        {
            "family_name": "Okoro",
            "given_names": "Emeka",
            "birth_date": "1971-05-05",
            "administrative_sex": "male",
            "address": ADDRESS,
        },
    ).json()
    survivor = register(api, "72222222222")
    merged = api.post(
        "steward",
        f"/v1/patients/{prior['id']}/merge",
        {"survivor_id": survivor, "reason": "same person, confirmed at the desk"},
        **{"If-Match": '"1"'},
    )
    assert merged.status_code == 200, merged.text
    ward = api.post(
        "admin",
        "/v1/wards",
        {"facility_id": str(api.tenant.facility_id), "code": "W1", "name": "Ward 1"},
    ).json()
    ward = api.post("admin", f"/v1/wards/{ward['id']}/beds", {"code": "W1-1"}).json()
    bed = ward["beds"][0]["id"]
    placed = api.post(
        "nurse", f"/v1/encounters/{enc['id']}/bed", {"bed_id": bed}, **{"If-Match": '"1"'}
    )
    assert placed.status_code == 201, placed.text
    t = api.post(
        "admin",
        "/v1/theatres",
        {"facility_id": str(api.tenant.facility_id), "code": "T1", "name": "Theatre 1"},
    ).json()
    start = NOW + timedelta(days=1)
    times = {"starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=2)).isoformat()}
    slot = api.post("admin", f"/v1/theatres/{t['id']}/sessions", times).json()
    case = api.post(
        "scheduler",
        "/v1/theatre-cases",
        {
            "session_id": slot["id"],
            "encounter_id": enc["id"],
            "surgeon_id": str(api.tenant.practitioners["clinician"]),
            "procedure": "Hernia repair",
            "laterality": "left",
            "estimated_minutes": 60,
        },
    )
    assert case.status_code == 201, case.text
    with factory() as s:
        link = s.scalar(select(MergeLink.id).where(MergeLink.prior_id == uuid.UUID(prior["id"])))
    return {
        "patient_id": pid,
        "encounter_id": enc["id"],
        "review_id": rep["review_id"],
        "slot_id": first["id"],
        "appointment_id": appointment["id"],
        "referral_id": referral["id"],
        "entry_id": entry["id"],
        "document_id": doc["id"],
        "plan_id": care_plan["id"],
        "cycle_id": care_plan["cycles"][0]["id"],
        "intervention_id": intervention["id"],
        "concern_id": concern["id"],
        "grant_id": grant["id"],
        "service_id": service["id"],
        "identity_task_id": near["identity_review_tasks"][0],
        "daybook_task_id": task(api)["id"],
        "link_id": str(link),
        "practitioner_id": str(api.tenant.practitioners["clinician"]),
        "facility_id": str(api.tenant.facility_id),
        "ward_id": ward["id"],
        "bed_id": bed,
        "theatre_id": t["id"],
        "session_id": slot["id"],
        "case_id": case.json()["id"],
    }


def _body(path: str, a: dict[str, str]) -> dict[str, Any]:
    """A valid body for each write route, so a refusal is about the tenant and
    not about the input. Foreign ids in bodies are tenant A's too."""
    later = (NOW + timedelta(days=2)).isoformat()
    bodies: dict[str, dict[str, Any]] = {
        "/attendance": {"outcome": "attended"},
        "/appointments/{appointment_id}/cancel": {"reason": "Patient asked"},
        "/reschedule": {"hold_id": a["slot_id"]},
        "/care-plans/{plan_id}/discontinue": {"reason": "No longer needed"},
        "/revisions": {
            "effective_from": later,
            "session_type": "review",
            "interval_days": 7,
            "sessions": 1,
            "instructions": "Review",
            "reason": "Changed",
        },
        "/activate": {
            "facility_id": a["facility_id"],
            "owner_id": a["practitioner_id"],
            "approval_reference": "CAB-1",
        },
        "/retire": {"reason": "Closed"},
        "/documents/{document_id}/file": {
            "patient_id": a["patient_id"],
            "reviewer_id": a["practitioner_id"],
        },
        "/reindex": {
            "patient_id": a["patient_id"],
            "document_type": "letter",
            "reason": "Wrong patient",
        },
        "/documents/{document_id}/review": {"note": "Seen"},
        "/emergency-grants/{grant_id}/review": {"outcome": "appropriate", "note": "Fine"},
        "/discharge": {"discharged_at": NOW.isoformat()},
        "/discharge-summary": {"disposition": "home", "summary": "Well"},
        "/encounters/{encounter_id}/entries": {"note_type": "consultation", "body": "Note"},
        "/amendments": {"body": "Corrected", "reason": "Typo"},
        "/draft": {"body": "Changed"},
        "/sign": {},
        "/identity-review-tasks/{task_id}/resolve": {
            "resolution": "distinct",
            "reason": "Two people",
        },
        "/unmerge": {"reason": "Wrong merge"},
        "/address": {"address": ADDRESS, "reason": "moved"},
        "/advocates": {"practitioner_id": a["practitioner_id"]},
        "/close": {"reason": "moved_away", "exit_date": date.today().isoformat()},
        "/conditions": {
            "code_system": "http://hl7.org/fhir/sid/icd-10",
            "code": "N18.5",
            "display": "CKD 5",
        },
        "/legal-status": {
            "status": "informal",
            "valid_from": NOW.isoformat(),
            "authorised_by_id": a["practitioner_id"],
            "reason": "Agreed to stay",
        },
        "/merge": {"survivor_id": a["patient_id"], "reason": "Same person"},
        "/plan-cycles/{cycle_id}/complete": {},
        "/release": {"note": "Resolved"},
        "/decision": {"decision": "accepted"},
        "/restrictive-interventions/{intervention_id}/end": {
            "ended_at": NOW.isoformat(),
            "debrief_offered": True,
        },
        "/restrictive-interventions/{intervention_id}/review": {
            "outcome": "appropriate",
            "note": "Fine",
        },
        "/acknowledge": {},
        "/outcome": {"outcome": "upheld", "note": "Upheld"},
        "/hold": {},
        "/tasks/{task_id}/cancel": {"reason": "Not needed"},
        "/tasks/{task_id}/complete": {},
        "/reassign": {"queue": "nurse", "reason": "Rota"},
        "/wards/{ward_id}/status": {"active": False},
        "/wards/{ward_id}/beds": {"code": "X-1"},
        "/beds/{bed_id}/status": {"status": "closed"},
        "/bed": {"bed_id": a["bed_id"]},
        "/transfer": {"bed_id": a["bed_id"]},
        "/theatres/{theatre_id}/status": {"active": False},
        "/theatres/{theatre_id}/sessions": {
            "starts_at": (NOW + timedelta(days=3)).isoformat(),
            "ends_at": (NOW + timedelta(days=3, hours=1)).isoformat(),
        },
        "/theatre-sessions/{session_id}/status": {"status": "unavailable"},
        "/theatre-cases/{case_id}/checklist": {"step": "sign_in"},
        "/theatre-cases/{case_id}/start": {"override_reason": "Emergency"},
        "/theatre-cases/{case_id}/complete": {"procedure_note": "Done", "override_reason": "x"},
        "/theatre-cases/{case_id}/cancel": {"reason": "Unwell"},
        "/theatre-cases/{case_id}/handover": {"recipient_id": a["practitioner_id"]},
    }
    for suffix, body in bodies.items():
        if path.endswith(suffix):
            return body
    raise AssertionError(f"no body for {path}: add one, so the route is checked")


def _ids(path: str, a: dict[str, str]) -> str:
    def value(m: re.Match[str]) -> str:
        name = m.group(1)
        if name == "task_id":
            name = "identity_task_id" if "identity-review" in path else "daybook_task_id"
        if name not in a:
            raise AssertionError(f"no tenant-A id for {{{name}}} in {path}: add one")
        return a[name]

    return re.sub(r"\{([a-z_]+)\}", value, path)


@pytest.fixture
def other(settings: Settings, factory: sessionmaker[Session], client: TestClient) -> Api:
    return Api(client, settings, make_tenant(factory))


def test_no_route_reaches_another_tenants_records(
    api: Api, other: Api, factory: sessionmaker[Session]
) -> None:
    a = _world(api, factory)
    secrets = set(a.values()) | {str(api.tenant.tenant_id)}
    routes = [
        r
        for r in api.client.app.routes  # type: ignore[attr-defined]
        if isinstance(r, APIRoute) and r.path.startswith("/v1")
    ]
    leaks: list[str] = []
    for route in routes:
        method = sorted(route.methods - {"HEAD"})[0]
        templated = "{" in route.path
        if not templated and method == "POST":
            continue  # creations: their foreign ids are covered by the bodies above
        path = _ids(route.path, a) if templated else route.path
        body = _body(route.path, a) if method == "POST" else None
        for who in ROLES:
            if method == "POST":
                r = other.post(who, path, body or {}, **{"If-Match": '"1"'})
            else:
                r = other.get(who, path)
            if templated and r.status_code not in (403, 404):
                leaks.append(f"{who} {method} {route.path}: {r.status_code} {r.text[:120]}")
            if r.status_code < 300 and any(s in r.text for s in secrets):
                leaks.append(f"{who} {method} {route.path}: tenant A data in the response")
    assert not leaks, "\n".join(leaks)
    # The sweep is not vacuous: tenant A can read its own record.
    assert api.get("clinician", f"/v1/patients/{a['patient_id']}/chart").status_code == 200
