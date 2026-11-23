"""API-03 first vertical slice: one test admission, one authorised chart read,
an order, result release and one clinician acknowledgement, with field masks
and audit checked before chart data is shown. Plus the API-02 contract."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import (
    AuditEvent,
    LegitimateRelationship,
    ObservationRevision,
    OutboxEvent,
    ResultReview,
)
from tests.conftest import Api

ADMITTED = (datetime.now(UTC) - timedelta(hours=1)).isoformat()


def register(api: Api, nin: str = "12345678901") -> str:
    r = api.post(
        "registrar",
        "/v1/patients",
        {
            "title": "Mrs",
            "family_name": "Adeyemi",
            "given_names": "Folake Ngozi",
            "birth_date": "1984-03-09",
            "administrative_sex": "female",
            "mother_name": "Bisi Adeyemi",
            "identifiers": [{"issuer": "NG-NIN", "value": nin, "verified": True}],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def admit(api: Api, patient_id: str, visit: str = "V-0001", **extra: object) -> dict:
    body = {
        "patient_id": patient_id,
        "facility_id": str(api.tenant.facility_id),
        "responsible_practitioner_id": str(api.tenant.practitioners["clinician"]),
        "visit_authority": "PILOT",
        "visit_number": visit,
        "service": "general_medicine",
        "admitted_at": ADMITTED,
        **extra,
    }
    r = api.post("registrar", "/v1/encounters", body)
    assert r.status_code == 201, r.text
    return r.json()


def order(api: Api, patient_id: str, encounter_id: str) -> dict:
    r = api.post(
        "clinician",
        "/v1/orders",
        {
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "code_system": "http://loinc.org",
            "code": "2823-3",
            "display": "Potassium [Moles/volume] in Serum",
            "priority": "urgent",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def release(api: Api, order_id: str, value: str = "6.1") -> dict:
    r = api.post(
        "scientist",
        "/v1/diagnostic-reports",
        {
            "service_request_id": order_id,
            "effective_at": datetime.now(UTC).isoformat(),
            "observations": [
                {
                    "code_system": "http://loinc.org",
                    "code": "2823-3",
                    "display": "Potassium",
                    "value_type": "quantity",
                    "quantity": value,
                    "unit": "mmol/L",
                    "ref_low": "3.5",
                    "ref_high": "5.3",
                }
            ],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_vertical_slice(api: Api, factory: sessionmaker[Session]) -> None:
    tid = api.tenant.tenant_id
    pid = register(api)
    enc = admit(api, pid)
    assert enc["state"] == "in_progress"

    chart = api.get("clinician", f"/v1/patients/{pid}/chart")
    assert chart.status_code == 200, chart.text
    body = chart.json()
    assert body["patient"]["family_name"] == "Adeyemi"
    assert body["patient"]["identifiers"][0]["value"] == "12345678901"
    with factory() as s:  # the read was audited before data was returned
        assert (
            s.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.tenant_id == tid,
                    AuditEvent.action == "chart.read",
                    AuditEvent.outcome == "success",
                )
            )
            == 1
        )

    o = order(api, pid, enc["id"])
    assert o["status"] == "active" and o["placer_id"].startswith("ORD-")
    rep = release(api, o["id"])
    assert rep["status"] == "final"
    assert rep["observations"][0]["flag"] == "H"

    chart = api.get("clinician", f"/v1/patients/{pid}/chart").json()
    assert chart["orders"][0]["status"] == "completed"
    review = chart["open_reviews"][0]
    assert review["assignee_id"] == str(api.tenant.practitioners["clinician"])

    ack = api.post(
        "clinician",
        f"/v1/result-reviews/{review['id']}/acknowledge",
        {"note": "repeat in 4h"},
        **{"If-Match": f'"{review["version"]}"'},
    )
    assert ack.status_code == 200, ack.text
    assert ack.json()["state"] == "acknowledged"

    with factory() as s:
        types = s.scalars(select(OutboxEvent.event_type).where(OutboxEvent.tenant_id == tid)).all()
    assert sorted(types) == sorted(
        [
            "patient.registered",
            "encounter.admitted",
            "order.placed",
            "result.released",
            "result.acknowledged",
        ]
    )


def test_idempotent_replay_and_changed_content(api: Api) -> None:
    pid = register(api)
    body = {
        "patient_id": pid,
        "facility_id": str(api.tenant.facility_id),
        "responsible_practitioner_id": str(api.tenant.practitioners["clinician"]),
        "visit_authority": "PILOT",
        "visit_number": "V-77",
        "service": "med",
        "admitted_at": ADMITTED,
    }
    first = api.post("registrar", "/v1/encounters", body, key="k-admit-1")
    again = api.post("registrar", "/v1/encounters", body, key="k-admit-1")
    assert first.status_code == again.status_code == 201
    assert again.json() == first.json()
    assert again.headers["Idempotent-Replay"] == "true"
    changed = api.post(
        "registrar", "/v1/encounters", {**body, "service": "surgery"}, key="k-admit-1"
    )
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "idempotency_key_reused"
    missing = api.post("registrar", "/v1/encounters", body, key=None)
    assert missing.status_code == 428


def test_duplicate_identifier_and_visit_number_conflict(api: Api) -> None:
    pid = register(api, nin="22222222222")
    r = api.post(
        "registrar",
        "/v1/patients",
        {
            "family_name": "Okafor",
            "given_names": "Chidi",
            "birth_date": "1970-01-01",
            "administrative_sex": "male",
            "identifiers": [{"issuer": "NG-NIN", "value": "22222222222"}],
        },
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "identifier_already_bound"
    admit(api, pid, visit="V-DUP")
    r = api.post(
        "registrar",
        "/v1/encounters",
        {
            "patient_id": pid,
            "facility_id": str(api.tenant.facility_id),
            "responsible_practitioner_id": str(api.tenant.practitioners["clinician"]),
            "visit_authority": "PILOT",
            "visit_number": "V-DUP",
            "service": "med",
            "admitted_at": ADMITTED,
        },
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "visit_number_exists"


def test_stale_or_missing_version_on_acknowledge(api: Api) -> None:
    pid = register(api)
    enc = admit(api, pid)
    rep = release(api, order(api, pid, enc["id"])["id"])
    path = f"/v1/result-reviews/{rep['review_id']}/acknowledge"
    assert api.post("clinician", path, {}).status_code == 428
    stale = api.post("clinician", path, {}, **{"If-Match": '"7"'})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_version"


def test_access_is_concealed_and_denials_are_audited(
    api: Api, factory: sessionmaker[Session]
) -> None:
    pid = register(api)
    admit(api, pid)
    # No legitimate relationship: a clinician gets the same 404 as for a missing patient.
    no_rel = api.get("clinician2", f"/v1/patients/{pid}/chart")
    missing = api.get("clinician2", f"/v1/patients/{uuid.uuid7()}/chart")
    assert no_rel.status_code == missing.status_code == 404
    assert no_rel.json()["error"]["code"] == missing.json()["error"]["code"] == "not_found"
    # Registrars and tenant administrators hold no clinical capability.
    assert api.get("registrar", f"/v1/patients/{pid}/chart").status_code == 404
    assert api.get("admin", f"/v1/patients/{pid}/chart").status_code == 404
    with factory() as s:
        denied = s.scalars(
            select(AuditEvent.reason_code).where(
                AuditEvent.tenant_id == api.tenant.tenant_id, AuditEvent.outcome == "denied"
            )
        ).all()
    assert "no_care_relationship" in denied and "missing_capability" in denied


def test_other_tenant_cannot_see_the_patient(api: Api, client, settings, factory) -> None:  # type: ignore[no-untyped-def]
    from tests.fixtures.synthetic import make_tenant

    pid = register(api)
    admit(api, pid)
    other = Api(client, settings, make_tenant(factory))
    assert other.get("clinician", f"/v1/patients/{pid}/chart").status_code == 404


def test_nurse_reads_through_workgroup_with_identifiers_masked(
    api: Api, factory: sessionmaker[Session]
) -> None:
    pid = register(api, nin="33333333333")
    enc = admit(api, pid)
    assert api.get("nurse", f"/v1/patients/{pid}/chart").status_code == 404
    with factory() as s, s.begin():
        s.add(
            LegitimateRelationship(
                tenant_id=api.tenant.tenant_id,
                id=uuid.uuid7(),
                recorded_at=datetime.now(UTC),
                patient_id=uuid.UUID(pid),
                workgroup_id=api.tenant.workgroup_id,
                encounter_id=uuid.UUID(enc["id"]),
                start_at=datetime.now(UTC) - timedelta(minutes=1),
                creation_reason_code="ward_team",
            )
        )
    chart = api.get("nurse", f"/v1/patients/{pid}/chart")
    assert chart.status_code == 200, chart.text
    assert chart.json()["patient"]["identifiers"][0]["value"] == "*******3333"
    assert "identifier.value" in chart.json()["masked_fields"]


def test_amended_result_reopens_exactly_one_review(
    api: Api, factory: sessionmaker[Session]
) -> None:
    pid = register(api)
    enc = admit(api, pid)
    o = order(api, pid, enc["id"])
    first = release(api, o["id"], "6.1")
    second = release(api, o["id"], "5.0")
    assert second["status"] == "amended" and second["prior_report_id"] == first["id"]
    assert second["observations"][0]["revision"] == 2 and second["observations"][0]["flag"] == "N"
    with factory() as s:
        states = s.scalars(
            select(ResultReview.state).where(ResultReview.tenant_id == api.tenant.tenant_id)
        ).all()
        revisions = s.scalar(
            select(func.count())
            .select_from(ObservationRevision)
            .where(ObservationRevision.tenant_id == api.tenant.tenant_id)
        )
    assert sorted(states) == ["open", "superseded"]
    assert revisions == 2


def test_ae_attendance_requires_emergency_class(api: Api) -> None:
    pid = register(api)
    ae = {"attendance_number": "AE-1", "arrival_mode": "1", "attendance_category": "1"}
    r = api.post(
        "registrar",
        "/v1/encounters",
        {
            "patient_id": pid,
            "facility_id": str(api.tenant.facility_id),
            "responsible_practitioner_id": str(api.tenant.practitioners["clinician"]),
            "visit_authority": "PILOT",
            "visit_number": "AE-V1",
            "service": "emergency",
            "admitted_at": ADMITTED,
            "ae": ae,
        },
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "ae_needs_emergency"
    admit(api, pid, visit="AE-V2", encounter_class="emergency", ae=ae)


def test_medicare_number_is_retired_in_favour_of_nin(api: Api) -> None:
    base = {
        "family_name": "Bello",
        "given_names": "Musa",
        "birth_date": "1961-07-02",
        "administrative_sex": "male",
    }
    current = api.post(
        "registrar",
        "/v1/patients",
        {**base, "identifiers": [{"issuer": "NG-MEDICARE", "value": "MED-1001"}]},
    )
    assert current.status_code == 422
    assert current.json()["error"]["code"] == "medicare_number_retired"

    # Migrated history: the old number is kept as a previous identifier next to the NIN.
    # It never holds the active binding, so it cannot block another record.
    for nin in ("44444444444", "55555555555"):
        r = api.post(
            "registrar",
            "/v1/patients",
            {
                **base,
                "identifiers": [
                    {"issuer": "NG-NIN", "value": nin, "verified": True},
                    {"issuer": "NG-MEDICARE", "value": "MED-1001", "identifier_type": "previous"},
                ],
            },
        )
        assert r.status_code == 201, r.text
        kinds = {(i["issuer"], i["identifier_type"]) for i in r.json()["identifiers"]}
        assert kinds == {("NG-NIN", "current")}  # only active bindings are listed


def test_parents_names_are_stored_but_not_disclosed_in_the_chart(
    api: Api, factory: sessionmaker[Session]
) -> None:
    from astemia.adapters.db.models import Patient

    pid = register(api)  # registers mother_name="Bisi Adeyemi"
    admit(api, pid)
    with factory() as s:
        assert s.get(Patient, (api.tenant.tenant_id, uuid.UUID(pid))).mother_name == "Bisi Adeyemi"  # type: ignore[union-attr]
    chart = api.get("clinician", f"/v1/patients/{pid}/chart")
    assert "Bisi" not in chart.text
