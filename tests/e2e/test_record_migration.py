"""Migration of existing patient records (CEDA MIG-01 to MIG-03).

Legacy rows are staged verbatim; each person loads through the registration
checks or is quarantined with a reason; a re-run creates nothing twice; and
reconciliation accounts for every person and checks each loaded identity
against the live record.
"""

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import Patient, PatientIdentifier
from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import register

SOURCE = "PDI-LAGOS"


def person(key: str, nin: str | None = "33333333331", **x: Any) -> dict[str, Any]:
    return {
        "row_key": key,
        "person_number": key,
        "nin": nin,
        "gender": "F",
        "date_of_birth": "1980-02-01",
        **x,
    }


def name(key: str, **x: Any) -> dict[str, Any]:
    return {
        "row_key": f"N-{key}",
        "person_number": key,
        "title": "Mrs",
        "forename": "Amaka",
        "other_names": "Chioma",
        "surname": "Okafor",
        **x,
    }


def address(key: str, **x: Any) -> dict[str, Any]:
    return {
        "row_key": f"A-{key}",
        "person_number": key,
        "address_line1": "4 Allen Avenue",
        "address_line2": "Opebi",
        "address_line3": "Ikeja",
        "state": "Lagos",
        "local_government_area": "Ikeja",
        "postcode": "100271",
        **x,
    }


def stage(api: Api, persons: list[Any], names: list[Any], addresses: list[Any]) -> dict[str, Any]:
    r = api.post(
        "migrator",
        "/v1/migration/batches",
        {
            "source_system": SOURCE,
            "description": "Lagos PDI extract",
            "persons": persons,
            "names": names,
            "addresses": addresses,
        },
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


def load(api: Api, batch: dict[str, Any]) -> Any:
    return api.post("migrator", f"/v1/migration/batches/{batch['id']}/load", {})


def reconciliation(api: Api, batch: dict[str, Any]) -> dict[str, Any]:
    r = api.get("migrator", f"/v1/migration/batches/{batch['id']}/reconciliation")
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_persons_load_once_and_reconcile(api: Api, factory: sessionmaker[Session]) -> None:
    persons = [
        person("P-1"),
        person("P-2", nin="44444444442", date_of_birth="15/06/1975", gender="1"),
    ]
    names = [
        name("P-1"),
        name("P-1", row_key="N-P-1-old", surname="Eze", valid_to="2010-01-01"),  # a former name
        name("P-2", forename="Tunde", other_names=None, surname="Bakare", title=None),
    ]
    addresses = [
        address("P-1"),
        address("P-1", row_key="A-P-1-old", address_line1="Old house", effective_to="2015-01-01"),
        address("P-2", address_line2="Ikeja", address_line3=None),
    ]
    batch = stage(api, persons, names, addresses)
    assert (batch["staged_persons"], batch["staged_names"], batch["staged_addresses"]) == (2, 3, 3)
    loaded = load(api, batch)
    assert loaded.status_code == 200, loaded.text
    assert (loaded.json()["loaded"], loaded.json()["quarantined"]) == (2, 0)

    with factory() as s:
        rows = s.scalars(
            select(Patient).where(
                Patient.tenant_id == api.tenant.tenant_id, Patient.source_system == SOURCE
            )
        ).all()
        assert {
            (p.source_id, p.administrative_sex, p.initial_registration_source) for p in rows
        } == {
            ("P-1", "female", "migration"),
            ("P-2", "male", "migration"),
        }
        p1 = next(p for p in rows if p.source_id == "P-1")
    # A migrated patient is found like any other, with the current name and address.
    found = api.get("registrar", "/v1/patient-index?nin=33333333331").json()
    assert [f["id"] for f in found] == [str(p1.id)]
    assert found[0]["family_name"] == "Okafor" and found[0]["given_names"] == "Amaka Chioma"

    rec = reconciliation(api, batch)
    assert rec == {
        "batch_id": batch["id"],
        "status": "loaded",
        "source_persons": 2,
        "loaded": 2,
        "quarantined": 0,
        "not_processed": 0,
        "quarantine_reasons": {},
        "patients_from_source": 2,
        "identity_mismatches": [],
        "reconciled": True,
    }

    # MIG-02: running the extract again creates nothing twice.
    again = stage(api, persons, names, addresses)
    assert (again["staged_persons"], again["already_staged"]) == (0, 8)
    assert load(api, again).json()["loaded"] == 0
    assert reconciliation(api, again)["source_persons"] == 0
    assert load(api, batch).json()["error"]["code"] == "batch_loaded"

    # A changed version of a loaded person is quarantined, not applied.
    changed = stage(api, [person("P-1", gender="M")], [], [])
    out = load(api, changed).json()
    assert (out["loaded"], out["quarantined"]) == (0, 1)
    [exc] = api.get("migrator", f"/v1/migration/batches/{changed['id']}/exceptions").json()
    assert (exc["source_row_key"], exc["reason"]) == ("P-1", "changed_since_load")
    with factory() as s:
        assert s.get(Patient, (api.tenant.tenant_id, p1.id)).administrative_sex == "female"  # type: ignore[union-attr]

    # A loaded identity that no longer matches the live record is reported.
    with factory() as s, s.begin():
        s.execute(update(Patient).where(Patient.id == p1.id).values(birth_date="1980-02-02"))
        # And one whose NIN has since been retired.
        p2 = next(p for p in rows if p.source_id == "P-2")
        s.execute(
            update(PatientIdentifier)
            .where(PatientIdentifier.patient_id == p2.id)
            .values(active_marker=None)
        )
    rec = reconciliation(api, batch)
    assert sorted(rec["identity_mismatches"]) == sorted([str(p1.id), str(p2.id)])
    assert rec["reconciled"] is False


def test_unsafe_persons_are_quarantined_with_their_reason(api: Api) -> None:
    register(api, "55555555553")  # already registered at the desk
    cases = {
        "P-nin": (person("P-nin", nin=None), True, True),
        "P-name": (person("P-name", nin="66666666661"), False, True),
        "P-surname": (person("P-surname", nin="66666666662"), "no-surname", True),
        "P-date": (person("P-date", nin="66666666663", date_of_birth="31/02/1980"), True, True),
        "P-dob": (person("P-dob", nin="66666666664", date_of_birth="sometime"), True, True),
        "P-sex": (person("P-sex", nin="66666666665", gender="X"), True, True),
        "P-bad-nin": (person("P-bad-nin", nin="123"), True, True),
        "P-taken": (person("P-taken", nin="55555555553"), True, True),
        "P-homeless": (person("P-homeless", nin="66666666666"), True, False),
    }
    persons, names, addresses = [], [], []
    for key, (p, has_name, has_address) in cases.items():
        persons.append(p)
        if has_name == "no-surname":
            names.append(name(key, surname=None))
        elif has_name:
            names.append(name(key))
        if has_address:
            addresses.append(address(key))
    batch = stage(api, persons, names, addresses)
    out = load(api, batch).json()
    assert (out["loaded"], out["quarantined"]) == (0, len(cases))
    reasons = {
        e["source_row_key"]: e["reason"]
        for e in api.get("migrator", f"/v1/migration/batches/{batch['id']}/exceptions").json()
    }
    assert reasons == {
        "P-nin": "nin_missing",
        "P-name": "name_missing",
        "P-surname": "invalid_record",
        "P-date": "bad_date",
        "P-dob": "bad_date",
        "P-sex": "bad_sex",
        "P-bad-nin": "bad_identifier",
        "P-taken": "identifier_in_use",
        "P-homeless": "address_required",
    }
    rec = reconciliation(api, batch)
    assert (rec["quarantined"], rec["loaded"], rec["reconciled"]) == (len(cases), 0, True)
    assert rec["quarantine_reasons"]["bad_date"] == 2

    # The source is corrected and resent: the new version loads.
    fixed = stage(api, [person("P-sex", nin="66666666665", gender="F")], [], [])
    assert load(api, fixed).json()["loaded"] == 1


def test_an_unloaded_batch_does_not_reconcile_and_access_is_limited(api: Api) -> None:
    batch = stage(api, [person("P-9", nin="77777777771")], [name("P-9")], [address("P-9")])
    rec = reconciliation(api, batch)
    assert (rec["not_processed"], rec["reconciled"], rec["status"]) == (1, False, "staged")
    path = f"/v1/migration/batches/{batch['id']}"
    assert (
        api.get("migrator", f"/v1/migration/batches/{uuid.uuid4()}/reconciliation").status_code
        == 404
    )
    assert api.post("migrator", f"/v1/migration/batches/{uuid.uuid4()}/load", {}).status_code == 404
    assert (
        api.get("migrator", f"/v1/migration/batches/{uuid.uuid4()}/exceptions").status_code == 404
    )
    assert (
        api.post(
            "clinician", "/v1/migration/batches", {"source_system": "X", "description": "x"}
        ).status_code
        == 403
    )
    assert api.get("registrar", f"{path}/exceptions").status_code == 403
    assert api.post("registrar", f"{path}/load", {}).status_code == 403
