"""Staff and site directory, and the laboratory worklist: names instead of IDs
on every screen, and the orders still waiting for a result."""

import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import AuditEvent, Practitioner, ServiceRequest
from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import admit, order, register, release


def test_the_directory_names_staff_and_sites(api: Api, factory: sessionmaker[Session]) -> None:
    staff = api.get("registrar", "/v1/practitioners")
    assert staff.status_code == 200, staff.text
    by_id = {p["id"]: p for p in staff.json()}
    clinician = by_id[str(api.tenant.practitioners["clinician"])]
    assert set(clinician) == {
        "id",
        "display_name",
        "professional_register",
        "specialist_area",
    }  # no contact details or dates of birth
    names = [p["display_name"] for p in staff.json()]
    assert names == sorted(names)

    with factory() as s, s.begin():
        s.execute(
            update(Practitioner)
            .where(Practitioner.id == api.tenant.practitioners["clinician2"])
            .values(authorisation_status="suspended")
        )
    listed = {p["id"] for p in api.get("registrar", "/v1/practitioners").json()}
    assert str(api.tenant.practitioners["clinician2"]) not in listed  # cannot be chosen

    sites = api.get("clinician", "/v1/facilities").json()
    assert {s["id"] for s in sites} >= {
        str(api.tenant.facility_id),
        str(api.tenant.second_facility_id),
    }
    assert all(s["organisation_name"] for s in sites)
    assert api.client.get("/v1/practitioners").status_code == 401


def test_the_laboratory_worklist(api: Api, factory: sessionmaker[Session]) -> None:
    pid = register(api)
    enc = admit(api, pid)
    urgent = order(api, pid, enc["id"])
    routine = api.post(
        "clinician",
        "/v1/orders",
        {
            "patient_id": pid,
            "encounter_id": enc["id"],
            "code_system": "http://loinc.org",
            "code": "718-7",
            "display": "Haemoglobin",
            "priority": "routine",
        },
    ).json()
    done = order(api, pid, enc["id"])
    release(api, done["id"])

    r = api.get("scientist", "/v1/orders/worklist")
    assert r.status_code == 200, r.text
    work = r.json()
    assert [w["order"]["id"] for w in work] == [urgent["id"], routine["id"]]  # urgent first
    first = work[0]
    assert first["patient"]["family_name"] and first["ordered_at"]
    nin = next(i for i in first["patient"]["identifiers"] if i["issuer"] == "NG-NIN")
    assert nin["value"] != "12345678901"  # masked for the laboratory

    assert (
        api.get("scientist", "/v1/orders/worklist?limit=1").json()[0]["order"]["id"]
        == (urgent["id"])
    )
    with factory() as s, s.begin():
        s.execute(
            update(ServiceRequest)
            .where(ServiceRequest.id == uuid.UUID(routine["id"]))
            .values(status="revoked")
        )
    assert [w["order"]["id"] for w in api.get("scientist", "/v1/orders/worklist").json()] == [
        urgent["id"]
    ]

    denied = api.get("registrar", "/v1/orders/worklist")
    assert denied.status_code == 403
    with factory() as s:
        outcomes = s.scalars(
            select(AuditEvent.outcome).where(
                AuditEvent.tenant_id == api.tenant.tenant_id,
                AuditEvent.action == "order.worklist",
            )
        ).all()
    assert sorted(set(outcomes)) == ["denied", "success"]
