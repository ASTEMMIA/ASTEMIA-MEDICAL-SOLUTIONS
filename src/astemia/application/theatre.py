"""Theatres, sessions and cases (CEDA HS03, WF05 step 2).

Tenant administrators set up theatres and their sessions, and mark a session
unavailable when the theatre cannot be used. Schedulers and clinicians book a
case for an open encounter into an open session with time left; the session
row is locked while its booked time changes, so the last minutes go to one
case only. Nurses and clinicians record the safety checklist; the operating
clinician starts and completes the case (a missing step needs an override
with a reason) and hands the patient over from recovery to a named recipient,
who gets a task. Cancelling a scheduled case gives its time back and sends
one review task to the linked plan's owner, or to the surgeon.
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import (
    CarePlan,
    Encounter,
    OrganisationSite,
    Practitioner,
    Task,
    Theatre,
    TheatreCase,
    TheatreSession,
)
from astemia.application.context import RequestContext
from astemia.application.daybook import open_task
from astemia.application.errors import Conflict, NotFound, Unprocessable
from astemia.application.policy import Decision, PolicyEngine
from astemia.application.schemas import (
    BookTheatreCase,
    CancelCase,
    ChecklistEntry,
    CompleteCase,
    CreateTheatre,
    CreateTheatreSession,
    HandOverCase,
    RecordChecklistStep,
    SetSessionStatus,
    SetWardStatus,
    StartCase,
    TheatreCaseOut,
    TheatreOut,
    TheatreSessionOut,
)
from astemia.application.write_path import CommandResult, Unit, WritePath, read_path
from astemia.domain import theatre as th
from astemia.domain.common import DomainError, Sensitivity, new_id
from astemia.domain.encounter import OPEN_STATES, EncounterState
from astemia.domain.events import EventType
from astemia.domain.tasks import Priority, TaskType

REVIEW_DUE = timedelta(days=1)
HANDOVER_DUE = timedelta(minutes=30)


def _domain(fn: Any) -> Any:
    try:
        return fn()
    except DomainError as exc:
        raise Unprocessable(str(exc), code=exc.code) from None


def _done(case: TheatreCase) -> set[th.ChecklistStep]:
    return {th.ChecklistStep(e["step"]) for e in case.checklist}


def theatre_out(row: Theatre) -> TheatreOut:
    return TheatreOut(
        id=row.id,
        version=row.version,
        facility_id=row.facility_id,
        code=row.code,
        name=row.name,
        active=row.active,
    )


def case_out(session: Session, case: TheatreCase, theatre_id: uuid.UUID) -> TheatreCaseOut:
    tasks = session.execute(
        select(Task.id)
        .where(
            Task.tenant_id == case.tenant_id,
            Task.origin_type == "theatre_case",
            Task.origin_id == case.id,
        )
        .order_by(Task.recorded_at, Task.id)
    ).scalars()
    return TheatreCaseOut(
        id=case.id,
        version=case.version,
        session_id=case.session_id,
        theatre_id=theatre_id,
        encounter_id=case.encounter_id,
        patient_id=case.patient_id,
        surgeon_id=case.surgeon_id,
        care_plan_id=case.care_plan_id,
        procedure=case.procedure,
        procedure_code=case.procedure_code,
        laterality=th.Laterality(case.laterality),
        estimated_minutes=case.estimated_minutes,
        status=th.CaseStatus(case.status),
        checklist=[ChecklistEntry.model_validate(e) for e in case.checklist],
        override_reason=case.override_reason,
        started_at=case.started_at,
        completed_at=case.completed_at,
        procedure_note=case.procedure_note,
        cancelled_at=case.cancelled_at,
        cancellation_reason=case.cancellation_reason,
        handover_recipient_id=case.handover_recipient_id,
        handed_over_at=case.handed_over_at,
        handover_note=case.handover_note,
        tasks=list(tasks),
    )


class Theatres:
    def __init__(
        self, write_path: WritePath, factory: sessionmaker[Session], policy: PolicyEngine
    ) -> None:
        self.wp = write_path
        self.factory = factory
        self.policy = policy

    def _patient_of_case(self, ctx: RequestContext, case_id: uuid.UUID) -> uuid.UUID | None:
        with self.factory() as session:
            return session.execute(
                select(TheatreCase.patient_id).where(
                    TheatreCase.tenant_id == ctx.tenant_id, TheatreCase.id == case_id
                )
            ).scalar_one_or_none()

    def _patient_of_encounter(
        self, ctx: RequestContext, encounter_id: uuid.UUID
    ) -> uuid.UUID | None:
        with self.factory() as session:
            return session.execute(
                select(Encounter.patient_id).where(
                    Encounter.tenant_id == ctx.tenant_id, Encounter.id == encounter_id
                )
            ).scalar_one_or_none()

    def _sessions_out(
        self, session: Session, rows: list[TheatreSession]
    ) -> list[TheatreSessionOut]:
        if not rows:
            return []
        tid = rows[0].tenant_id
        theatres = {
            t.id: t
            for t in session.execute(
                select(Theatre).where(
                    Theatre.tenant_id == tid, Theatre.id.in_({r.theatre_id for r in rows})
                )
            ).scalars()
        }
        cases: dict[uuid.UUID, list[uuid.UUID]] = {r.id: [] for r in rows}
        for sid, cid in session.execute(
            select(TheatreCase.session_id, TheatreCase.id)
            .where(
                TheatreCase.tenant_id == tid,
                TheatreCase.session_id.in_(list(cases)),
                TheatreCase.status != th.CaseStatus.CANCELLED.value,
            )
            .order_by(TheatreCase.recorded_at, TheatreCase.id)
        ).all():
            cases[sid].append(cid)
        return [
            TheatreSessionOut(
                id=r.id,
                version=r.version,
                theatre_id=r.theatre_id,
                theatre_code=theatres[r.theatre_id].code,
                starts_at=r.starts_at,
                ends_at=r.ends_at,
                status=th.SessionStatus(r.status),
                status_reason=r.status_reason,
                capacity_minutes=r.capacity_minutes,
                booked_minutes=r.booked_minutes,
                cases=cases[r.id],
            )
            for r in rows
        ]

    # -- set-up -------------------------------------------------------------------

    def create_theatre(
        self, ctx: RequestContext, key: str | None, cmd: CreateTheatre
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            u.get(OrganisationSite, cmd.facility_id)
            row = Theatre(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                recorded_at=u.ctx.now,
                author_id=u.ctx.principal.practitioner_id,
                facility_id=cmd.facility_id,
                code=cmd.code,
                name=cmd.name,
                active=True,
            )
            u.session.add(row)
            u.session.flush()
            decision = u.authorize("theatre:manage")
            u.audit(decision, "theatre.create", "theatre", row.id)
            return CommandResult(201, theatre_out(row).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="theatre.create",
            capability="theatre:manage",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json"),
            handler=handle,
        )

    def set_theatre_status(
        self,
        ctx: RequestContext,
        key: str | None,
        theatre_id: uuid.UUID,
        expected: int | None,
        cmd: SetWardStatus,
    ) -> CommandResult:
        """Take a theatre out of use (or back). Booked cases stay; new bookings
        are refused until it reopens."""

        def handle(u: Unit) -> CommandResult:
            row = u.get(Theatre, theatre_id, lock=True)
            u.check_version(row.version, expected)
            row.active, row.version = cmd.active, row.version + 1
            u.session.flush()
            decision = u.authorize("theatre:manage")
            u.audit(decision, "theatre.status", "theatre", row.id)
            return CommandResult(200, theatre_out(row).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="theatre.status",
            capability="theatre:manage",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"theatre_id": str(theatre_id), "v": expected},
            handler=handle,
            resource=("theatre", theatre_id),
        )

    def create_session(
        self, ctx: RequestContext, key: str | None, theatre_id: uuid.UUID, cmd: CreateTheatreSession
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            theatre = u.get(Theatre, theatre_id, lock=True)  # serialises sessions per theatre
            minutes = _domain(lambda: th.check_session_times(cmd.starts_at, cmd.ends_at))
            clash = u.session.execute(
                select(TheatreSession.id).where(
                    TheatreSession.tenant_id == u.ctx.tenant_id,
                    TheatreSession.theatre_id == theatre.id,
                    TheatreSession.starts_at < cmd.ends_at,
                    TheatreSession.ends_at > cmd.starts_at,
                )
            ).first()
            if clash is not None:
                raise Conflict(
                    "that theatre already has a session at that time", code="session_overlap"
                )
            row = TheatreSession(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                recorded_at=u.ctx.now,
                author_id=u.ctx.principal.practitioner_id,
                theatre_id=theatre.id,
                starts_at=cmd.starts_at,
                ends_at=cmd.ends_at,
                capacity_minutes=minutes,
                booked_minutes=0,
                status=th.SessionStatus.OPEN.value,
            )
            u.session.add(row)
            u.session.flush()
            decision = u.authorize("theatre:manage")
            u.audit(decision, "theatre_session.create", "theatre_session", row.id)
            return CommandResult(
                201, self._sessions_out(u.session, [row])[0].model_dump(mode="json")
            )

        return self.wp.run(
            ctx,
            operation="theatre_session.create",
            capability="theatre:manage",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"theatre_id": str(theatre_id)},
            handler=handle,
            resource=("theatre", theatre_id),
        )

    def set_session_status(
        self,
        ctx: RequestContext,
        key: str | None,
        session_id: uuid.UUID,
        expected: int | None,
        cmd: SetSessionStatus,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            row = u.get(TheatreSession, session_id, lock=True)
            u.check_version(row.version, expected)
            if cmd.status is th.SessionStatus.UNAVAILABLE and row.booked_minutes > 0:
                raise Conflict(
                    "cancel or move the booked cases before closing the session",
                    code="session_has_cases",
                )
            row.status, row.status_reason = cmd.status.value, cmd.reason
            row.version += 1
            u.session.flush()
            decision = u.authorize("theatre:manage")
            u.audit(decision, "theatre_session.status", "theatre_session", row.id)
            return CommandResult(
                200, self._sessions_out(u.session, [row])[0].model_dump(mode="json")
            )

        return self.wp.run(
            ctx,
            operation="theatre_session.status",
            capability="theatre:manage",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"session_id": str(session_id), "v": expected},
            handler=handle,
            resource=("theatre_session", session_id),
        )

    def theatres(self, ctx: RequestContext) -> list[TheatreOut]:
        def read(session: Session, decision: Decision) -> list[TheatreOut]:
            rows = session.execute(
                select(Theatre).where(Theatre.tenant_id == ctx.tenant_id).order_by(Theatre.code)
            ).scalars()
            return [theatre_out(r) for r in rows]

        return read_path(
            self.factory,
            self.policy,
            ctx,
            capability="theatre:read",
            action="theatre.list",
            resource_type="theatre",
            patient_id=None,
            reader=read,
        )

    def sessions(
        self, ctx: RequestContext, theatre_id: uuid.UUID | None
    ) -> list[TheatreSessionOut]:
        def read(session: Session, decision: Decision) -> list[TheatreSessionOut]:
            stmt = select(TheatreSession).where(
                TheatreSession.tenant_id == ctx.tenant_id,
                TheatreSession.ends_at > ctx.now,
            )
            if theatre_id is not None:
                stmt = stmt.where(TheatreSession.theatre_id == theatre_id)
            rows = session.execute(stmt.order_by(TheatreSession.starts_at)).scalars()
            return self._sessions_out(session, list(rows))

        return read_path(
            self.factory,
            self.policy,
            ctx,
            capability="theatre:read",
            action="theatre_session.list",
            resource_type="theatre_session",
            patient_id=None,
            reader=read,
        )

    # -- cases --------------------------------------------------------------------

    def book(self, ctx: RequestContext, key: str | None, cmd: BookTheatreCase) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            encounter = u.get(Encounter, cmd.encounter_id)
            if EncounterState(encounter.state) not in OPEN_STATES:
                raise Unprocessable(
                    "only an open encounter can be booked for theatre", code="encounter_not_open"
                )
            slot = u.get(TheatreSession, cmd.session_id, lock=True)
            theatre = u.get(Theatre, slot.theatre_id)
            if theatre.facility_id != encounter.facility_id:
                raise Unprocessable(
                    "that theatre is in another facility", code="theatre_in_another_facility"
                )
            if slot.ends_at <= u.ctx.now:
                raise Unprocessable("that session has ended", code="session_ended")
            u.get(Practitioner, cmd.surgeon_id)
            if cmd.care_plan_id is not None:
                plan = u.get(CarePlan, cmd.care_plan_id)
                if plan.patient_id != encounter.patient_id:
                    raise Unprocessable(
                        "that plan is for another patient", code="plan_for_another_patient"
                    )
            try:
                th.check_booking(
                    th.SessionStatus(slot.status),
                    theatre.active,
                    slot.capacity_minutes,
                    slot.booked_minutes,
                    cmd.estimated_minutes,
                )
            except DomainError as exc:
                # A resource conflict (UAT WF05), not a malformed request.
                raise Conflict(str(exc), code=exc.code) from None
            slot.booked_minutes += cmd.estimated_minutes
            slot.version += 1
            case = TheatreCase(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                recorded_at=u.ctx.now,
                author_id=u.ctx.principal.practitioner_id,
                sensitivity=encounter.sensitivity,
                session_id=slot.id,
                encounter_id=encounter.id,
                patient_id=encounter.patient_id,
                surgeon_id=cmd.surgeon_id,
                care_plan_id=cmd.care_plan_id,
                procedure=cmd.procedure,
                procedure_code=cmd.procedure_code,
                laterality=cmd.laterality.value,
                estimated_minutes=cmd.estimated_minutes,
                status=th.CaseStatus.SCHEDULED.value,
                checklist=[],
            )
            u.session.add(case)
            u.session.flush()
            decision = u.authorize("theatre:book", patient_id=encounter.patient_id)
            event = u.emit(
                EventType.THEATRE_CASE_BOOKED,
                "theatre_case",
                case.id,
                case.version,
                slot.starts_at,
                {
                    "theatre_case_id": str(case.id),
                    "patient_id": str(case.patient_id),
                    "encounter_id": str(case.encounter_id),
                    "session_id": str(slot.id),
                },
            )
            u.audit(
                decision,
                "theatre_case.book",
                "theatre_case",
                case.id,
                patient_id=case.patient_id,
                event_id=event,
            )
            return CommandResult(201, case_out(u.session, case, theatre.id).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="theatre_case.book",
            capability="theatre:book",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json"),
            handler=handle,
            patient_id=self._patient_of_encounter(ctx, cmd.encounter_id),
        )

    def _act(
        self,
        ctx: RequestContext,
        key: str | None,
        case_id: uuid.UUID,
        expected: int | None,
        cmd: Any,
        *,
        operation: str,
        capability: str,
        apply: Any,
    ) -> CommandResult:
        """Common shape of the case commands: lock, check the version, change
        the case under its rules, authorise for the patient, audit."""

        def handle(u: Unit) -> CommandResult:
            case = u.get(TheatreCase, case_id, lock=True)
            u.check_version(case.version, expected)
            slot = u.get(TheatreSession, case.session_id, lock=True)
            event = apply(u, case, slot)
            case.version += 1
            u.session.flush()
            decision = u.authorize(capability, patient_id=case.patient_id)
            event_id = None
            if event is not None:
                event_id = u.emit(
                    event,
                    "theatre_case",
                    case.id,
                    case.version,
                    u.ctx.now,
                    {
                        "theatre_case_id": str(case.id),
                        "patient_id": str(case.patient_id),
                        "status": case.status,
                    },
                )
            u.audit(
                decision,
                operation,
                "theatre_case",
                case.id,
                patient_id=case.patient_id,
                event_id=event_id,
            )
            return CommandResult(
                200, case_out(u.session, case, slot.theatre_id).model_dump(mode="json")
            )

        return self.wp.run(
            ctx,
            operation=operation,
            capability=capability,
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"case_id": str(case_id), "v": expected},
            handler=handle,
            patient_id=self._patient_of_case(ctx, case_id),
            resource=("theatre_case", case_id),
        )

    def record_step(
        self,
        ctx: RequestContext,
        key: str | None,
        case_id: uuid.UUID,
        expected: int | None,
        cmd: RecordChecklistStep,
    ) -> CommandResult:
        def apply(u: Unit, case: TheatreCase, slot: TheatreSession) -> None:
            _domain(lambda: th.check_step(cmd.step, th.CaseStatus(case.status), _done(case)))
            entry = {
                "step": cmd.step.value,
                "by_id": str(u.ctx.principal.practitioner_id),
                "at": u.ctx.now.isoformat(),
            }
            case.checklist = [*case.checklist, entry]

        return self._act(
            ctx,
            key,
            case_id,
            expected,
            cmd,
            operation="theatre_case.checklist",
            capability="theatre:checklist",
            apply=apply,
        )

    def start(
        self,
        ctx: RequestContext,
        key: str | None,
        case_id: uuid.UUID,
        expected: int | None,
        cmd: StartCase,
    ) -> CommandResult:
        def apply(u: Unit, case: TheatreCase, slot: TheatreSession) -> EventType:
            missing = _domain(
                lambda: th.missing_steps(_done(case), th.BEFORE_START, cmd.override_reason)
            )
            case.status = _domain(
                lambda: th.move(th.CaseStatus(case.status), th.CaseStatus.IN_THEATRE)
            ).value
            if missing:
                case.override_reason = cmd.override_reason
            case.started_at = u.ctx.now
            return EventType.THEATRE_CASE_STARTED

        return self._act(
            ctx,
            key,
            case_id,
            expected,
            cmd,
            operation="theatre_case.start",
            capability="theatre:perform",
            apply=apply,
        )

    def complete(
        self,
        ctx: RequestContext,
        key: str | None,
        case_id: uuid.UUID,
        expected: int | None,
        cmd: CompleteCase,
    ) -> CommandResult:
        def apply(u: Unit, case: TheatreCase, slot: TheatreSession) -> EventType:
            case.status = _domain(
                lambda: th.move(th.CaseStatus(case.status), th.CaseStatus.COMPLETED)
            ).value
            missing = _domain(
                lambda: th.missing_steps(_done(case), th.BEFORE_END, cmd.override_reason)
            )
            if missing:
                case.override_reason = "; ".join(
                    r for r in (case.override_reason, cmd.override_reason) if r
                )
            case.completed_at, case.procedure_note = u.ctx.now, cmd.procedure_note
            return EventType.THEATRE_CASE_COMPLETED

        return self._act(
            ctx,
            key,
            case_id,
            expected,
            cmd,
            operation="theatre_case.complete",
            capability="theatre:perform",
            apply=apply,
        )

    def cancel(
        self,
        ctx: RequestContext,
        key: str | None,
        case_id: uuid.UUID,
        expected: int | None,
        cmd: CancelCase,
    ) -> CommandResult:
        def apply(u: Unit, case: TheatreCase, slot: TheatreSession) -> EventType:
            case.status = _domain(
                lambda: th.move(th.CaseStatus(case.status), th.CaseStatus.CANCELLED)
            ).value
            case.cancelled_at, case.cancellation_reason = u.ctx.now, cmd.reason
            slot.booked_minutes -= case.estimated_minutes  # the time goes back
            slot.version += 1
            owner = case.surgeon_id
            if case.care_plan_id is not None:
                owner = u.get(CarePlan, case.care_plan_id).owner_id
            open_task(
                u,
                subject="An operation was cancelled: review the plan",
                task_type=TaskType.PLAN_REVIEW,
                due_at=u.ctx.now + REVIEW_DUE,
                assignee=owner,
                patient_id=case.patient_id,
                source=("theatre_case", case.id),
            )
            return EventType.THEATRE_CASE_CANCELLED

        return self._act(
            ctx,
            key,
            case_id,
            expected,
            cmd,
            operation="theatre_case.cancel",
            capability="theatre:book",
            apply=apply,
        )

    def hand_over(
        self,
        ctx: RequestContext,
        key: str | None,
        case_id: uuid.UUID,
        expected: int | None,
        cmd: HandOverCase,
    ) -> CommandResult:
        def apply(u: Unit, case: TheatreCase, slot: TheatreSession) -> EventType:
            recipient = u.get(Practitioner, cmd.recipient_id)
            if recipient.id == u.ctx.principal.practitioner_id:
                raise Unprocessable(
                    "hand the patient over to someone else", code="handover_to_self"
                )
            case.status = _domain(
                lambda: th.move(th.CaseStatus(case.status), th.CaseStatus.HANDED_OVER)
            ).value
            case.handover_recipient_id, case.handed_over_at = recipient.id, u.ctx.now
            case.handover_note = cmd.note
            open_task(
                u,
                subject="Receive a patient from theatre recovery",
                task_type=TaskType.HANDOVER,
                due_at=u.ctx.now + HANDOVER_DUE,
                assignee=recipient.id,
                patient_id=case.patient_id,
                priority=Priority.URGENT,
                source=("theatre_case", case.id),
            )
            return EventType.THEATRE_CASE_HANDED_OVER

        return self._act(
            ctx,
            key,
            case_id,
            expected,
            cmd,
            operation="theatre_case.hand_over",
            capability="theatre:perform",
            apply=apply,
        )

    def get(self, ctx: RequestContext, case_id: uuid.UUID) -> TheatreCaseOut:
        patient_id = self._patient_of_case(ctx, case_id)
        if patient_id is None:
            raise NotFound("not found")

        def read(session: Session, decision: Decision) -> TheatreCaseOut:
            case, theatre_id = session.execute(
                select(TheatreCase, TheatreSession.theatre_id)
                .join(
                    TheatreSession,
                    (TheatreSession.tenant_id == TheatreCase.tenant_id)
                    & (TheatreSession.id == TheatreCase.session_id),
                )
                .where(TheatreCase.tenant_id == ctx.tenant_id, TheatreCase.id == case_id)
            ).one()
            if (
                case.sensitivity != Sensitivity.NORMAL
                and f"sensitivity:{case.sensitivity}" in decision.masks
            ):
                raise NotFound("not found")  # withheld, as in the chart
            return case_out(session, case, theatre_id)

        return read_path(
            self.factory,
            self.policy,
            ctx,
            capability="chart:read",
            action="theatre_case.read",
            resource_type="theatre_case",
            patient_id=patient_id,
            reader=read,
        )
