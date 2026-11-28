"""Inbound HL7 v2 (CEDA section 6, WF03; ICRS X5; UAT WF03).

The interface engine posts each message as it arrives. A message is applied
once: replaying the same message returns the same acknowledgement and creates
nothing, and a different message under a control id already used is refused.

* ADT^A01 admits a known patient (by an identifier in PID-3) to a facility,
  service and responsible clinician named in PV1.
* ORM^O01 (new order, ORC-1 NW) places an order on the patient's encounter
  under the sender's placer number, for the ordering clinician in ORC-12.
* ORU^R01 releases a result on the order its placer number names. A result
  that arrives before its order is held, and applied when the order arrives.

A message the service cannot apply is kept with an application error (AE) and
its reason, so nothing is lost and it can be corrected and resent; a message
that cannot be read at all is rejected (AR). Every outcome is acknowledged in
HL7 as well as in JSON.
"""

import hashlib
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import (
    Encounter,
    InterfaceMessage,
    OrganisationSite,
    Patient,
    PatientIdentifier,
    Practitioner,
    ServiceRequest,
)
from astemia.application import views
from astemia.application.catalogue import resolve_service_for_admission
from astemia.application.commands import create_order, open_encounter, record_release
from astemia.application.context import RequestContext
from astemia.application.errors import ApplicationError, Unprocessable
from astemia.application.policy import Decision, PolicyEngine
from astemia.application.schemas import (
    Hl7In,
    Hl7Out,
    InterfaceMessageOut,
    ObservationIn,
    PlaceOrder,
    ReleaseReport,
)
from astemia.application.write_path import CommandResult, Unit, WritePath, read_path
from astemia.domain import diagnostics as dx
from astemia.domain import encounter as enc
from astemia.domain import hl7
from astemia.domain.common import DomainError, new_id
from astemia.domain.events import EventType

# HL7 table 0396 coding system names, and the canonical system each stands for.
CODING_SYSTEMS = {
    "LN": "http://loinc.org",
    "SCT": "http://snomed.info/sct",
    "I10": "http://hl7.org/fhir/sid/icd-10",
}
PATIENT_CLASS = {
    "I": enc.EncounterClass.INPATIENT,
    "E": enc.EncounterClass.EMERGENCY,
    "O": enc.EncounterClass.AMBULATORY,
}
ORDER_PRIORITY = {"S": dx.OrderPriority.STAT, "A": dx.OrderPriority.URGENT}
RESULT_STATUS = {
    "F": dx.ReportStatus.FINAL,
    "P": dx.ReportStatus.PRELIMINARY,
    "C": dx.ReportStatus.AMENDED,
}


class Applied:
    """What applying a message did, for the log and the acknowledgement."""

    def __init__(
        self,
        status: str,
        patient_id: uuid.UUID | None = None,
        resource: tuple[str, uuid.UUID] | None = None,
        placer_key: str | None = None,
        note: str = "",
    ) -> None:
        self.status, self.patient_id, self.resource = status, patient_id, resource
        self.placer_key, self.note = placer_key, note


def _need(value: str, what: str) -> str:
    if not value:
        raise Unprocessable(f"{what} is required", code="hl7_missing_field")
    return value


def _system(name: str) -> str:
    return CODING_SYSTEMS.get(name, f"urn:hl7v2:{name or 'local'}")


def _patient(u: Unit, pid: hl7.Segment) -> Patient:
    """The patient whose active identifier appears in PID-3 (any repetition)."""
    for rep in range(len(pid.field(3).split(pid.seps.repetition))):
        value, issuer = pid.component(3, 1, rep), pid.component(3, 4, rep)
        found = u.session.execute(
            select(PatientIdentifier.patient_id).where(
                PatientIdentifier.tenant_id == u.ctx.tenant_id,
                PatientIdentifier.issuer == issuer,
                PatientIdentifier.value == value.replace(" ", "").upper(),
                PatientIdentifier.active_marker == 1,
            )
        ).scalar_one_or_none()
        if found is not None:
            return u.get(Patient, found)
    raise Unprocessable("no patient has an identifier in PID-3", code="unknown_patient")


def _practitioner(u: Unit, professional_id: str, what: str) -> uuid.UUID:
    found = u.session.execute(
        select(Practitioner.id).where(
            Practitioner.tenant_id == u.ctx.tenant_id,
            Practitioner.professional_id == _need(professional_id, what),
        )
    ).scalar_one_or_none()
    if found is None:
        raise Unprocessable(f"{what} {professional_id!r} is not known", code="unknown_practitioner")
    return found


def _placer(msg: hl7.Message, seg: hl7.Segment, field: int) -> tuple[str, str]:
    """(authority, number): the namespace in the field, or the sending application."""
    number = _need(seg.component(field, 1), f"{seg.name}-{field} placer order number")
    return seg.component(field, 2) or msg.msh.component(3), number


class Interfaces:
    def __init__(
        self, write_path: WritePath, factory: sessionmaker[Session], policy: PolicyEngine
    ) -> None:
        self.wp = write_path
        self.factory = factory
        self.policy = policy

    # -- the three message types -----------------------------------------------------

    def _admit(self, u: Unit, msg: hl7.Message) -> Applied:
        patient = _patient(u, msg.first("PID"))
        pv1 = msg.first("PV1")
        klass = PATIENT_CLASS.get(pv1.field(2))
        if klass is None:
            raise Unprocessable(
                f"patient class {pv1.field(2)!r} is not supported", code="hl7_bad_class"
            )
        site_code = pv1.component(3, 4) or msg.msh.component(4)
        site = u.session.execute(
            select(OrganisationSite.id).where(
                OrganisationSite.tenant_id == u.ctx.tenant_id,
                OrganisationSite.site_identifier == site_code,
            )
        ).scalar_one_or_none()
        if site is None:
            raise Unprocessable(f"facility {site_code!r} is not known", code="unknown_facility")
        clinician = _practitioner(u, pv1.component(7, 1), "PV1-7 attending doctor")
        service = _need(pv1.field(10), "PV1-10 hospital service")
        admitted_at = hl7.timestamp(_need(pv1.field(44), "PV1-44 admit date and time"))
        if admitted_at > u.ctx.now:
            raise Unprocessable("admission time is in the future", code="future_admission")
        encounter = open_encounter(
            u,
            patient_id=patient.id,
            facility_id=site,
            practitioner_id=clinician,
            visit_authority=pv1.component(19, 4) or msg.msh.component(4),
            visit_number=_need(pv1.component(19, 1), "PV1-19 visit number"),
            encounter_class=klass,
            service=service,
            clinical_service_id=resolve_service_for_admission(u, service, site),
            started_at=admitted_at,
            sensitivity="normal",
            admission_route=None,
        )
        encounter.source_system, encounter.source_id = msg.sender, msg.control_id
        u.emit(
            EventType.ENCOUNTER_ADMITTED,
            "encounter",
            encounter.id,
            1,
            admitted_at,
            {
                "encounter_id": str(encounter.id),
                "patient_id": str(patient.id),
                "facility_id": str(site),
                "class": encounter.encounter_class,
            },
        )
        return Applied("processed", patient.id, ("encounter", encounter.id))

    def _order(self, u: Unit, msg: hl7.Message, decision: Decision) -> Applied:
        orc, obr = msg.first("ORC"), msg.first("OBR")
        if orc.field(1) != "NW":
            raise Unprocessable(
                f"order control {orc.field(1)!r} is not supported; send NW", code="hl7_unsupported"
            )
        patient = _patient(u, msg.first("PID"))
        pv1 = msg.first("PV1")
        encounter_id = u.session.execute(
            select(Encounter.id).where(
                Encounter.tenant_id == u.ctx.tenant_id,
                Encounter.visit_authority == (pv1.component(19, 4) or msg.msh.component(4)),
                Encounter.visit_number == _need(pv1.component(19, 1), "PV1-19 visit number"),
            )
        ).scalar_one_or_none()
        if encounter_id is None:
            raise Unprocessable("no encounter has that visit number", code="unknown_encounter")
        placer = _placer(msg, orc, 2)
        try:
            cmd = PlaceOrder(
                patient_id=patient.id,
                encounter_id=encounter_id,
                code_system=_system(obr.component(4, 3)),
                code=_need(obr.component(4, 1), "OBR-4 universal service identifier"),
                display=obr.component(4, 2) or obr.component(4, 1),
                priority=ORDER_PRIORITY.get(orc.component(7, 6), dx.OrderPriority.ROUTINE),
            )
        except ValidationError as exc:
            raise Unprocessable(str(exc.errors()[0]["msg"]), code="hl7_invalid_order") from None
        requester = _practitioner(u, orc.component(12, 1), "ORC-12 ordering provider")
        order = create_order(u, cmd, "interface", requester=requester, placer=placer)
        order.source_system, order.source_id = msg.sender, msg.control_id
        u.emit(
            EventType.ORDER_PLACED,
            "service_request",
            order.id,
            1,
            u.ctx.now,
            {
                "order_id": str(order.id),
                "patient_id": str(order.patient_id),
                "encounter_id": str(order.encounter_id),
                "placer_id": order.placer_id,
                "code_system": order.code_system,
                "code": order.code,
                "priority": order.priority,
            },
        )
        note = self._release_held(u, f"{placer[0]}|{placer[1]}", decision)
        return Applied("processed", order.patient_id, ("service_request", order.id), note=note)

    def _result(self, u: Unit, msg: hl7.Message) -> Applied:
        obrs = msg.all("OBR")
        if len(obrs) != 1:
            raise Unprocessable("send one OBR per result message", code="hl7_one_order")
        obr = obrs[0]
        authority, number = _placer(msg, obr, 2)
        order = u.session.execute(
            select(ServiceRequest)
            .where(
                ServiceRequest.tenant_id == u.ctx.tenant_id,
                ServiceRequest.placer_authority == authority,
                ServiceRequest.placer_id == number,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if order is None:
            # The result came first: hold it for its order (UAT WF03).
            return Applied("held", placer_key=f"{authority}|{number}", note="waiting for its order")
        patient = _patient(u, msg.first("PID"))
        if patient.id not in (
            order.patient_id,
            *views.merged_from(u.session, u.ctx.tenant_id, order.patient_id),
        ):
            raise Unprocessable(
                "the result is for another patient than its order", code="patient_mismatch"
            )
        status = RESULT_STATUS.get(obr.field(25))
        if status is None:
            raise Unprocessable(
                f"result status {obr.field(25)!r} is not supported", code="hl7_bad_status"
            )
        scientist = _practitioner(u, obr.component(32, 1), "OBR-32 principal result interpreter")
        try:
            cmd = ReleaseReport(
                service_request_id=order.id,
                status=status,
                filler_authority=obr.component(3, 2) or msg.msh.component(3) or None,
                filler_id=obr.component(3, 1) or None,
                effective_at=hl7.timestamp(_need(obr.field(7), "OBR-7 observation time")),
                observations=[self._observation(obx) for obx in msg.all("OBX")],
            )
        except ValidationError as exc:
            raise Unprocessable(str(exc.errors()[0]["msg"]), code="hl7_invalid_result") from None
        released = record_release(u, cmd, scientist, author_role="interface")
        released.report.source_system, released.report.source_id = msg.sender, msg.control_id
        u.emit(
            EventType.RESULT_AMENDED
            if released.status is dx.ReportStatus.AMENDED
            else EventType.RESULT_RELEASED,
            "diagnostic_report",
            released.report.id,
            1,
            cmd.effective_at,
            {
                "report_id": str(released.report.id),
                "order_id": str(order.id),
                "patient_id": str(order.patient_id),
                "status": released.report.status,
                "prior_report_id": str(released.prior.id) if released.prior else None,
                "review_id": str(released.review.id),
                "revisions": released.revisions,
            },
        )
        return Applied("processed", order.patient_id, ("diagnostic_report", released.report.id))

    @staticmethod
    def _observation(obx: hl7.Segment) -> ObservationIn:
        return ObservationIn.model_validate(Interfaces._observation_fields(obx))

    @staticmethod
    def _observation_fields(obx: hl7.Segment) -> dict[str, Any]:
        kind, value = obx.field(2), obx.component(5, 1)
        base: dict[str, Any] = {
            "code_system": _system(obx.component(3, 3)),
            "code": obx.component(3, 1),
            "display": obx.component(3, 2) or obx.component(3, 1),
            "original_value": obx.field(5)[:255] or None,
        }
        if kind == "NM":
            low, _, high = obx.field(7).partition("-")
            try:
                return base | {
                    "value_type": dx.ValueType.QUANTITY,
                    "quantity": Decimal(value),
                    "unit": obx.component(6, 1) or None,
                    "ref_low": Decimal(low) if low else None,
                    "ref_high": Decimal(high) if high else None,
                }
            except InvalidOperation:
                raise Unprocessable(
                    f"{value!r} is not a number", code="hl7_invalid_result"
                ) from None
        if kind in ("CE", "CWE"):
            return base | {"value_type": dx.ValueType.CODED, "value_code": value}
        if kind in ("ST", "TX", "FT"):
            return base | {"value_type": dx.ValueType.STRING, "text": obx.field(5)}
        raise Unprocessable(f"OBX value type {kind!r} is not supported", code="hl7_unsupported")

    def _release_held(self, u: Unit, placer_key: str, decision: Decision) -> str:
        """Apply the results that arrived before this order, oldest first."""
        held = list(
            u.session.execute(
                select(InterfaceMessage)
                .where(
                    InterfaceMessage.tenant_id == u.ctx.tenant_id,
                    InterfaceMessage.status == "held",
                    InterfaceMessage.placer_key == placer_key,
                )
                .order_by(InterfaceMessage.recorded_at, InterfaceMessage.id)
                .with_for_update()
            ).scalars()
        )
        for row in held:
            self._settle(u, row, hl7.parse(row.raw), decision)
        return f"applied {len(held)} held result(s)" if held else ""

    # -- the common path -------------------------------------------------------------

    def _apply(self, u: Unit, msg: hl7.Message, decision: Decision) -> Applied:
        match msg.message_type:
            case "ADT^A01":
                return self._admit(u, msg)
            case "ORM^O01":
                return self._order(u, msg, decision)
            case "ORU^R01":
                return self._result(u, msg)
            case other:
                raise Unprocessable(f"{other} messages are not accepted", code="hl7_unsupported")

    def _settle(self, u: Unit, row: InterfaceMessage, msg: hl7.Message, decision: Decision) -> None:
        """Apply the message in a savepoint and record the outcome on its row:
        a failure leaves no partial change, only the reason."""
        savepoint = u.session.begin_nested()
        try:
            applied = self._apply(u, msg, decision)
            u.session.flush()
            savepoint.commit()
        except IntegrityError:
            savepoint.rollback()
            self._reject(row, "duplicate", "a record with these identifiers already exists")
            return
        except (ApplicationError, DomainError) as exc:
            savepoint.rollback()
            self._reject(row, exc.code, str(exc))
            return
        row.status, row.ack_code, row.error_code = applied.status, "AA", None
        row.patient_id, row.placer_key = applied.patient_id, applied.placer_key
        row.detail = applied.note or None
        if applied.resource is not None:
            row.resource_type, row.resource_id = applied.resource
        if applied.status == "processed":
            row.processed_at = u.ctx.now
        row.version += 1
        u.audit(
            decision,
            f"interface.{msg.message_type.replace('^', '_').lower()}",
            row.resource_type or "interface_message",
            row.resource_id or row.id,
            patient_id=row.patient_id,
        )

    @staticmethod
    def _reject(row: InterfaceMessage, code: str, detail: str) -> None:
        row.status, row.ack_code = "rejected", "AE"
        row.error_code, row.detail = code, detail[:500]
        row.version += 1

    def receive(self, ctx: RequestContext, cmd: Hl7In) -> CommandResult:
        digest = hashlib.sha256(cmd.message.encode()).hexdigest()

        def handle(u: Unit) -> CommandResult:
            decision = u.authorize("interface:submit")
            try:
                msg = hl7.parse(cmd.message)
            except hl7.Hl7Error as exc:
                # Unreadable: nothing to file it under. Rejected outright.
                return CommandResult(
                    200,
                    Hl7Out(
                        message_id=None,
                        control_id=None,
                        message_type=None,
                        status="rejected",
                        ack_code="AR",
                        error_code=exc.code,
                        detail=str(exc),
                        ack=None,
                    ).model_dump(mode="json"),
                )
            row = InterfaceMessage(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                recorded_at=u.ctx.now,
                source_system=msg.sender[:64],
                source_id=msg.control_id[:128],
                sender=msg.sender[:128],
                control_id=msg.control_id[:64],
                message_type=msg.message_type[:16],
                digest=digest,
                raw=cmd.message,
                status="received",
                ack_code="AA",
            )
            u.session.add(row)
            u.session.flush()  # a control id already used fails here, before anything is applied
            self._settle(u, row, msg, decision)
            u.session.flush()
            text = row.detail or ("accepted" if row.ack_code == "AA" else "error")
            return CommandResult(
                200,
                Hl7Out(
                    message_id=row.id,
                    control_id=row.control_id,
                    message_type=row.message_type,
                    status=row.status,
                    ack_code=row.ack_code,
                    error_code=row.error_code,
                    detail=row.detail,
                    resource_type=row.resource_type,
                    resource_id=row.resource_id,
                    ack=hl7.ack(msg, row.ack_code, text, f"ACK{row.id.hex[-12:]}", u.ctx.now),
                ).model_dump(mode="json"),
            )

        return self.wp.run(
            ctx,
            operation="interface.hl7",
            capability="interface:submit",
            # The message is its own key: the same message twice is one message.
            idempotency_key=f"hl7:{digest}",
            payload={"digest": digest},
            handler=handle,
        )

    def messages(self, ctx: RequestContext, status: str | None) -> list[InterfaceMessageOut]:
        """The message log, without the message text (it holds patient data)."""

        def read(session: Session, decision: Decision) -> list[InterfaceMessageOut]:
            stmt = select(InterfaceMessage).where(InterfaceMessage.tenant_id == ctx.tenant_id)
            if status is not None:
                stmt = stmt.where(InterfaceMessage.status == status)
            rows = session.execute(
                stmt.order_by(InterfaceMessage.recorded_at.desc(), InterfaceMessage.id).limit(500)
            ).scalars()
            return [InterfaceMessageOut.model_validate(r, from_attributes=True) for r in rows]

        return read_path(
            self.factory,
            self.policy,
            ctx,
            capability="interface:monitor",
            action="interface_message.list",
            resource_type="interface_message",
            patient_id=None,
            reader=read,
        )
