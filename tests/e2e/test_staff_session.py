"""The staff web app's session (NFR-03): who is signed in, development sign-in
that is off by default and never in production, and the built app served with
strict headers."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from astemia.api.app import create_app
from astemia.config import Settings
from tests.conftest import Api


def test_me_names_the_person_their_tenant_and_what_they_may_do(api: Api) -> None:
    r = api.get("clinician", "/v1/me")
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["subject"] == api.tenant.subject("clinician")
    assert me["roles"] == ["clinician"] and me["display_name"] == "Clinician"
    assert "chart:read" in me["capabilities"] and "catalogue:manage" not in me["capabilities"]
    assert me["practitioner_id"] == str(api.tenant.practitioners["clinician"])
    assert me["tenant_name"]
    unlinked = api.get("unlinked_clinician", "/v1/me").json()
    assert unlinked["practitioner_id"] is None
    assert unlinked["display_name"] == api.tenant.subject("unlinked_clinician")
    assert api.client.get("/v1/me").status_code == 401
    for response in (r, api.client.get("/v1/me")):  # with data, and refused
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert response.headers["Strict-Transport-Security"].startswith("max-age=")


def test_development_sign_in_is_off_by_default(api: Api) -> None:
    tid = api.tenant.tenant_id
    assert api.client.get(f"/v1/dev/accounts?tenant_id={tid}").status_code == 404
    body = {"tenant_id": str(tid), "subject": api.tenant.subject("clinician")}
    assert api.client.post("/v1/dev/sign-in", json=body).status_code == 404


@pytest.fixture
def dev_client(settings: Settings, factory: sessionmaker[Session], tmp_path: Path) -> TestClient:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>ASTEMIA</title>")
    (tmp_path / "assets" / "app.js").write_text("console.log('app')")
    s = settings.model_copy(update={"dev_sign_in": True, "web_dir": str(tmp_path)})
    return TestClient(create_app(s, factory), raise_server_exceptions=False)


def test_development_sign_in_when_enabled(api: Api, dev_client: TestClient) -> None:
    tid = api.tenant.tenant_id
    accounts = dev_client.get(f"/v1/dev/accounts?tenant_id={tid}").json()
    by_subject = {a["subject"]: a for a in accounts}
    clinician = by_subject[api.tenant.subject("clinician")]
    assert (clinician["display_name"], clinician["roles"]) == ("Clinician", ["clinician"])
    assert by_subject[api.tenant.subject("unlinked_clinician")]["display_name"] == (
        api.tenant.subject("unlinked_clinician")
    )
    signed = dev_client.post(
        "/v1/dev/sign-in", json={"tenant_id": str(tid), "subject": clinician["subject"]}
    )
    assert signed.status_code == 200, signed.text
    token = signed.json()
    assert token["token_type"] == "Bearer" and token["expires_in"] == 8 * 3600
    me = dev_client.get("/v1/me", headers={"Authorization": f"Bearer {token['access_token']}"})
    assert me.json()["subject"] == clinician["subject"]
    nobody = dev_client.post(
        "/v1/dev/sign-in", json={"tenant_id": str(tid), "subject": "nobody@nowhere.test"}
    )
    assert nobody.status_code == 401


def test_never_in_production(settings: Settings, factory: sessionmaker[Session], api: Api) -> None:
    # model_copy skips validation, so this is the route's own guard, behind the
    # startup check in Settings.
    prod = settings.model_copy(update={"dev_sign_in": True, "environment": "staging"})
    client = TestClient(create_app(prod, factory), raise_server_exceptions=False)
    tid = api.tenant.tenant_id
    assert client.get(f"/v1/dev/accounts?tenant_id={tid}").status_code == 404


def test_the_built_app_is_served_with_strict_headers(dev_client: TestClient) -> None:
    page = dev_client.get("/app/")
    assert page.status_code == 200 and "<title>ASTEMIA</title>" in page.text
    csp = page.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert page.headers["X-Frame-Options"] == "DENY"
    assert page.headers["Referrer-Policy"] == "no-referrer"
    asset = dev_client.get("/app/assets/app.js")
    assert asset.status_code == 200 and "console.log" in asset.text
    route = dev_client.get("/app/patients/123")  # a client-side route
    assert route.status_code == 200 and "<title>ASTEMIA</title>" in route.text
    escape = dev_client.get("/app/..%2F..%2Fpyproject.toml")
    assert "<title>ASTEMIA</title>" in escape.text  # never a file outside the app
    assert dev_client.get("/app").status_code == 200
    head = dev_client.head("/app/")  # health checks and proxies ask for headers only
    assert head.status_code == 200 and head.headers["X-Frame-Options"] == "DENY"
