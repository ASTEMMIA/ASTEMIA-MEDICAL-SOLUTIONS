"""FHIR R4 (4.0.1) representations of the chart (CEDA section 6.2).

Pure mapping from the scoped chart read to FHIR resources: whatever the chart
masks or withholds for the reader stays masked or withheld here. A masked
identifier keeps only its last four digits and says so with the standard
data-absent-reason extension.
"""

import base64
from typing import Any

from astemia.application.schemas import (
    ChartOut,
    EncounterOut,
    ObservationOut,
    OrderOut,
    PatientOut,
    ReportOut,
)

FHIR_VERSION = "4.0.1"
MEDIA_TYPE = "application/fhir+json"
DATA_ABSENT = "http://hl7.org/fhir/StructureDefinition/data-absent-reason"
ACT_CODE = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
INTERPRETATION = "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation"
UCUM = "http://unitsofmeasure.org"

# Name types (domain NameType) as FHIR name uses.
NAME_USE = {
    "usual": "usual",
    "preferred": "nickname",
    "maiden": "maiden",
    "alias": "old",  # a merged record's name, kept so the patient is still found
    "previous": "old",
}
GENDER = {"male": "male", "female": "female", "other": "other"}
ENCOUNTER_STATUS = {
    "planned": "planned",
    "arrived": "arrived",
    "in_progress": "in-progress",
    "on_leave": "onleave",
    "finished": "finished",
    "cancelled": "cancelled",
    "entered_in_error": "entered-in-error",
}
ENCOUNTER_CLASS = {
    "inpatient": ("IMP", "inpatient encounter"),
    "emergency": ("EMER", "emergency"),
    "ambulatory": ("AMB", "ambulatory"),
    "day_case": ("SS", "short stay"),
    "virtual": ("VR", "virtual"),
}
ORDER_STATUS = {
    "active": "active",
    "on_hold": "on-hold",
    "completed": "completed",
    "revoked": "revoked",
    "entered_in_error": "entered-in-error",
}
SEARCHABLE = ("Encounter", "ServiceRequest", "DiagnosticReport", "Observation")


def _ref(kind: str, id_: Any) -> dict[str, str]:
    return {"reference": f"{kind}/{id_}"}


def patient(p: PatientOut, masked: list[str]) -> dict[str, Any]:
    identifiers = []
    for i in p.identifiers:
        ident: dict[str, Any] = {"system": f"urn:astemia:identifier:{i.issuer}", "value": i.value}
        if "identifier.value" in masked:
            ident["extension"] = [{"url": DATA_ABSENT, "valueCode": "masked"}]
        identifiers.append(ident)
    out: dict[str, Any] = {
        "resourceType": "Patient",
        "id": str(p.id),
        "meta": {"versionId": str(p.version)},
        "active": p.status == "active",
        "identifier": identifiers,
        "name": [
            {
                "use": NAME_USE[n.name_type],
                "family": n.family_name,
                "given": [g for g in (n.given_name, n.other_given_name) if g],
                **({"prefix": [n.title]} if n.title else {}),
            }
            for n in p.names
        ],
        "gender": GENDER.get(p.administrative_sex, "unknown"),
        "birthDate": p.birth_date.isoformat(),
    }
    if p.address is not None:
        a = p.address
        out["address"] = [
            {
                "use": "home",
                "line": [x for x in (a.line1, a.line2) if x],
                "city": a.town,
                "district": a.local_government_area,
                "state": a.state,
                "postalCode": a.postcode,
                "country": a.country,
            }
        ]
    elif "address" in masked:
        out["_address"] = {"extension": [{"url": DATA_ABSENT, "valueCode": "masked"}]}
    return out


def encounter(e: EncounterOut) -> dict[str, Any]:
    code, display = ENCOUNTER_CLASS[e.encounter_class]
    period = {"start": e.period_start.isoformat()}
    if e.period_end is not None:
        period["end"] = e.period_end.isoformat()
    return {
        "resourceType": "Encounter",
        "id": str(e.id),
        "meta": {"versionId": str(e.version)},
        "identifier": [
            {"system": f"urn:astemia:visit:{e.visit_authority}", "value": e.visit_number}
        ],
        "status": ENCOUNTER_STATUS[e.state],
        "class": {"system": ACT_CODE, "code": code, "display": display},
        "serviceType": {"text": e.service},
        "subject": _ref("Patient", e.patient_id),
        "participant": [{"individual": _ref("Practitioner", e.responsible_practitioner_id)}],
        "period": period,
        "serviceProvider": _ref("Location", e.facility_id),
    }


def service_request(o: OrderOut) -> dict[str, Any]:
    return {
        "resourceType": "ServiceRequest",
        "id": str(o.id),
        "meta": {"versionId": str(o.version)},
        "identifier": [
            {
                "type": {"text": "Placer"},
                "system": f"urn:astemia:placer:{o.placer_authority}",
                "value": o.placer_id,
            }
        ],
        "status": ORDER_STATUS[o.status],
        "intent": "order",
        "priority": o.priority,
        "code": {"coding": [{"system": o.code_system, "code": o.code, "display": o.display}]},
        "subject": _ref("Patient", o.patient_id),
        "encounter": _ref("Encounter", o.encounter_id),
        "requester": _ref("Practitioner", o.requester_id),
    }


def observation(o: ObservationOut, report: ReportOut) -> dict[str, Any]:
    out: dict[str, Any] = {
        "resourceType": "Observation",
        "id": str(o.observation_id),
        "meta": {"versionId": str(o.revision)},
        "status": o.status,
        "code": {"coding": [{"system": o.code_system, "code": o.code, "display": o.display}]},
        "subject": _ref("Patient", report.patient_id),
        "basedOn": [_ref("ServiceRequest", report.service_request_id)],
        "issued": report.released_at.isoformat(),
    }
    if o.value_type == "quantity":
        out["valueQuantity"] = {
            "value": float(o.quantity) if o.quantity is not None else None,
            "unit": o.unit,
            "system": UCUM,
            "code": o.unit,
        }
    elif o.value_type == "coded":
        out["valueCodeableConcept"] = {"coding": [{"code": o.value_code}]}
    else:
        out["valueString"] = o.text
    if o.ref_low is not None or o.ref_high is not None:
        bounds: dict[str, Any] = {}
        if o.ref_low is not None:
            bounds["low"] = {"value": float(o.ref_low), "unit": o.unit}
        if o.ref_high is not None:
            bounds["high"] = {"value": float(o.ref_high), "unit": o.unit}
        out["referenceRange"] = [bounds]
    if o.flag:
        out["interpretation"] = [{"coding": [{"system": INTERPRETATION, "code": o.flag}]}]
    return out


def diagnostic_report(r: ReportOut, orders: dict[Any, OrderOut]) -> dict[str, Any]:
    order = orders.get(r.service_request_id)
    out: dict[str, Any] = {
        "resourceType": "DiagnosticReport",
        "id": str(r.id),
        "meta": {"versionId": str(r.version)},
        "status": r.status,
        "code": (
            {
                "coding": [
                    {"system": order.code_system, "code": order.code, "display": order.display}
                ]
            }
            if order is not None
            else {"text": "Report"}
        ),
        "subject": _ref("Patient", r.patient_id),
        "basedOn": [_ref("ServiceRequest", r.service_request_id)],
        "issued": r.released_at.isoformat(),
        "result": [_ref("Observation", o.observation_id) for o in r.observations],
    }
    if r.conclusion:
        out["conclusion"] = r.conclusion
    if r.presented_form:
        out["presentedForm"] = [
            {
                "contentType": "text/plain",
                "data": base64.b64encode(r.presented_form.encode()).decode(),
            }
        ]
    return out


def search(kind: str, chart: ChartOut) -> list[dict[str, Any]]:
    """The patient's resources of one kind, as the chart shows them."""
    match kind:
        case "Encounter":
            return [encounter(e) for e in chart.encounters]
        case "ServiceRequest":
            return [service_request(o) for o in chart.orders]
        case "DiagnosticReport":
            orders = {o.id: o for o in chart.orders}
            return [diagnostic_report(r, orders) for r in chart.reports]
        case _:  # Observation
            return [observation(o, r) for r in chart.reports for o in r.observations]


def bundle(base: str, resources: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(resources),
        "entry": [
            {
                "fullUrl": f"{base}/{r['resourceType']}/{r['id']}",
                "resource": r,
                "search": {"mode": "match"},
            }
            for r in resources
        ],
    }


def outcome(code: str, diagnostics: str) -> dict[str, Any]:
    """OperationOutcome: FHIR's error body."""
    severity_code = {
        "not_found": "not-found",
        "forbidden": "forbidden",
        "unauthenticated": "login",
        "invalid": "invalid",
    }.get(code, "processing")
    return {
        "resourceType": "OperationOutcome",
        "issue": [{"severity": "error", "code": severity_code, "diagnostics": diagnostics}],
    }


def capability_statement(base: str) -> dict[str, Any]:
    return {
        "resourceType": "CapabilityStatement",
        "status": "active",
        "date": "2026-11-28",
        "kind": "instance",
        "fhirVersion": FHIR_VERSION,
        "format": ["json"],
        "implementation": {"description": "ASTEMIA FHIR R4 read API", "url": base},
        "rest": [
            {
                "mode": "server",
                "security": {
                    "description": "Bearer tokens of staff users. Every read applies the "
                    "user's care relationships, masks and sensitive-record rules, and is "
                    "audited, as in the chart.",
                },
                "resource": [
                    {
                        "type": "Patient",
                        "interaction": [{"code": "read"}],
                    },
                    *(
                        {
                            "type": kind,
                            "interaction": [{"code": "search-type"}],
                            "searchParam": [{"name": "patient", "type": "reference"}],
                        }
                        for kind in SEARCHABLE
                    ),
                ],
            }
        ],
    }
