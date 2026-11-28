"""Registration needs a full address and postcode (CEDA revision 1.8), filed as
the patient's home address and shown only to roles that need it."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import Address, DemographicTransaction, PartyAddress
from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import admit, order, register
from tests.fixtures.synthetic import ADDRESS

PERSON = {
    "family_name": "Bello",
    "given_names": "Amina",
    "birth_date": "1990-02-11",
    "administrative_sex": "female",
}


def code(r: Any) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def test_registration_needs_a_full_address_and_postcode(
    api: Api, factory: sessionmaker[Session]
) -> None:
    assert code(api.post("registrar", "/v1/patients", PERSON)) == (422, "address_required")
    no_postcode = {k: v for k, v in ADDRESS.items() if k != "postcode"}
    assert code(api.post("registrar", "/v1/patients", {**PERSON, "address": no_postcode})) == (
        422,
        "invalid_input",
    )
    bad = {**ADDRESS, "postcode": "10124"}
    assert code(api.post("registrar", "/v1/patients", {**PERSON, "address": bad})) == (
        422,
        "bad_postcode",
    )
    no_lga = {**ADDRESS, "local_government_area": None}
    assert code(api.post("registrar", "/v1/patients", {**PERSON, "address": no_lga})) == (
        422,
        "address_incomplete",
    )

    uk = {
        "line1": "10 Downing Street",
        "town": "London",
        "postcode": "sw1a2aa",
        "country": "GB",
    }
    made = api.post("registrar", "/v1/patients", {**PERSON, "address": uk})
    assert made.status_code == 201, made.text
    assert made.json()["address"] == {
        "line1": "10 Downing Street",
        "line2": None,
        "town": "London",
        "local_government_area": None,
        "state": None,
        "postcode": "SW1A 2AA",
        "country": "GB",
    }
    with factory() as s:
        link = s.execute(
            select(PartyAddress).where(PartyAddress.party_id == made.json()["id"])
        ).scalar_one()
        assert link.address_type == "home" and link.effective_to is None
        assert s.get(Address, (api.tenant.tenant_id, link.address_id)) is not None
        delta = s.scalar(
            select(DemographicTransaction.delta).where(
                DemographicTransaction.patient_id == made.json()["id"]
            )
        )
    assert delta is not None and "address" in delta["created"]

    # An unidentified patient, such as an unconscious arrival, may wait for it.
    unknown = api.post(
        "registrar",
        "/v1/patients",
        {**PERSON, "family_name": "Unknown", "temporary": True},
    )
    assert unknown.status_code == 201 and unknown.json()["address"] is None


def test_the_address_is_shown_only_to_roles_that_need_it(api: Api) -> None:
    pid = register(api)
    enc = admit(api, pid)
    chart = api.get("clinician", f"/v1/patients/{pid}/chart").json()
    assert chart["patient"]["address"]["postcode"] == ADDRESS["postcode"]
    assert "address" not in chart["masked_fields"]
    found = api.get("registrar", "/v1/patient-index?family_name=Adeyemi").json()
    assert found[0]["address"]["town"] == "Lagos"

    order(api, pid, enc["id"])
    [work] = api.get("scientist", "/v1/orders/worklist").json()
    assert work["patient"]["address"] is None  # the laboratory does not need it

    api.post(
        "clinician2",
        "/v1/emergency-grants",
        {"patient_id": pid, "purpose": "Collapsed in the emergency department"},
    )
    emergency = api.get("clinician2", f"/v1/patients/{pid}/chart").json()
    assert emergency["access_basis"] == "emergency_grant"
    assert emergency["patient"]["address"] is None
    assert "address" in emergency["masked_fields"]
