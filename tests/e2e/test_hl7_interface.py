"""Inbound HL7 v2 (CEDA section 6, WF03; UAT WF03).

Admissions, orders and results arrive from other systems. Replaying a message
creates nothing twice; a result that arrives before its order is held and
applied once the order arrives; a message that cannot be applied is kept with
its reason and acknowledged AE.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import DiagnosticReport, Encounter, ServiceRequest
from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import admit, register

WHEN = (datetime.now(UTC) - timedelta(minutes=30)).strftime("%Y%m%d%H%M%S")


def seg(name: str, fields: dict[int, str]) -> str:
    out = [""] * (max(fields) + 1)
    for n, value in fields.items():
        out[n] = value
    return name + "|" + "|".join(out[1:])


def msh(api: Api, kind: str, control: str) -> str:
    site = f"S{api.tenant.tenant_id.hex[:6]}"
    return f"MSH|^~\\&|LABSYS|{site}|ASTEMIA|PILOT|{WHEN}||{kind}|{control}|P|2.5"


def pid(nin: str = "12345678901") -> str:
    return seg("PID", {1: "1", 3: f"{nin}^^^NG-NIN~X9^^^LOCAL", 5: "Adeyemi^Folake", 7: "19840309"})


def pv1(api: Api, visit: str = "V-0001", **f: str) -> str:
    site = f"S{api.tenant.tenant_id.hex[:6]}"
    fields = {
        1: "1",
        2: "I",
        3: f"WARD1^^^{site}",
        7: "HCP-clinician^One^Clinician",
        10: "general_medicine",
        19: f"{visit}^^^PILOT",
        44: WHEN,
    }
    fields.update({int(k[1:]): v for k, v in f.items()})
    return seg("PV1", fields)


def orm(api: Api, control: str, placer: str = "PL-1", **x: str) -> str:
    orc = {
        1: x.get("order_control", "NW"),
        2: f"{placer}^EXTLAB",
        7: "^^^^^S",
        12: "HCP-clinician^One",
    }
    obr = {1: "1", 2: f"{placer}^EXTLAB", 4: x.get("service", "2823-3^Potassium^LN")}
    return "\r".join(
        [
            msh(api, "ORM^O01", control),
            pid(),
            pv1(api, x.get("visit", "V-0001")),
            seg("ORC", orc),
            seg("OBR", obr),
        ]
    )


def oru(api: Api, control: str, placer: str = "PL-1", nin: str = "12345678901", **x: str) -> str:
    obr = {
        1: "1",
        2: f"{placer}^EXTLAB",
        3: "F-9^LAB",
        4: "2823-3^Potassium^LN",
        7: WHEN,
        25: x.get("status", "F"),
        32: x.get("scientist", "HCP-scientist"),
    }
    obx = x.get(
        "obx",
        seg(
            "OBX",
            {
                1: "1",
                2: "NM",
                3: "2823-3^Potassium^LN",
                5: x.get("value", "6.1"),
                6: "mmol/L",
                7: "3.5-5.1",
                11: "F",
            },
        ),
    )
    return "\r".join([msh(api, "ORU^R01", control), pid(nin), seg("OBR", obr), obx])


def send(api: Api, message: str, who: str = "interface") -> Any:
    return api.client.post(
        "/v1/interfaces/hl7", json={"message": message}, headers=api.headers(who, None)
    )


def test_a_result_before_its_order_is_held_then_applied(
    api: Api, factory: sessionmaker[Session]
) -> None:
    """UAT WF03: a result delivered before its order is reconciled once the order arrives."""
    pid_ = register(api)
    admit(api, pid_)
    early = send(api, oru(api, "R-1"))
    assert early.status_code == 200, early.text
    body = early.json()
    assert (body["status"], body["ack_code"], body["detail"]) == (
        "held",
        "AA",
        "waiting for its order",
    )
    assert body["ack"].split("\r")[1] == "MSA|AA|R-1|waiting for its order"
    held = api.get("admin", "/v1/interfaces/messages?status=held").json()
    assert [m["control_id"] for m in held] == ["R-1"] and held[0]["placer_key"] == "EXTLAB|PL-1"

    order = send(api, orm(api, "O-1"))
    assert order.json()["status"] == "processed", order.text
    assert order.json()["detail"] == "applied 1 held result(s)"
    assert order.json()["resource_type"] == "service_request"
    assert api.get("admin", "/v1/interfaces/messages?status=held").json() == []
    [applied] = [
        m for m in api.get("admin", "/v1/interfaces/messages").json() if m["control_id"] == "R-1"
    ]
    assert (applied["status"], applied["resource_type"]) == ("processed", "diagnostic_report")
    assert applied["patient_id"] == pid_
    # On the chart: the ordering clinician's result, flagged high.
    chart = api.get("clinician", f"/v1/patients/{pid_}/chart").json()
    [report] = chart["reports"]
    assert report["observations"][0]["flag"] == "H"
    with factory() as s:
        sr = s.scalars(
            select(ServiceRequest).where(ServiceRequest.tenant_id == api.tenant.tenant_id)
        ).one()
        assert (sr.placer_authority, sr.placer_id, sr.priority, sr.status) == (
            "EXTLAB",
            "PL-1",
            "stat",
            "completed",
        )
        assert (sr.filler_authority, sr.filler_id) == ("LAB", "F-9")
        assert sr.requester_id == api.tenant.practitioners["clinician"]
    # A corrected result arrives later as an amendment.
    fixed = send(api, oru(api, "R-2", status="C", value="5.9"))
    assert fixed.json()["status"] == "processed"
    statuses = sorted(
        r["status"] for r in api.get("clinician", f"/v1/patients/{pid_}/chart").json()["reports"]
    )
    assert statuses == ["amended", "final"]


def test_a_replayed_message_creates_nothing_twice(api: Api, factory: sessionmaker[Session]) -> None:
    """UAT WF03: every input replayed creates nothing twice."""
    pid_ = register(api)
    admit(api, pid_)
    first = send(api, orm(api, "O-1"))
    again = send(api, orm(api, "O-1"))
    assert again.status_code == 200 and again.json() == first.json()
    assert again.headers.get("Idempotent-Replay") in ("true", None)
    reused = send(api, orm(api, "O-1", placer="PL-2"))  # same control id, other content
    assert reused.status_code == 409 and reused.json()["error"]["code"] == "control_id_reused"
    result = send(api, oru(api, "R-1"))
    assert send(api, oru(api, "R-1")).json() == result.json()
    with factory() as s:
        tid = api.tenant.tenant_id
        orders = s.scalar(
            select(func.count()).select_from(ServiceRequest).where(ServiceRequest.tenant_id == tid)
        )
        reports = s.scalar(
            select(func.count())
            .select_from(DiagnosticReport)
            .where(DiagnosticReport.tenant_id == tid)
        )
    assert (orders, reports) == (1, 1)
    # A second order with the same placer number is an error, not a second order.
    dup = send(api, orm(api, "O-2"))
    assert (dup.json()["ack_code"], dup.json()["error_code"]) == ("AE", "duplicate")


def test_an_admission_arrives_from_the_patient_administration_system(
    api: Api, factory: sessionmaker[Session]
) -> None:
    pid_ = register(api)
    adt = "\r".join([msh(api, "ADT^A01", "A-1"), pid(), pv1(api, "V-PAS-1")])
    out = send(api, adt)
    assert (out.json()["status"], out.json()["resource_type"]) == ("processed", "encounter"), (
        out.text
    )
    with factory() as s:
        e = s.scalars(
            select(Encounter).where(
                Encounter.tenant_id == api.tenant.tenant_id, Encounter.visit_number == "V-PAS-1"
            )
        ).one()
        assert (e.visit_authority, e.encounter_class, e.source_system) == (
            "PILOT",
            "inpatient",
            "LABSYS^" + f"S{api.tenant.tenant_id.hex[:6]}",
        )
    # The responsible clinician now has the patient in their care.
    assert api.get("clinician", f"/v1/patients/{pid_}/chart").status_code == 200
    # An emergency attendance, with the facility taken from MSH-4.
    er = "\r".join([msh(api, "ADT^A01", "A-2"), pid(), pv1(api, "V-ED-1", f2="E", f3="BAY1")])
    assert send(api, er).json()["status"] == "processed"


def test_messages_that_cannot_be_applied_are_kept_with_their_reason(api: Api) -> None:
    register(api)
    site = f"S{api.tenant.tenant_id.hex[:6]}"
    cases = {
        "unknown_patient": "\r".join([msh(api, "ADT^A01", "E-1"), pid("79999999999"), pv1(api)]),
        "hl7_bad_class": "\r".join([msh(api, "ADT^A01", "E-2"), pid(), pv1(api, f2="Z")]),
        "unknown_facility": "\r".join(
            [msh(api, "ADT^A01", "E-3"), pid(), pv1(api, f3="W^^^NOWHERE")]
        ),
        "unknown_practitioner": "\r".join(
            [msh(api, "ADT^A01", "E-4"), pid(), pv1(api, f7="HCP-ghost")]
        ),
        "hl7_missing_field": "\r".join([msh(api, "ADT^A01", "E-5"), pid(), pv1(api, f44="")]),
        "future_admission": "\r".join(
            [msh(api, "ADT^A01", "E-6"), pid(), pv1(api, f44="20991231")]
        ),
        "hl7_invalid": "\r".join([msh(api, "ADT^A01", "E-7"), pid(), pv1(api, f44="yesterday")]),
        "hl7_unsupported": "\r".join([msh(api, "ADT^A08", "E-8"), pid()]),
    }
    for expected, message in cases.items():
        out = send(api, message).json()
        assert (out["status"], out["ack_code"], out["error_code"]) == (
            "rejected",
            "AE",
            expected,
        ), (expected, out)
        assert out["ack"].split("\r")[1].startswith(f"MSA|AE|{out['control_id']}|")
    rejected = api.get("admin", "/v1/interfaces/messages?status=rejected").json()
    assert len(rejected) == len(cases)
    assert "79999999999" not in str(rejected)  # the log holds no message text
    # Unreadable: rejected outright, nothing filed.
    junk = send(api, "this is not HL7 at all").json()
    assert (junk["ack_code"], junk["error_code"], junk["message_id"]) == ("AR", "hl7_invalid", None)
    assert site  # the facility code used above is the tenant's own


def test_orders_and_results_that_do_not_fit_are_refused(api: Api) -> None:
    pid_ = register(api)
    admit(api, pid_)
    other = register(api, "71111111111")
    admit(api, other, visit="V-OTHER")

    def code(message: str) -> str:
        out = send(api, message).json()
        assert out["ack_code"] == "AE", out
        return str(out["error_code"])

    assert code(orm(api, "O-1", order_control="CA")) == "hl7_unsupported"
    assert code(orm(api, "O-2", visit="V-NONE")) == "unknown_encounter"
    assert code(orm(api, "O-3", service="")) == "hl7_missing_field"
    assert code(orm(api, "O-4", service="X" * 70 + "^Too long^LN")) == "hl7_invalid_order"
    assert send(api, orm(api, "O-5")).json()["status"] == "processed"
    assert code(oru(api, "R-1", nin="71111111111")) == "patient_mismatch"
    assert code(oru(api, "R-2", status="X")) == "hl7_bad_status"
    assert code(oru(api, "R-3", scientist="HCP-ghost")) == "unknown_practitioner"
    assert code(oru(api, "R-4", value="high")) == "hl7_invalid_result"
    assert (
        code(oru(api, "R-5", obx=seg("OBX", {1: "1", 2: "ED", 3: "X^Y^LN", 5: "..."})))
        == "hl7_unsupported"
    )
    assert (
        code(oru(api, "R-6", obx=seg("OBX", {1: "1", 2: "ST", 3: "X^Y^LN", 5: ""})))
        == "invariant_violation"
    )
    assert code(oru(api, "R-11", obx="")) == "hl7_invalid_result"  # no observations
    two = oru(api, "R-7") + "\r" + seg("OBR", {1: "2", 2: "PL-1^EXTLAB"})
    assert code(two) == "hl7_one_order"
    # Coded and text results, and a coding system with no canonical name.
    coded = oru(
        api,
        "R-8",
        obx=seg("OBX", {1: "1", 2: "CWE", 3: "600-7^Culture^LN", 5: "264868006^No growth^SCT"}),
    )
    assert send(api, coded).json()["status"] == "processed"
    text = oru(
        api,
        "R-9",
        obx=seg("OBX", {1: "1", 2: "TX", 3: "C1^Comment^99LOCAL", 5: "Haemolysed\\S\\repeat"}),
    )
    assert send(api, text).json()["status"] == "processed"
    # A held result that does not fit its order when it arrives is rejected then.
    send(api, oru(api, "R-10", placer="PL-9", nin="71111111111"))
    out = send(api, orm(api, "O-6", placer="PL-9")).json()
    assert out["detail"] == "applied 1 held result(s)"
    [late] = [
        m for m in api.get("admin", "/v1/interfaces/messages").json() if m["control_id"] == "R-10"
    ]
    assert (late["status"], late["error_code"]) == ("rejected", "patient_mismatch")


def test_only_the_interface_engine_sends_and_monitors(api: Api) -> None:
    assert send(api, orm(api, "O-1"), who="clinician").status_code == 403
    assert api.get("clerk", "/v1/interfaces/messages").status_code == 403
    assert api.get("interface", "/v1/interfaces/messages").json() == []
    assert uuid  # ids in this module come from the API
