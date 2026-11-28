"""FHIR R4 read API (CEDA section 6.2).

The same scoped chart read as the staff API, shaped as FHIR: only a user who
may read the chart gets the resources, masks and withheld records carry over,
and errors are OperationOutcomes.
"""

import base64
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import DiagnosticReport, ServiceRequest
from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import admit, order, register, release

FHIR = "/fhir/r4"


def read(api: Api, who: str, path: str) -> Any:
    return api.get(who, f"{FHIR}/{path}")


def resources(api: Api, who: str, kind: str, pid: str) -> list[dict[str, Any]]:
    r = read(api, who, f"{kind}?patient=Patient/{pid}")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/fhir+json")
    bundle = r.json()
    assert (bundle["resourceType"], bundle["type"]) == ("Bundle", "searchset")
    assert bundle["total"] == len(bundle["entry"])
    for e in bundle["entry"]:
        assert e["fullUrl"].endswith(f"{FHIR}/{kind}/{e['resource']['id']}")
    return [e["resource"] for e in bundle["entry"]]


def test_the_capability_statement_says_what_is_served(api: Api) -> None:
    r = api.client.get(f"{FHIR}/metadata")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    cs = r.json()
    assert (cs["resourceType"], cs["fhirVersion"]) == ("CapabilityStatement", "4.0.1")
    kinds = [x["type"] for x in cs["rest"][0]["resource"]]
    assert kinds == ["Patient", "Encounter", "ServiceRequest", "DiagnosticReport", "Observation"]


def test_a_patient_and_their_records_read_as_fhir(api: Api) -> None:
    pid = register(api)
    enc = admit(api, pid)
    o = order(api, pid, enc["id"])
    api.post(
        "scientist",
        "/v1/diagnostic-reports",
        {
            "service_request_id": o["id"],
            "effective_at": datetime.now(UTC).isoformat(),
            "conclusion": "Hyperkalaemia",
            "observations": [
                {
                    "code_system": "http://loinc.org",
                    "code": "2823-3",
                    "display": "Potassium",
                    "value_type": "quantity",
                    "quantity": "6.1",
                    "unit": "mmol/L",
                    "ref_low": "3.5",
                    "ref_high": "5.3",
                },
                {
                    "code_system": "http://loinc.org",
                    "code": "2160-0",
                    "display": "Creatinine",
                    "value_type": "quantity",
                    "quantity": "90",
                    "unit": "umol/L",
                    "ref_high": "110",
                },
                {
                    "code_system": "http://loinc.org",
                    "code": "600-7",
                    "display": "Culture",
                    "value_type": "coded",
                    "value_code": "264868006",
                },
                {
                    "code_system": "http://loinc.org",
                    "code": "8251-1",
                    "display": "Comment",
                    "value_type": "string",
                    "text": "Slightly haemolysed",
                },
            ],
        },
    )

    p = read(api, "clinician", f"Patient/{pid}").json()
    assert (p["resourceType"], p["id"], p["gender"], p["birthDate"]) == (
        "Patient",
        pid,
        "female",
        "1984-03-09",
    )
    assert p["identifier"] == [{"system": "urn:astemia:identifier:NG-NIN", "value": "12345678901"}]
    assert p["name"][0]["family"] == "Adeyemi" and p["name"][0]["use"] == "usual"
    assert p["address"][0]["use"] == "home" and p["active"] is True

    [e] = resources(api, "clinician", "Encounter", pid)
    assert (e["status"], e["class"]["code"]) == ("in-progress", "IMP")
    assert e["identifier"][0]["value"] == "V-0001" and "end" not in e["period"]
    [sr] = resources(api, "clinician", "ServiceRequest", pid)
    assert (sr["status"], sr["intent"], sr["priority"]) == ("completed", "order", "urgent")
    assert sr["code"]["coding"][0]["code"] == "2823-3"
    [dr] = resources(api, "clinician", "DiagnosticReport", pid)
    assert (dr["status"], dr["conclusion"]) == ("final", "Hyperkalaemia")
    assert dr["code"]["coding"][0]["code"] == "2823-3"
    assert len(dr["result"]) == 4 and "presentedForm" not in dr
    by_code = {
        o["code"]["coding"][0]["code"]: o for o in resources(api, "clinician", "Observation", pid)
    }
    k, creat = by_code["2823-3"], by_code["2160-0"]
    culture, comment = by_code["600-7"], by_code["8251-1"]
    assert k["valueQuantity"] == {
        "value": 6.1,
        "unit": "mmol/L",
        "system": "http://unitsofmeasure.org",
        "code": "mmol/L",
    }
    assert k["referenceRange"][0]["low"]["value"] == 3.5
    assert k["interpretation"][0]["coding"][0]["code"] == "H"
    assert (
        "low" not in creat["referenceRange"][0]
        and creat["interpretation"][0]["coding"][0]["code"] == "N"
    )
    assert culture["valueCodeableConcept"]["coding"][0]["code"] == "264868006"
    assert "referenceRange" not in culture and "interpretation" not in culture
    assert comment["valueString"] == "Slightly haemolysed"


def test_a_narrative_report_carries_its_text_and_a_discharge_ends_the_period(
    api: Api, factory: sessionmaker[Session]
) -> None:
    pid = register(api)
    enc = admit(api, pid)
    release(api, order(api, pid, enc["id"])["id"])
    with factory() as s, s.begin():
        s.execute(
            update(DiagnosticReport)
            .where(DiagnosticReport.patient_id == uuid.UUID(pid))
            .values(presented_form="Full signed text")
        )
    [dr] = resources(api, "clinician", "DiagnosticReport", pid)
    assert base64.b64decode(dr["presentedForm"][0]["data"]).decode() == "Full signed text"
    api.post(
        "clinician",
        f"/v1/encounters/{enc['id']}/discharge-summary",
        {"disposition": "home", "summary": "Well"},
    )
    api.post(
        "clinician",
        f"/v1/encounters/{enc['id']}/discharge",
        {"discharged_at": datetime.now(UTC).isoformat()},
        **{"If-Match": '"1"'},
    )
    [e] = resources(api, "clinician", "Encounter", pid)
    assert e["status"] == "finished" and "end" in e["period"]
    # A report whose order is withheld from this reader keeps a plain code.
    with factory() as s, s.begin():
        s.execute(
            update(ServiceRequest)
            .where(ServiceRequest.patient_id == uuid.UUID(pid))
            .values(sensitivity="sexual_health")
        )
    [dr] = resources(api, "clinician", "DiagnosticReport", pid)
    assert dr["code"] == {"text": "Report"}


def test_masks_and_access_carry_over_and_errors_are_operation_outcomes(api: Api) -> None:
    pid = register(api)
    admit(api, pid)
    # Emergency access: identifiers and address masked, and said to be.
    grant = api.post(
        "clinician2",
        "/v1/emergency-grants",
        {"patient_id": pid, "purpose": "Collapsed in the emergency department"},
    )
    assert grant.status_code == 201, grant.text
    p = read(api, "clinician2", f"Patient/{pid}").json()
    [ident] = p["identifier"]
    assert ident["value"] == "*******8901"
    assert ident["extension"][0]["valueCode"] == "masked"
    assert "address" not in p and p["_address"]["extension"][0]["valueCode"] == "masked"

    def outcome(r: Any, status: int, issue: str) -> None:
        assert r.status_code == status, r.text
        assert r.headers["content-type"].startswith("application/fhir+json")
        body = r.json()
        assert body["resourceType"] == "OperationOutcome"
        assert body["issue"][0]["code"] == issue

    outcome(read(api, "nurse", f"Patient/{pid}"), 404, "not-found")  # not in their care
    outcome(read(api, "registrar", f"Patient/{pid}"), 404, "not-found")  # no chart access
    outcome(read(api, "clinician", f"Patient/{uuid.uuid4()}"), 404, "not-found")
    outcome(read(api, "clinician", "Patient/not-a-uuid"), 422, "invalid")
    outcome(read(api, "clinician", "Encounter"), 422, "invalid")
    outcome(read(api, "clinician", "Encounter?patient=Patient/x"), 422, "invalid")
    outcome(api.client.get(f"{FHIR}/Patient/{pid}"), 401, "login")
    outcome(read(api, "scheduler", f"Observation?patient={pid}"), 404, "not-found")
