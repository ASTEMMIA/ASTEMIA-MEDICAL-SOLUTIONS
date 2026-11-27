"""Authentication, health, error handling and every clinical rule violation,
end to end through the API on MySQL 26.10."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import Encounter, Membership, Patient, ServiceRequest
from astemia.adapters.db.session import build_engine
from astemia.adapters.identity.tokens import issue_dev_token
from astemia.api.app import create_app
from astemia.config import Settings
from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import ADMITTED, admit, order, register, release
from tests.e2e.test_service_catalogue import activate, find, provision


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- authentication (API-01) ---------------------------------------------------


def test_requests_without_valid_identity_are_rejected(api: Api, settings: Settings) -> None:
    t = api.tenant
    path = f"/v1/patients/{uuid.uuid7()}/chart"
    good = issue_dev_token(settings, t.subject("clinician"), t.tenant_id)
    forged = jwt.encode(
        jwt.decode(good, options={"verify_signature": False}), "x" * 40, algorithm="HS256"
    )
    expired = issue_dev_token(settings, t.subject("clinician"), t.tenant_id, ttl_s=-60)
    stranger = issue_dev_token(settings, "nobody@nowhere.test", t.tenant_id)
    for headers in (
        {},
        {"Authorization": "Basic abc"},
        bearer("not-a-jwt"),
        bearer(forged),
        bearer(expired),
        bearer(stranger),
    ):
        r = api.client.get(path, headers=headers)
        assert r.status_code == 401, headers
        assert r.json()["error"]["code"] == "unauthenticated"


def test_lapsed_or_inactive_membership_is_rejected(
    api: Api, factory: sessionmaker[Session]
) -> None:
    t = api.tenant
    with factory() as s, s.begin():
        s.execute(
            update(Membership)
            .where(Membership.tenant_id == t.tenant_id, Membership.subject == t.subject("nurse"))
            .values(valid_to=datetime.now(UTC) - timedelta(minutes=1))
        )
        s.execute(
            update(Membership)
            .where(
                Membership.tenant_id == t.tenant_id, Membership.subject == t.subject("clinician2")
            )
            .values(active=False)
        )
    for who in ("nurse", "clinician2"):
        assert api.get(who, f"/v1/patients/{uuid.uuid7()}/chart").status_code == 401


# --- health, error handling, correlation ---------------------------------------


def test_health_and_readiness(client: TestClient, settings: Settings) -> None:
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ready"}
    down = build_engine("mysql+mysqlconnector://x:y@127.0.0.1:1/none", pool_size=1)
    app = create_app(settings, sessionmaker(down))
    r = TestClient(app).get("/health/ready")
    assert r.status_code == 503 and r.json() == {"status": "unavailable"}


def test_unexpected_errors_are_generic_500s_with_correlation(settings: Settings, factory) -> None:  # type: ignore[no-untyped-def]
    app = create_app(settings, factory)

    def boom() -> None:
        raise RuntimeError("internal detail that must not leak")

    app.add_api_route("/boom", boom)
    r = TestClient(app, raise_server_exceptions=False).get(
        "/boom", headers={"X-Correlation-ID": "trace-12345678"}
    )
    assert r.status_code == 500
    assert r.json() == {
        "error": {
            "code": "internal_error",
            "message": "internal error",
            "correlation_id": "trace-12345678",
        }
    }
    assert r.headers["X-Correlation-ID"] == "trace-12345678"
    bad = TestClient(app).get("/health/live", headers={"X-Correlation-ID": "bad id; drop"})
    assert (
        bad.headers["X-Correlation-ID"] != "bad id; drop"
        and len(bad.headers["X-Correlation-ID"]) == 32
    )


def test_invalid_input_names_the_fields(api: Api) -> None:
    r = api.post("registrar", "/v1/patients", {"family_name": "", "birth_date": "not-a-date"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_input"
    assert "birth_date" in r.json()["error"]["message"]


# --- registration and admission rules ------------------------------------------


def test_registration_rules(api: Api) -> None:
    base = {"family_name": "Eze", "given_names": "Uche", "administrative_sex": "male"}
    future = api.post("registrar", "/v1/patients", {**base, "birth_date": "2099-01-01"})
    assert future.json()["error"]["code"] == "bad_birth_date"
    twice = {"issuer": "NG-NIN", "value": "66666666666"}
    dup = api.post(
        "registrar",
        "/v1/patients",
        {**base, "birth_date": "1980-01-01", "identifiers": [twice, twice]},
    )
    assert dup.json()["error"]["code"] == "duplicate_identifier"
    bad = api.post(
        "registrar",
        "/v1/patients",
        {**base, "birth_date": "1980-01-01", "identifiers": [{"issuer": "NG-NIN", "value": "123"}]},
    )
    assert bad.json()["error"]["code"] == "bad_identifier"


def test_admission_rules(api: Api, factory: sessionmaker[Session]) -> None:
    pid = register(api)
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    body = {
        "patient_id": pid,
        "facility_id": str(api.tenant.facility_id),
        "responsible_practitioner_id": str(api.tenant.practitioners["clinician"]),
        "visit_authority": "PILOT",
        "service": "med",
    }
    r = api.post(
        "registrar", "/v1/encounters", {**body, "visit_number": "F1", "admitted_at": tomorrow}
    )
    assert r.json()["error"]["code"] == "future_admission"
    missing = api.post(
        "registrar",
        "/v1/encounters",
        {**body, "visit_number": "F2", "admitted_at": ADMITTED, "patient_id": str(uuid.uuid7())},
    )
    assert missing.status_code == 404
    with factory() as s, s.begin():
        s.execute(update(Patient).where(Patient.id == uuid.UUID(pid)).values(status="deceased"))
    dead = api.post(
        "registrar", "/v1/encounters", {**body, "visit_number": "F3", "admitted_at": ADMITTED}
    )
    assert dead.status_code == 409 and dead.json()["error"]["code"] == "patient_not_admissible"


def test_ae_detail_is_returned_with_the_encounter(api: Api) -> None:
    pid = register(api)
    ae = {
        "attendance_number": "AE-777",
        "arrival_mode": "1",
        "attendance_category": "1",
        "patient_group": "10",
    }
    enc = admit(api, pid, visit="AE-9", encounter_class="emergency", ae=ae)
    assert enc["ae"]["attendance_number"] == "AE-777"
    chart = api.get("clinician", f"/v1/patients/{pid}/chart").json()
    assert chart["encounters"][0]["ae"]["patient_group"] == "10"


# --- orders, results and acknowledgement rules ---------------------------------


def test_order_rules(api: Api, factory: sessionmaker[Session]) -> None:
    pid, other = register(api), register(api, nin="77777777777")
    enc = admit(api, pid)
    order_body = {
        "patient_id": other,
        "encounter_id": enc["id"],
        "code_system": "http://loinc.org",
        "code": "2823-3",
        "display": "Potassium",
    }
    admit(api, other, visit="V-OTHER")
    mismatch = api.post("clinician", "/v1/orders", order_body)
    assert mismatch.json()["error"]["code"] == "encounter_patient_mismatch"
    assert (
        api.post("unlinked_clinician", "/v1/orders", {**order_body, "patient_id": pid}).status_code
        == 404
    )
    with factory() as s, s.begin():
        s.execute(
            update(Encounter).where(Encounter.id == uuid.UUID(enc["id"])).values(state="finished")
        )
    closed = api.post("clinician", "/v1/orders", {**order_body, "patient_id": pid})
    assert closed.status_code == 409 and closed.json()["error"]["code"] == "encounter_closed"


def test_result_release_rules(api: Api, factory: sessionmaker[Session]) -> None:
    pid = register(api)
    o = order(api, pid, admit(api, pid)["id"])
    obs = {
        "code_system": "http://loinc.org",
        "code": "2823-3",
        "display": "K",
        "value_type": "quantity",
        "quantity": "4.0",
        "unit": "mmol/L",
    }
    body = {
        "service_request_id": o["id"],
        "effective_at": datetime.now(UTC).isoformat(),
        "observations": [obs],
    }
    assert (
        api.post(
            "scientist", "/v1/diagnostic-reports", {**body, "observations": [obs, obs]}
        ).json()["error"]["code"]
        == "duplicate_observation"
    )
    no_unit = {**obs, "unit": None}
    assert (
        api.post("scientist", "/v1/diagnostic-reports", {**body, "observations": [no_unit]}).json()[
            "error"
        ]["code"]
        == "invariant_violation"
    )
    unlinked = api.post("unlinked_scientist", "/v1/diagnostic-reports", body)
    assert unlinked.status_code == 403 and unlinked.json()["error"]["code"] == "no_practitioner"
    with_filler = api.post(
        "scientist",
        "/v1/diagnostic-reports",
        {**body, "filler_authority": "LAB1", "filler_id": "ACC-1"},
    )
    assert with_filler.status_code == 201
    with factory() as s, s.begin():
        s.execute(
            update(ServiceRequest)
            .where(ServiceRequest.id == uuid.UUID(o["id"]))
            .values(status="revoked")
        )
    revoked = api.post("scientist", "/v1/diagnostic-reports", body)
    assert revoked.status_code == 409 and revoked.json()["error"]["code"] == "order_not_resultable"


def test_acknowledgement_rules(api: Api) -> None:
    t = api.tenant
    pid = register(api)
    enc = admit(api, pid)
    r = api.post(
        "clinician",
        "/v1/orders",
        {
            "patient_id": pid,
            "encounter_id": enc["id"],
            "code_system": "http://loinc.org",
            "code": "2823-3",
            "display": "Potassium",
            "backup_owner_id": str(t.practitioners["clinician2"]),
        },
    )
    rep = release(api, r.json()["id"])
    path = f"/v1/result-reviews/{rep['review_id']}/acknowledge"
    v1 = {"If-Match": '"1"'}
    assert api.post("nurse", path, {}, **v1).status_code == 403  # no acknowledge capability
    assert api.post("unlinked_clinician", path, {}, **v1).status_code == 404
    assert api.post("psychiatrist", path, {}, **v1).status_code == 404  # not the owner
    assert api.post("clinician2", path, {}, **v1).status_code == 200  # named backup owner
    again = api.post("clinician", path, {}, **{"If-Match": '"2"'})
    assert again.status_code == 422 and again.json()["error"]["code"] == "invalid_transition"
    unknown = api.post("clinician", f"/v1/result-reviews/{uuid.uuid7()}/acknowledge", {}, **v1)
    assert unknown.status_code == 404


# --- sensitive records -------------------------------------------------------------


def test_sensitive_records_are_withheld_without_a_grant(api: Api) -> None:
    t = api.tenant
    pid = register(api)
    admit(api, pid, visit="GEN-1")
    api.post(
        "registrar",
        "/v1/encounters",
        {
            "patient_id": pid,
            "facility_id": str(t.facility_id),
            "responsible_practitioner_id": str(t.practitioners["psychiatrist"]),
            "visit_authority": "PILOT",
            "visit_number": "MH-1",
            "service": "psychiatry",
            "admitted_at": ADMITTED,
            "sensitivity": "mental_health",
        },
    )
    general = api.get("clinician", f"/v1/patients/{pid}/chart").json()
    assert [e["visit_number"] for e in general["encounters"]] == ["GEN-1"]
    assert general["withheld_records"] == 1
    granted = api.get("psychiatrist", f"/v1/patients/{pid}/chart").json()
    assert sorted(e["visit_number"] for e in granted["encounters"]) == ["GEN-1", "MH-1"]
    assert granted["withheld_records"] == 0


# --- catalogue rules ---------------------------------------------------------------


def test_catalogue_rules(api: Api) -> None:
    t = api.tenant
    bad = api.post(
        "admin",
        "/v1/control/catalogue/provision",
        {"facility_id": str(t.facility_id), "group_codes": ["D99"]},
    )
    assert bad.json()["error"]["code"] == "unknown_group"
    denied = api.client.get("/v1/services", headers=api.headers("no_catalogue", None))
    assert denied.status_code == 403
    provision(api, ["D40"])
    malaria = activate(api, find(api, "Malaria")[0])
    by_site = api.client.get(
        "/v1/services",
        params={"facility_id": str(t.facility_id)},
        headers=api.headers("clinician", None),
    ).json()
    assert [s["code"] for s in by_site] == [malaria["code"]]
    other_site = api.client.get(
        "/v1/services",
        params={"facility_id": str(t.second_facility_id)},
        headers=api.headers("clinician", None),
    ).json()
    assert other_site == []
    assert (
        api.client.get(
            "/v1/services",
            params={"care_setting": "virtual"},
            headers=api.headers("clinician", None),
        ).json()
        == []
    )
    pid = register(api)
    r = api.post(
        "registrar",
        "/v1/encounters",
        {
            "patient_id": pid,
            "facility_id": str(t.second_facility_id),
            "responsible_practitioner_id": str(t.practitioners["clinician"]),
            "visit_authority": "PILOT",
            "visit_number": "SITE2",
            "service": malaria["code"],
            "admitted_at": ADMITTED,
        },
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "service_not_offered_here"
    retired = api.post(
        "admin",
        f"/v1/control/services/{malaria['id']}/retire",
        {"reason": "test retire"},
        **{"If-Match": f'"{malaria["version"]}"'},
    ).json()
    again = api.post(
        "admin",
        f"/v1/control/services/{malaria['id']}/activate",
        {
            "facility_id": str(t.facility_id),
            "owner_id": str(t.practitioners["clinician"]),
            "approval_reference": "CAB-2",
        },
        **{"If-Match": f'"{retired["version"]}"'},
    )
    assert again.status_code == 422 and again.json()["error"]["code"] == "invalid_transition"
