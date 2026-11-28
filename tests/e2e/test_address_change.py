"""Changing a patient's address after registration (CEDA revision 1.8; ICRS
3.2.11): a reason, the record's version, and the old address kept as history."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import DemographicTransaction, OutboxEvent
from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import register
from tests.fixtures.synthetic import ADDRESS

ABUJA = {
    "line1": "Plot 5 Ahmadu Bello Way",
    "line2": "Garki",
    "town": "Abuja",
    "local_government_area": "Abuja Municipal",
    "state": "Federal Capital Territory",
    "postcode": "900211",
    "country": "NG",
}


def if_match(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


def code(r: Any) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def change(api: Api, pid: str, version: int, who: str = "registrar", **body: Any) -> Any:
    return api.post(
        who,
        f"/v1/patients/{pid}/address",
        {"address": ABUJA, "reason": "moved", **body},
        **if_match(version),
    )


def test_a_move_keeps_the_old_address_as_history(api: Api, factory: sessionmaker[Session]) -> None:
    pid = register(api)
    path = f"/v1/patients/{pid}/address"
    assert code(api.post("registrar", path, {"address": ABUJA, "reason": "moved"})) == (
        428,
        "precondition_required",
    )
    assert code(change(api, pid, 7)) == (409, "stale_version")
    moved = change(api, pid, 1)
    assert moved.status_code == 200, moved.text
    assert moved.json()["version"] == 2
    assert moved.json()["address"]["town"] == "Abuja"

    history = api.get("registrar", f"/v1/patients/{pid}/addresses").json()
    assert [(h["town"], h["current"]) for h in history] == [("Abuja", True), ("Lagos", False)]
    assert history[1]["effective_to"] == history[0]["effective_from"]
    assert history[0]["recorded_by_id"] == str(api.tenant.practitioners["registrar"])

    assert code(change(api, pid, 2)) == (422, "address_unchanged")
    assert code(change(api, pid, 2, reason="identified")) == (422, "not_temporary")
    bad = {**ABUJA, "postcode": "9002"}
    assert code(change(api, pid, 2, address=bad)) == (422, "bad_postcode")
    incomplete = {**ABUJA, "state": None}
    assert code(change(api, pid, 2, address=incomplete)) == (422, "address_incomplete")
    fixed = change(
        api, pid, 2, reason="correction", address={**ABUJA, "line1": "Plot 7 Ahmadu Bello Way"}
    )
    assert fixed.status_code == 200, fixed.text

    with factory() as s:
        reasons = s.scalars(
            select(DemographicTransaction.change_reason)
            .where(DemographicTransaction.patient_id == uuid.UUID(pid))
            .order_by(DemographicTransaction.transaction_at)
        ).all()
        events = s.scalars(
            select(OutboxEvent.payload).where(
                OutboxEvent.tenant_id == api.tenant.tenant_id,
                OutboxEvent.event_type == "patient.address_changed",
            )
        ).all()
    assert reasons == ["registration", "address:moved", "address:correction"]
    assert len(events) == 2 and all("town" not in str(e) and "900211" not in str(e) for e in events)

    # The patient shows only the current address.
    current = api.get("registrar", f"/v1/patients/{pid}").json()
    assert current["address"]["line1"] == "Plot 7 Ahmadu Bello Way"


def test_an_unidentified_patient_gets_an_address_once_known(api: Api) -> None:
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
    assert api.get("registrar", f"/v1/patients/{arrival['id']}/addresses").json() == []
    known = change(api, arrival["id"], 1, reason="identified", address=ADDRESS)
    assert known.status_code == 200, known.text
    assert known.json()["address"]["postcode"] == "101241"


def test_who_may_change_and_read_addresses(api: Api) -> None:
    pid = register(api)
    assert change(api, pid, 1, who="clinician").status_code == 404  # may read, not change
    steward = change(api, pid, 1, who="steward")
    assert steward.status_code == 200, steward.text
    assert api.get("scientist", f"/v1/patients/{pid}/addresses").status_code == 403
    assert api.get("registrar", f"/v1/patients/{uuid.uuid4()}/addresses").status_code == 404

    read = api.get("registrar", f"/v1/patients/{pid}")
    assert read.status_code == 200 and read.json()["address"]["town"] == "Abuja"
    nin = next(i for i in read.json()["identifiers"] if i["issuer"] == "NG-NIN")
    assert nin["value"] != "12345678901"  # the registrar sees a masked NIN
    assert api.get("scientist", f"/v1/patients/{pid}").status_code == 403
    assert api.get("registrar", f"/v1/patients/{uuid.uuid4()}").status_code == 404


def test_a_merged_record_is_changed_through_its_survivor(api: Api) -> None:
    survivor = register(api, "72222222222")
    prior = api.post(
        "registrar",
        "/v1/patients",
        {
            "family_name": "Adeyemi",
            "given_names": "Folake",
            "birth_date": "1984-03-09",
            "administrative_sex": "female",
            "address": ADDRESS,
        },
    ).json()["id"]
    merged = api.post(
        "steward",
        f"/v1/patients/{prior}/merge",
        {"survivor_id": survivor, "reason": "same person, confirmed at the desk"},
        **if_match(1),
    )
    assert merged.status_code == 200, merged.text
    version = api.get("registrar", f"/v1/patients/{prior}").json()["version"]
    assert code(change(api, prior, version)) == (422, "patient_merged")
