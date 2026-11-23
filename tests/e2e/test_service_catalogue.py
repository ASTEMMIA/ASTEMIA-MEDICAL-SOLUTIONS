"""Catalogue lifecycle (CAT-01..05) through the API on MySQL 26.10."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import ClinicalService, Encounter, ServiceChange
from astemia.catalogue import load_catalogue
from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import register

ADMITTED = (datetime.now(UTC) - timedelta(hours=1)).isoformat()


def provision(api: Api, groups: list[str] | None = None, key: str = "auto") -> dict:
    body: dict = {"facility_id": str(api.tenant.facility_id)}
    if groups:
        body["group_codes"] = groups
    r = api.post("admin", "/v1/control/catalogue/provision", body, key=key)
    assert r.status_code == 201, r.text
    return r.json()


def find(api: Api, q: str, who: str = "admin", drafts: bool = True) -> list[dict]:
    r = api.client.get(
        "/v1/services",
        params={"q": q, "include_drafts": drafts},
        headers=api.headers(who, None),
    )
    assert r.status_code == 200, r.text
    return r.json()


def activate(api: Api, service: dict) -> dict:
    r = api.post(
        "admin",
        f"/v1/control/services/{service['id']}/activate",
        {
            "facility_id": str(api.tenant.facility_id),
            "owner_id": str(api.tenant.practitioners["clinician"]),
            "approval_reference": "CAB-2026-114",
        },
        **{"If-Match": f'"{service["version"]}"'},
    )
    assert r.status_code == 200, r.text
    return r.json()


def admit(api: Api, pid: str, service: str, visit: str):  # type: ignore[no-untyped-def]
    return api.post(
        "registrar",
        "/v1/encounters",
        {
            "patient_id": pid,
            "facility_id": str(api.tenant.facility_id),
            "responsible_practitioner_id": str(api.tenant.practitioners["clinician"]),
            "visit_authority": "PILOT",
            "visit_number": visit,
            "service": service,
            "admitted_at": ADMITTED,
        },
    )


def test_full_catalogue_provisions_as_drafts(api: Api) -> None:
    groups = load_catalogue()["groups"]
    n = sum(len(g["services"]) for g in groups)
    out = provision(api)
    assert out == {
        "facility_id": str(api.tenant.facility_id),
        "groups": len(groups),
        "services_created": n,
        "services_existing": 0,
    }
    again = provision(api)  # a new key: nothing is duplicated
    assert again["services_created"] == 0 and again["services_existing"] == n
    # Drafts are invisible to clinicians until activated.
    assert find(api, "Malaria", who="clinician", drafts=False) == []
    assert (
        api.client.get(
            "/v1/services", params={"include_drafts": True}, headers=api.headers("clinician", None)
        ).status_code
        == 403
    )


def test_search_by_alias_and_age(api: Api) -> None:
    provision(api, ["D27", "D40"])
    by_group_alias = find(api, "Tropical and communicable")
    assert {s["code"] for s in by_group_alias} == {f"D40-0{n}" for n in range(1, 9)}
    r = api.client.get(
        "/v1/services",
        params={"include_drafts": True, "age": "adult"},
        headers=api.headers("admin", None),
    )
    assert all(s["age_policy"] in ("adult", "all") for s in r.json())
    assert not any(s["code"].startswith("D27") for s in r.json())  # paediatric-only group


def test_activation_needs_approval_and_links_admissions(
    api: Api, factory: sessionmaker[Session]
) -> None:
    provision(api, ["D40", "D01"])
    malaria = find(api, "Malaria")[0]
    bad = api.post(
        "admin",
        f"/v1/control/services/{malaria['id']}/activate",
        {
            "facility_id": str(api.tenant.facility_id),
            "owner_id": str(api.tenant.practitioners["clinician"]),
            "approval_reference": "x",
        },
        **{"If-Match": f'"{malaria["version"]}"'},
    )
    assert bad.status_code == 422  # approval reference too short
    assert (
        api.post(
            "clinician",
            f"/v1/control/services/{malaria['id']}/activate",
            {
                "facility_id": str(api.tenant.facility_id),
                "owner_id": str(api.tenant.practitioners["clinician"]),
                "approval_reference": "CAB-1",
            },
            **{"If-Match": '"1"'},
        ).status_code
        == 403
    )
    active = activate(api, malaria)
    assert active["status"] == "active" and active["facilities"] == [str(api.tenant.facility_id)]
    assert [s["code"] for s in find(api, "Malaria", who="clinician", drafts=False)] == [
        malaria["code"]
    ]

    pid = register(api)
    ok = admit(api, pid, malaria["code"], "V-MAL-1")
    assert ok.status_code == 201, ok.text
    unknown = admit(api, pid, "general_medicine", "V-MAL-2")  # CAT-04: no silent default
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "unknown_service"
    draft = admit(api, pid, find(api, "Resuscitation")[0]["code"], "V-MAL-3")
    assert draft.status_code == 422 and draft.json()["error"]["code"] == "unknown_service"
    with factory() as s:
        enc = s.scalars(select(Encounter).where(Encounter.tenant_id == api.tenant.tenant_id)).one()
        assert enc.clinical_service_id is not None


def test_retirement_blocks_new_work_and_keeps_history(
    api: Api, factory: sessionmaker[Session]
) -> None:
    provision(api, ["D40"])
    tb = activate(api, find(api, "Tuberculosis DOTS")[0])
    pid = register(api)
    assert admit(api, pid, tb["code"], "V-TB-1").status_code == 201
    retired = api.post(
        "admin",
        f"/v1/control/services/{tb['id']}/retire",
        {"reason": "moved to partner site"},
        **{"If-Match": f'"{tb["version"]}"'},
    )
    assert retired.status_code == 200 and retired.json()["status"] == "retired"
    # Retiring the tenant's only active service must not reopen free-text
    # admissions: the retired code is refused (CAT-03/04).
    blocked = admit(api, pid, tb["code"], "V-TB-2")
    assert blocked.status_code == 422 and blocked.json()["error"]["code"] == "service_retired"
    assert find(api, "Tuberculosis DOTS", who="clinician", drafts=False) == []
    with factory() as s:
        linked = s.scalar(
            select(func.count())
            .select_from(Encounter)
            .where(
                Encounter.tenant_id == api.tenant.tenant_id,
                Encounter.clinical_service_id == tb["id"],
            )
        )
        assert linked == 1  # history stays linked
        kinds = s.scalars(
            select(ServiceChange.change_type).where(
                ServiceChange.tenant_id == api.tenant.tenant_id,
                ServiceChange.service_id == tb["id"],
            )
        ).all()
        assert sorted(kinds) == ["activate", "retire"]
        svc = s.scalars(
            select(ClinicalService).where(
                ClinicalService.tenant_id == api.tenant.tenant_id,
                ClinicalService.code == tb["code"],
            )
        ).one()
        assert svc.status == "retired" and svc.effective_to is not None


def test_tenants_cannot_see_each_others_catalogue(api: Api, client, settings, factory) -> None:  # type: ignore[no-untyped-def]
    from tests.fixtures.synthetic import make_tenant

    provision(api, ["D40"])
    activate(api, find(api, "Malaria")[0])
    other = Api(client, settings, make_tenant(factory))
    assert find(other, "Malaria", who="admin") == []


def test_directory_listing_names_are_search_aliases(api: Api) -> None:
    """CAT-02: people search with the names the public directories use."""
    provision(api, ["D29", "D48", "D07"])
    assert {s["name"] for s in find(api, "The Havens")} == {"Sexual assault referral centre"}
    assert {s["name"] for s in find(api, "WestMARC")} == {
        "Prosthetics",
        "Prosthetic rehabilitation physiotherapy",
    }
    assert "Diabetes disordered eating and psychological support" in {
        s["name"] for s in find(api, "T1DE")
    }
