"""Emergency access (CEDA SEC-04, WF02 step 4): one patient, read-only, 30
minutes, a recorded purpose, a privacy alert and a review within one working
day. Without a grant, a chart outside the clinician's care stays concealed."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import AuditEvent, EmergencyGrant, OutboxEvent
from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import admit, register

PURPOSE = "Collapsed on ward 4; covering for the on-call team"


def ask(api: Api, who: str, patient_id: str, purpose: str = PURPOSE) -> Any:
    return api.post(who, "/v1/emergency-grants", {"patient_id": patient_id, "purpose": purpose})


def chart(api: Api, who: str, patient_id: str) -> Any:
    return api.get(who, f"/v1/patients/{patient_id}/chart")


def expire(factory: sessionmaker[Session], grant_id: str) -> None:
    with factory() as s, s.begin():
        s.execute(
            update(EmergencyGrant)
            .where(EmergencyGrant.id == uuid.UUID(grant_id))
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )


def test_emergency_access_opens_one_chart_read_only_for_thirty_minutes(
    api: Api, factory: sessionmaker[Session]
) -> None:
    pid = register(api)
    enc = admit(api, pid)  # under Dr Clinician One
    assert chart(api, "clinician2", pid).status_code == 404  # concealed, as before

    def code(r: Any) -> tuple[int, str]:
        return r.status_code, r.json()["error"]["code"]

    assert code(ask(api, "clinician2", pid, "urgent")) == (422, "invalid_input")  # say why
    assert code(ask(api, "registrar", pid)) == (403, "missing_capability")
    assert code(ask(api, "clinician", pid)) == (409, "access_not_needed")
    assert code(ask(api, "clinician2", str(uuid.uuid4()))) == (404, "not_found")
    assert code(ask(api, "unlinked_clinician", pid)) == (403, "no_practitioner")

    r = ask(api, "clinician2", pid)
    assert r.status_code == 201, r.text
    grant = r.json()
    assert grant["practitioner_id"] == str(api.tenant.practitioners["clinician2"])
    assert (grant["scope"], grant["live"], grant["step_up"]) == (
        "chart:read",
        True,
        "not_available",
    )
    starts = datetime.fromisoformat(grant["starts_at"])
    assert datetime.fromisoformat(grant["expires_at"]) - starts == timedelta(minutes=30)
    assert datetime.fromisoformat(grant["review_due_at"]) > starts

    seen = chart(api, "clinician2", pid)
    assert seen.status_code == 200, seen.text
    body = seen.json()
    assert body["access_basis"] == "emergency_grant"
    assert body["patient"]["identifiers"][0]["value"] == "*******8901"  # minimum necessary
    assert "identifier.value" in body["masked_fields"]
    assert [e["id"] for e in body["encounters"]] == [enc["id"]]
    assert chart(api, "clinician", pid).json()["access_basis"] == "care_relationship"
    # Read-only: the grant does not let the clinician place an order.
    no_order = api.post(
        "clinician2",
        "/v1/orders",
        {
            "patient_id": pid,
            "encounter_id": enc["id"],
            "code_system": "http://loinc.org",
            "code": "2823-3",
            "display": "Potassium",
        },
    )
    assert no_order.status_code == 404
    # One patient at a time.
    other = register(api, "98765432109")
    assert code(ask(api, "clinician2", other)) == (409, "grant_active")

    with factory() as s:
        reads = s.execute(
            select(AuditEvent.outcome, AuditEvent.reason_code).where(
                AuditEvent.tenant_id == api.tenant.tenant_id,
                AuditEvent.action == "chart.read",
                AuditEvent.actor_subject == api.tenant.subject("clinician2"),
            )
        ).all()
        alert = s.execute(
            select(OutboxEvent.payload).where(
                OutboxEvent.tenant_id == api.tenant.tenant_id,
                OutboxEvent.event_type == "emergency_access.granted",
            )
        ).scalar_one()
    assert ("success", "emergency_grant") in reads  # emergency reads are marked as such
    assert alert["grant_id"] == grant["id"] and alert["patient_id"] == pid
    assert "purpose" not in alert  # clinical detail stays out of the event

    # The first read after expiry is refused, and another grant may be asked for.
    expire(factory, grant["id"])
    assert chart(api, "clinician2", pid).status_code == 404
    assert ask(api, "clinician2", other).status_code == 201


def test_privacy_officer_reviews_every_grant(api: Api, factory: sessionmaker[Session]) -> None:
    pid = register(api)
    admit(api, pid)
    grant = ask(api, "clinician2", pid).json()
    own = ask(api, "dual", pid).json()

    def code(r: Any) -> tuple[int, str]:
        return r.status_code, r.json()["error"]["code"]

    queue = api.get("privacy", "/v1/emergency-grants")
    assert queue.status_code == 200, queue.text
    assert {g["id"] for g in queue.json()} == {grant["id"], own["id"]}
    assert not any(g["review_overdue"] for g in queue.json())
    assert api.get("clinician", "/v1/emergency-grants").status_code == 403

    path = f"/v1/emergency-grants/{grant['id']}/review"
    verdict = {"outcome": "appropriate", "note": "Confirmed with the ward sister"}
    if_match = {"If-Match": '"1"'}
    assert code(api.post("privacy", path, verdict)) == (428, "precondition_required")
    assert code(api.post("clinician", path, verdict, **if_match)) == (403, "missing_capability")
    assert code(api.post("unlinked_privacy", path, verdict, **if_match)) == (
        403,
        "no_practitioner",
    )
    own_path = f"/v1/emergency-grants/{own['id']}/review"
    assert code(api.post("dual", own_path, verdict, **if_match)) == (403, "own_grant")

    done = api.post("privacy", path, verdict, **if_match)
    assert done.status_code == 200, done.text
    out = done.json()
    assert (out["review_outcome"], out["review_note"], out["version"]) == (
        "appropriate",
        verdict["note"],
        2,
    )
    assert out["reviewed_by_id"] == str(api.tenant.practitioners["privacy"])
    assert done.headers["ETag"] == '"2"'
    assert code(api.post("privacy", path, verdict, **{"If-Match": '"2"'})) == (
        422,
        "already_reviewed",
    )
    assert [g["id"] for g in api.get("privacy", "/v1/emergency-grants?reviewed=true").json()] == [
        grant["id"]
    ]

    # An unreviewed grant past its deadline is flagged as overdue.
    with factory() as s, s.begin():
        s.execute(
            update(EmergencyGrant)
            .where(EmergencyGrant.id == uuid.UUID(own["id"]))
            .values(review_due_at=datetime.now(UTC) - timedelta(minutes=1))
        )
    [late] = api.get("privacy", "/v1/emergency-grants").json()
    assert late["id"] == own["id"] and late["review_overdue"]
