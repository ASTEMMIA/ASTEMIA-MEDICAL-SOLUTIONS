"""Appointments and referrals (CEDA UG01, HS04, HS05; SA-05).

Booking is two steps. A hold reserves a slot for a few minutes and expires on
the server; confirming the hold books the appointment. The data layer allows
one live hold and one booked appointment per slot, so two schedulers racing
for the last slot cannot both succeed. A reschedule locks both slots in a fixed
order and commits everything together: if the new slot cannot be had, the
original booking stands.
"""

import uuid
import zoneinfo
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, select, update
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import (
    Appointment,
    DiagnosticReport,
    Encounter,
    Organisation,
    OrganisationSite,
    Patient,
    Practitioner,
    Referral,
    ReferralRecord,
    ServiceRequest,
    Slot,
    SlotHold,
)
from astemia.application import views
from astemia.application.catalogue import resolve_service_for_admission
from astemia.application.commands import open_encounter
from astemia.application.context import RequestContext
from astemia.application.errors import AccessDenied, Conflict, NotFound, Unprocessable
from astemia.application.policy import Decision, PolicyEngine
from astemia.application.schemas import (
    AppointmentOut,
    BookAppointment,
    CancelAppointment,
    ClinicAppointmentOut,
    CreateSlots,
    DecideReferral,
    HoldOut,
    RecordAttendance,
    ReferralOut,
    ReferralRecordsOut,
    RescheduleAppointment,
    SlotOut,
    SubmitReferral,
)
from astemia.application.views import merged_from
from astemia.application.write_path import (
    CommandResult,
    Unit,
    WritePath,
    audit_row,
    read_path,
)
from astemia.domain import scheduling as sch
from astemia.domain.common import DomainError, Sensitivity, new_id
from astemia.domain.encounter import EncounterClass
from astemia.domain.events import EventType
from astemia.domain.identity import OPEN_STATUSES

BOOKABLE = [s.value for s in OPEN_STATUSES]


def _domain(fn: Any) -> Any:
    try:
        return fn()
    except DomainError as exc:
        raise Unprocessable(str(exc), code=exc.code) from None


def _live_hold(tenant_id: uuid.UUID, at: datetime) -> Any:
    return and_(
        SlotHold.tenant_id == tenant_id,
        SlotHold.slot_id == Slot.id,
        SlotHold.live_marker == 1,
        SlotHold.expires_at > at,
    )


def _booked(tenant_id: uuid.UUID) -> Any:
    return and_(
        Appointment.tenant_id == tenant_id,
        Appointment.slot_id == Slot.id,
        Appointment.booked_marker == 1,
    )


def slot_status(session: Session, slot: Slot, at: datetime) -> sch.SlotStatus:
    tid = slot.tenant_id
    booked = session.execute(select(exists().where(_booked(tid), Slot.id == slot.id))).scalar()
    if booked:
        return sch.SlotStatus.BOOKED
    held = session.execute(select(exists().where(_live_hold(tid, at), Slot.id == slot.id))).scalar()
    return sch.SlotStatus.HELD if held else sch.SlotStatus.AVAILABLE


def slot_out(slot: Slot, status: sch.SlotStatus) -> SlotOut:
    return SlotOut(
        id=slot.id,
        facility_id=slot.facility_id,
        practitioner_id=slot.practitioner_id,
        service=slot.service,
        slot_type=slot.slot_type,
        modality=slot.modality,
        starts_at=slot.starts_at,
        ends_at=slot.ends_at,
        timezone=slot.timezone,
        status=status.value,
    )


def appointment_out(row: Appointment, slot: Slot) -> AppointmentOut:
    return AppointmentOut(
        id=row.id,
        version=row.version,
        patient_id=row.patient_id,
        slot_id=row.slot_id,
        status=row.status,
        facility_id=slot.facility_id,
        practitioner_id=slot.practitioner_id,
        service=slot.service,
        modality=slot.modality,
        starts_at=slot.starts_at,
        ends_at=slot.ends_at,
        reason=row.reason,
        cancel_reason=row.cancel_reason,
        referral_id=row.referral_id,
        rescheduled_from_id=row.rescheduled_from_id,
        encounter_id=row.encounter_id,
    )


def referral_out(row: Referral) -> ReferralOut:
    return ReferralOut(
        id=row.id,
        version=row.version,
        patient_id=row.patient_id,
        referrer_id=row.referrer_id,
        source_encounter_id=row.source_encounter_id,
        requesting_service=row.requesting_service,
        receiving_service=row.receiving_service,
        priority=row.priority,
        reason=row.reason,
        status=row.status,
        decided_by_id=row.decided_by_id,
        decided_at=row.decided_at,
        decision_reason=row.decision_reason,
        recorded_at=row.recorded_at,
        referring_facility_id=row.referring_facility_id,
        receiving_facility_id=row.receiving_facility_id,
        referring_level=row.referring_level,
        receiving_level=row.receiving_level,
        records_count=row.records_count,
    )


def _envelope(u: Unit) -> dict[str, Any]:
    return {
        "tenant_id": u.ctx.tenant_id,
        "id": new_id(),
        "version": 1,
        "recorded_at": u.ctx.now,
        "author_id": u.ctx.principal.practitioner_id,
    }


def _lock_slots(u: Unit, *ids: uuid.UUID) -> dict[uuid.UUID, Slot]:
    """Lock slots in id order, so two reschedules in opposite directions
    cannot deadlock."""
    return {sid: u.get(Slot, sid, lock=True) for sid in sorted(set(ids))}


def _take_hold(u: Unit, hold_id: uuid.UUID) -> SlotHold:
    """The caller's own live hold, consumed by a booking."""
    hold = u.get(SlotHold, hold_id, lock=True)
    if hold.holder_subject != u.ctx.principal.subject:
        u.deny("not_hold_owner")
    if hold.outcome == "confirmed":
        raise Conflict("this hold has already been used", code="hold_used")
    if not sch.hold_live(hold.expires_at, hold.released_at is not None, u.ctx.now):
        # A stale token: the slot went back to the pool when the hold expired.
        raise Conflict("the hold has expired; hold the slot again", code="hold_expired")
    hold.released_at, hold.outcome, hold.live_marker = u.ctx.now, "confirmed", None
    hold.version += 1
    return hold


def _referral_for_booking(
    u: Unit, referral_id: uuid.UUID | None, patient_id: uuid.UUID
) -> Referral | None:
    if referral_id is None:
        return None
    referral = u.get(Referral, referral_id, lock=True)
    if referral.patient_id != patient_id:
        raise Unprocessable(
            "the referral is for a different patient", code="referral_patient_mismatch"
        )
    referral.status = _domain(
        lambda: sch.move_referral(sch.ReferralStatus(referral.status), sch.ReferralStatus.SCHEDULED)
    ).value
    referral.version += 1
    return referral


def _release_referral(u: Unit, appointment: Appointment, to: sch.ReferralStatus) -> None:
    if appointment.referral_id is None:
        return
    referral = u.get(Referral, appointment.referral_id, lock=True)
    if referral.status == sch.ReferralStatus.SCHEDULED:
        referral.status = sch.move_referral(sch.ReferralStatus.SCHEDULED, to).value
        referral.version += 1


def _care_records(u: Unit, patient_id: uuid.UUID, encounter_id: uuid.UUID | None) -> Encounter:
    """The care episode a referral summarises. A patient with no care records
    here (no encounter on this record or one merged into it) is not referred:
    the receiving team, a teaching hospital for example, would get nothing to
    act on (CEDA revision 1.5, HS05)."""
    family = [patient_id, *merged_from(u.session, u.ctx.tenant_id, patient_id)]
    if encounter_id is not None:
        encounter = u.get(Encounter, encounter_id)
        if encounter.patient_id not in family:
            raise Unprocessable(
                "encounter does not belong to this patient", code="encounter_patient_mismatch"
            )
        return encounter
    latest = u.session.execute(
        select(Encounter)
        .where(Encounter.tenant_id == u.ctx.tenant_id, Encounter.patient_id.in_(family))
        .order_by(Encounter.period_start.desc(), Encounter.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest is None:
        raise Unprocessable(
            "this patient has no care records to send with the referral; record the "
            "care first (an admission or an attended appointment)",
            code="no_care_records",
        )
    return latest


def _package_records(u: Unit, referral: Referral) -> int:
    """Attach every historical record of the patient, and of any record merged
    into it, to the referral. Not optional: the receiving hospital always gets
    the patient's history with the referral (CEDA revision 1.5)."""
    family = [referral.patient_id, *merged_from(u.session, u.ctx.tenant_id, referral.patient_id)]
    tid = u.ctx.tenant_id
    sources: list[tuple[sch.RecordType, Any, Any]] = [
        (sch.RecordType.ENCOUNTER, Encounter, Encounter.period_start),
        (sch.RecordType.ORDER, ServiceRequest, ServiceRequest.recorded_at),
        (sch.RecordType.REPORT, DiagnosticReport, DiagnosticReport.released_at),
    ]
    count = 0
    for kind, model, when in sources:
        for record_id, patient_id, at in u.session.execute(
            select(model.id, model.patient_id, when).where(
                model.tenant_id == tid, model.patient_id.in_(family)
            )
        ).all():
            u.session.add(
                ReferralRecord(
                    tenant_id=tid,
                    id=new_id(),
                    referral_id=referral.id,
                    record_type=kind.value,
                    record_id=record_id,
                    patient_id=patient_id,
                    recorded_at=at,
                )
            )
            count += 1
    return count


class Scheduling:
    def __init__(
        self, write_path: WritePath, factory: sessionmaker[Session], policy: PolicyEngine
    ) -> None:
        self.wp = write_path
        self.factory = factory
        self.policy = policy

    # -- slots --------------------------------------------------------------------

    def create_slots(self, ctx: RequestContext, key: str | None, cmd: CreateSlots) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            _domain(lambda: sch.check_slot_run(cmd.starts_at, cmd.minutes, cmd.count, u.ctx.now))
            try:
                zoneinfo.ZoneInfo(cmd.timezone)
            except zoneinfo.ZoneInfoNotFoundError, ValueError:
                raise Unprocessable("unknown time zone", code="bad_timezone") from None
            u.get(OrganisationSite, cmd.facility_id)
            u.get(Practitioner, cmd.practitioner_id)
            service_id = resolve_service_for_admission(u, cmd.service, cmd.facility_id)
            slots = []
            for starts, ends in sch.slot_run(cmd.starts_at, cmd.minutes, cmd.count):
                slot = Slot(
                    facility_id=cmd.facility_id,
                    practitioner_id=cmd.practitioner_id,
                    service=cmd.service,
                    clinical_service_id=service_id,
                    slot_type=cmd.slot_type.value,
                    modality=cmd.modality.value,
                    starts_at=starts,
                    ends_at=ends,
                    timezone=cmd.timezone,
                    **_envelope(u),
                )
                u.session.add(slot)
                slots.append(slot)
            u.session.flush()  # a clash with an existing slot is a 409
            decision = u.authorize("schedule:manage")
            u.audit(decision, "slot.create", "slot", slots[0].id)
            body = {
                "slots": [
                    slot_out(s, sch.SlotStatus.AVAILABLE).model_dump(mode="json") for s in slots
                ]
            }
            return CommandResult(201, body)

        return self.wp.run(
            ctx,
            operation="slot.create",
            capability="schedule:manage",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json"),
            handler=handle,
        )

    def search(
        self,
        ctx: RequestContext,
        *,
        facility_id: uuid.UUID | None,
        service: str | None,
        practitioner_id: uuid.UUID | None,
        slot_type: sch.SlotType | None,
        start: datetime | None,
        end: datetime | None,
        available_only: bool,
        limit: int,
    ) -> list[SlotOut]:
        def read(session: Session, decision: Decision) -> list[SlotOut]:
            tid, at = ctx.tenant_id, ctx.now
            lower = start or at
            upper = end or lower + timedelta(days=14)
            stmt = select(Slot).where(
                Slot.tenant_id == tid, Slot.starts_at >= lower, Slot.starts_at < upper
            )
            for column, value in (
                (Slot.facility_id, facility_id),
                (Slot.service, service),
                (Slot.practitioner_id, practitioner_id),
                (Slot.slot_type, slot_type.value if slot_type else None),
            ):
                if value is not None:
                    stmt = stmt.where(column == value)
            if available_only:
                stmt = stmt.where(
                    ~exists().where(_booked(tid)), ~exists().where(_live_hold(tid, at))
                )
            rows = session.execute(stmt.order_by(Slot.starts_at, Slot.id).limit(limit)).scalars()
            return [slot_out(s, slot_status(session, s, at)) for s in rows]

        return read_path(
            self.factory,
            self.policy,
            ctx,
            capability="schedule:book",
            action="slot.search",
            resource_type="slot",
            patient_id=None,
            reader=read,
        )

    def clinic_list(
        self,
        ctx: RequestContext,
        *,
        start: datetime | None,
        end: datetime | None,
        facility_id: uuid.UUID | None,
        practitioner_id: uuid.UUID | None,
        patient_id: uuid.UUID | None,
        status: str | None,
        limit: int,
    ) -> list[ClinicAppointmentOut]:
        """Appointments in a period (today by default), in time order, for the
        people who run clinics: to reschedule, cancel or record attendance."""

        def read(session: Session, decision: Decision) -> list[ClinicAppointmentOut]:
            tid = ctx.tenant_id
            lower = start or ctx.now.replace(hour=0, minute=0, second=0, microsecond=0)
            upper = end or lower + timedelta(days=1)
            stmt = (
                select(Appointment, Slot, Patient)
                .join(
                    Slot,
                    (Slot.tenant_id == Appointment.tenant_id) & (Slot.id == Appointment.slot_id),
                )
                .join(
                    Patient,
                    (Patient.tenant_id == Appointment.tenant_id)
                    & (Patient.id == Appointment.patient_id),
                )
                .where(
                    Appointment.tenant_id == tid, Slot.starts_at >= lower, Slot.starts_at < upper
                )
            )
            for column, value in (
                (Slot.facility_id, facility_id),
                (Slot.practitioner_id, practitioner_id),
                (Appointment.patient_id, patient_id),
                (Appointment.status, status),
            ):
                if value is not None:
                    stmt = stmt.where(column == value)
            rows = session.execute(stmt.order_by(Slot.starts_at, Appointment.id).limit(limit)).all()
            return [
                ClinicAppointmentOut(
                    appointment=appointment_out(a, s),
                    patient=views.patient(session, p, masks=decision.masks, at=ctx.now),
                )
                for a, s, p in rows
            ]

        return read_path(
            self.factory,
            self.policy,
            ctx,
            capability="appointment:attend",
            action="appointment.list",
            resource_type="appointment",
            patient_id=None,
            reader=read,
        )

    def hold(self, ctx: RequestContext, key: str | None, slot_id: uuid.UUID) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            slot = u.get(Slot, slot_id, lock=True)  # one holder at a time per slot
            if slot.starts_at <= u.ctx.now:
                raise Conflict("this slot has already started", code="slot_started")
            # Holds expire on the server: clear any that have run out.
            u.session.execute(
                update(SlotHold)
                .where(
                    SlotHold.tenant_id == u.ctx.tenant_id,
                    SlotHold.slot_id == slot.id,
                    SlotHold.live_marker == 1,
                    SlotHold.expires_at <= u.ctx.now,
                )
                .values(released_at=u.ctx.now, outcome="expired", live_marker=None)
            )
            status = slot_status(u.session, slot, u.ctx.now)
            if status is sch.SlotStatus.BOOKED:
                raise Conflict("this slot is booked", code="slot_booked")
            if status is sch.SlotStatus.HELD:
                raise Conflict("another booking is in progress for this slot", code="slot_held")
            hold = SlotHold(
                slot_id=slot.id,
                holder_subject=u.ctx.principal.subject,
                expires_at=u.ctx.now + sch.HOLD_DURATION,
                live_marker=1,
                **_envelope(u),
            )
            u.session.add(hold)
            u.session.flush()
            decision = u.authorize("schedule:book")
            u.audit(decision, "slot.hold", "slot_hold", hold.id)
            out = HoldOut(id=hold.id, slot_id=slot.id, expires_at=hold.expires_at)
            return CommandResult(201, out.model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="slot.hold",
            capability="schedule:book",
            idempotency_key=key,
            payload={"slot_id": str(slot_id)},
            handler=handle,
            resource=("slot", slot_id),
        )

    # -- appointments ----------------------------------------------------------------

    def book(self, ctx: RequestContext, key: str | None, cmd: BookAppointment) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            hold = _take_hold(u, cmd.hold_id)
            slot = u.get(Slot, hold.slot_id, lock=True)
            patient = u.get(Patient, cmd.patient_id)
            if patient.status not in BOOKABLE:
                raise Conflict(f"patient is {patient.status}", code="patient_not_bookable")
            referral = _referral_for_booking(u, cmd.referral_id, patient.id)
            appointment = Appointment(
                patient_id=patient.id,
                slot_id=slot.id,
                referral_id=cmd.referral_id,
                status=sch.AppointmentStatus.BOOKED.value,
                booked_marker=1,
                reason=cmd.reason,
                effective_at=slot.starts_at,
                **_envelope(u),
            )
            u.session.add(appointment)
            u.session.flush()  # the one-booking-per-slot guard
            decision = u.authorize("schedule:book")
            event = u.emit(
                EventType.APPOINTMENT_BOOKED,
                "appointment",
                appointment.id,
                1,
                slot.starts_at,
                {
                    "appointment_id": str(appointment.id),
                    "patient_id": str(patient.id),
                    "slot_id": str(slot.id),
                    "service": slot.service,
                    "starts_at": slot.starts_at.isoformat(),
                    "referral_id": str(referral.id) if referral else None,
                },
            )
            u.audit(
                decision,
                "appointment.book",
                "appointment",
                appointment.id,
                patient_id=patient.id,
                event_id=event,
            )
            return CommandResult(201, appointment_out(appointment, slot).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="appointment.book",
            capability="schedule:book",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json"),
            handler=handle,
        )

    def reschedule(
        self,
        ctx: RequestContext,
        key: str | None,
        appointment_id: uuid.UUID,
        expected: int | None,
        cmd: RescheduleAppointment,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            old = u.get(Appointment, appointment_id, lock=True)
            u.check_version(old.version, expected)
            hold = _take_hold(u, cmd.hold_id)
            slots = _lock_slots(u, old.slot_id, hold.slot_id)
            old.status = _domain(
                lambda: sch.move_appointment(
                    sch.AppointmentStatus(old.status), sch.AppointmentStatus.RESCHEDULED
                )
            ).value
            old.booked_marker, old.version = None, old.version + 1
            u.session.flush()
            new = Appointment(
                patient_id=old.patient_id,
                slot_id=hold.slot_id,
                referral_id=old.referral_id,
                rescheduled_from_id=old.id,
                status=sch.AppointmentStatus.BOOKED.value,
                booked_marker=1,
                reason=old.reason,
                effective_at=slots[hold.slot_id].starts_at,
                **_envelope(u),
            )
            u.session.add(new)
            u.session.flush()  # if the new slot is taken, everything rolls back
            decision = u.authorize("schedule:book")
            event = u.emit(
                EventType.APPOINTMENT_RESCHEDULED,
                "appointment",
                new.id,
                1,
                slots[hold.slot_id].starts_at,
                {
                    "appointment_id": str(new.id),
                    "rescheduled_from_id": str(old.id),
                    "patient_id": str(new.patient_id),
                    "from_slot_id": str(old.slot_id),
                    "to_slot_id": str(new.slot_id),
                },
            )
            for row in (old, new):
                u.audit(
                    decision,
                    "appointment.reschedule",
                    "appointment",
                    row.id,
                    patient_id=row.patient_id,
                    event_id=event,
                )
            body = appointment_out(new, slots[hold.slot_id]).model_dump(mode="json")
            return CommandResult(200, body)

        return self.wp.run(
            ctx,
            operation="appointment.reschedule",
            capability="schedule:book",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json")
            | {"appointment_id": str(appointment_id), "v": expected},
            handler=handle,
            resource=("appointment", appointment_id),
        )

    def cancel(
        self,
        ctx: RequestContext,
        key: str | None,
        appointment_id: uuid.UUID,
        expected: int | None,
        cmd: CancelAppointment,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            row = u.get(Appointment, appointment_id, lock=True)
            u.check_version(row.version, expected)
            row.status = _domain(
                lambda: sch.move_appointment(
                    sch.AppointmentStatus(row.status), sch.AppointmentStatus.CANCELLED
                )
            ).value
            row.booked_marker, row.cancel_reason = None, cmd.reason
            row.version += 1
            _release_referral(u, row, sch.ReferralStatus.ACCEPTED)
            slot = u.get(Slot, row.slot_id)
            decision = u.authorize("schedule:book")
            event = u.emit(
                EventType.APPOINTMENT_CANCELLED,
                "appointment",
                row.id,
                row.version,
                u.ctx.now,
                {"appointment_id": str(row.id), "patient_id": str(row.patient_id)},
            )
            u.audit(
                decision,
                "appointment.cancel",
                "appointment",
                row.id,
                patient_id=row.patient_id,
                event_id=event,
            )
            return CommandResult(200, appointment_out(row, slot).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="appointment.cancel",
            capability="schedule:book",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json")
            | {"appointment_id": str(appointment_id), "v": expected},
            handler=handle,
            resource=("appointment", appointment_id),
        )

    def attendance(
        self,
        ctx: RequestContext,
        key: str | None,
        appointment_id: uuid.UUID,
        expected: int | None,
        cmd: RecordAttendance,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            row = u.get(Appointment, appointment_id, lock=True)
            u.check_version(row.version, expected)
            slot = u.get(Slot, row.slot_id)
            modality = sch.Modality(slot.modality)
            _domain(lambda: sch.check_outcome(cmd.outcome, modality))
            remote = modality in sch.REMOTE
            if (
                cmd.outcome is sch.AttendanceOutcome.ATTENDED
                and remote
                and not cmd.identity_verified
            ):
                raise Unprocessable(
                    "verify the patient's identity before a remote consultation",
                    code="identity_not_verified",
                )
            row.status = _domain(
                lambda: sch.move_appointment(
                    sch.AppointmentStatus(row.status), sch.AppointmentStatus(cmd.outcome.value)
                )
            ).value
            row.booked_marker, row.outcome_recorded_at = None, u.ctx.now
            row.version += 1
            if cmd.outcome is sch.AttendanceOutcome.ATTENDED:
                # Authorised attendance creates the visit (HS04).
                encounter = open_encounter(
                    u,
                    patient_id=row.patient_id,
                    facility_id=slot.facility_id,
                    practitioner_id=slot.practitioner_id,
                    visit_authority="APPOINTMENT",
                    visit_number=f"APT-{row.id.hex[-12:].upper()}",
                    encounter_class=EncounterClass.VIRTUAL if remote else EncounterClass.AMBULATORY,
                    service=slot.service,
                    clinical_service_id=slot.clinical_service_id,
                    started_at=u.ctx.now,
                    sensitivity="normal",
                    admission_route="appointment",
                )
                row.encounter_id = encounter.id
                _release_referral(u, row, sch.ReferralStatus.CLOSED)
            else:
                # Not seen: the referral goes back to the waiting list to rebook.
                _release_referral(u, row, sch.ReferralStatus.ACCEPTED)
            u.session.flush()
            decision = u.authorize("appointment:attend")
            event = u.emit(
                EventType.APPOINTMENT_OUTCOME_RECORDED,
                "appointment",
                row.id,
                row.version,
                u.ctx.now,
                {
                    "appointment_id": str(row.id),
                    "patient_id": str(row.patient_id),
                    "outcome": cmd.outcome.value,
                    "encounter_id": str(row.encounter_id) if row.encounter_id else None,
                },
            )
            u.audit(
                decision,
                "appointment.attendance",
                "appointment",
                row.id,
                patient_id=row.patient_id,
                event_id=event,
            )
            return CommandResult(200, appointment_out(row, slot).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="appointment.attendance",
            capability="appointment:attend",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json")
            | {"appointment_id": str(appointment_id), "v": expected},
            handler=handle,
            resource=("appointment", appointment_id),
        )

    # -- referrals ---------------------------------------------------------------------

    def refer(self, ctx: RequestContext, key: str | None, cmd: SubmitReferral) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            referrer = u.ctx.principal.practitioner_id
            assert referrer is not None  # guaranteed by the relationship-bound policy
            patient = u.get(Patient, cmd.patient_id)
            if patient.status not in BOOKABLE:
                raise Conflict(f"patient is {patient.status}", code="patient_not_bookable")
            source = _care_records(u, patient.id, cmd.encounter_id)
            _domain(
                lambda: sch.check_facilities(cmd.referring_facility_id, cmd.receiving_facility_id)
            )
            levels = [
                sch.care_level(
                    u.get(
                        Organisation, u.get(OrganisationSite, fid).organisation_id
                    ).organisation_type
                )
                for fid in (cmd.referring_facility_id, cmd.receiving_facility_id)
            ]
            referral = Referral(
                referring_facility_id=cmd.referring_facility_id,
                receiving_facility_id=cmd.receiving_facility_id,
                referring_level=levels[0].value if levels[0] else None,
                receiving_level=levels[1].value if levels[1] else None,
                patient_id=patient.id,
                referrer_id=referrer,
                source_encounter_id=source.id,
                requesting_service=cmd.requesting_service,
                receiving_service=cmd.receiving_service,
                priority=cmd.priority.value,
                reason=cmd.reason,
                status=sch.ReferralStatus.SUBMITTED.value,
                **_envelope(u),
            )
            u.session.add(referral)
            u.session.flush()
            referral.records_count = _package_records(u, referral)
            decision = u.authorize("referral:create", patient_id=patient.id)
            # The reason stays out of the event: it is clinical text.
            event = u.emit(
                EventType.REFERRAL_SUBMITTED,
                "referral",
                referral.id,
                1,
                u.ctx.now,
                {
                    "referral_id": str(referral.id),
                    "patient_id": str(patient.id),
                    "source_encounter_id": str(source.id),
                    "receiving_facility_id": str(cmd.receiving_facility_id),
                    "receiving_level": referral.receiving_level,
                    "records_count": referral.records_count,
                    "receiving_service": referral.receiving_service,
                    "priority": referral.priority,
                },
            )
            u.audit(
                decision,
                "referral.submit",
                "referral",
                referral.id,
                patient_id=patient.id,
                event_id=event,
            )
            return CommandResult(201, referral_out(referral).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="referral.submit",
            capability="referral:create",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json"),
            handler=handle,
            patient_id=cmd.patient_id,
        )

    def decide(
        self,
        ctx: RequestContext,
        key: str | None,
        referral_id: uuid.UUID,
        expected: int | None,
        cmd: DecideReferral,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            referral = u.get(Referral, referral_id, lock=True)
            u.check_version(referral.version, expected)
            decision_status = sch.ReferralStatus(cmd.decision)
            _domain(lambda: sch.check_decision(decision_status, cmd.reason))
            referral.status = _domain(
                lambda: sch.move_referral(sch.ReferralStatus(referral.status), decision_status)
            ).value
            referral.decided_by_id = u.ctx.principal.practitioner_id
            referral.decided_at, referral.decision_reason = u.ctx.now, cmd.reason
            referral.version += 1
            decision = u.authorize("referral:triage")
            event = u.emit(
                EventType.REFERRAL_DECIDED,
                "referral",
                referral.id,
                referral.version,
                u.ctx.now,
                {"referral_id": str(referral.id), "decision": cmd.decision},
            )
            u.audit(
                decision,
                "referral.decide",
                "referral",
                referral.id,
                patient_id=referral.patient_id,
                event_id=event,
            )
            return CommandResult(200, referral_out(referral).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="referral.decide",
            capability="referral:triage",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"referral_id": str(referral_id), "v": expected},
            handler=handle,
            resource=("referral", referral_id),
        )

    def referrals(
        self,
        ctx: RequestContext,
        *,
        receiving_service: str | None,
        status: sch.ReferralStatus,
        limit: int,
    ) -> list[ReferralOut]:
        def read(session: Session, decision: Decision) -> list[ReferralOut]:
            stmt = select(Referral).where(
                Referral.tenant_id == ctx.tenant_id, Referral.status == status.value
            )
            if receiving_service:
                stmt = stmt.where(Referral.receiving_service == receiving_service)
            # Urgent first, then oldest first.
            rows = session.execute(
                stmt.order_by(
                    (Referral.priority == sch.ReferralPriority.URGENT.value).desc(),
                    Referral.recorded_at,
                    Referral.id,
                ).limit(limit)
            ).scalars()
            return [referral_out(r) for r in rows]

        return read_path(
            self.factory,
            self.policy,
            ctx,
            capability="referral:triage",
            action="referral.list",
            resource_type="referral",
            patient_id=None,
            reader=read,
        )

    def records(self, ctx: RequestContext, referral_id: uuid.UUID) -> ReferralRecordsOut:
        """The records package, for the receiving team (who triage referrals)
        and for the referrer. Masks and sensitive-record withholding apply as
        for a chart read, and the read is audited before anything is returned.
        A rejected referral no longer opens the package to the receiving side."""
        with self.factory() as session:
            tid = ctx.tenant_id
            referral = session.execute(
                select(Referral).where(Referral.tenant_id == tid, Referral.id == referral_id)
            ).scalar_one_or_none()
            if referral is None:
                raise NotFound("referral not found")
            if ctx.principal.practitioner_id == referral.referrer_id:
                decision = self.policy.decide(
                    session, ctx, "chart:read", patient_id=referral.patient_id
                )
            else:
                decision = self.policy.decide(session, ctx, "referral:triage")
                if decision.allowed and referral.status == sch.ReferralStatus.REJECTED:
                    decision = Decision(
                        False, uuid.uuid7(), decision.policy_version, "referral_rejected"
                    )
            if not decision.allowed:
                session.add(
                    audit_row(
                        ctx,
                        decision,
                        "referral.records",
                        "referral",
                        referral.id,
                        referral.patient_id,
                        "denied",
                    )
                )
                session.commit()
                raise AccessDenied(decision.reason, code=decision.reason, conceal=decision.conceal)
            masks = decision.masks
            packaged: dict[str, list[uuid.UUID]] = {k.value: [] for k in sch.RecordType}
            for kind, record_id in session.execute(
                select(ReferralRecord.record_type, ReferralRecord.record_id).where(
                    ReferralRecord.tenant_id == tid, ReferralRecord.referral_id == referral.id
                )
            ).all():
                packaged[kind].append(record_id)
            withheld = 0

            def visible(sensitivity: str) -> bool:
                nonlocal withheld
                if sensitivity == Sensitivity.NORMAL or f"sensitivity:{sensitivity}" not in masks:
                    return True
                withheld += 1
                return False

            def load(model: Any, kind: sch.RecordType, order: Any) -> list[Any]:
                return [
                    r
                    for r in session.execute(
                        select(model)
                        .where(model.tenant_id == tid, model.id.in_(packaged[kind.value]))
                        .order_by(order)
                    ).scalars()
                    if visible(r.sensitivity)
                ]

            encounters = load(Encounter, sch.RecordType.ENCOUNTER, Encounter.period_start.desc())
            orders = load(ServiceRequest, sch.RecordType.ORDER, ServiceRequest.recorded_at.desc())
            reports = load(
                DiagnosticReport, sch.RecordType.REPORT, DiagnosticReport.released_at.desc()
            )
            patient = session.execute(
                select(Patient).where(Patient.tenant_id == tid, Patient.id == referral.patient_id)
            ).scalar_one()
            out = ReferralRecordsOut(
                referral=referral_out(referral),
                patient=views.patient(session, patient, masks=masks, at=ctx.now),
                encounters=[views.encounter(session, e) for e in encounters],
                orders=[views.order(o) for o in orders],
                reports=[views.report(session, r, masks=masks) for r in reports],
                masked_fields=sorted(m for m in masks if not m.startswith("sensitivity:")),
                withheld_records=withheld,
            )
            session.add(
                audit_row(
                    ctx,
                    decision,
                    "referral.records",
                    "referral",
                    referral.id,
                    referral.patient_id,
                    "success",
                )
            )
            session.commit()
        return out
