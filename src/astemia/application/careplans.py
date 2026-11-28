"""Conditions and care plans (CEDA HS12; SA-08 CarePlan, PlanRevision,
PlanCycle; Condition).

A clinician in the patient's care records conditions and makes a care plan on
an approved pathway. Each revision is authorised, never changed, and schedules
the plan's sessions. A new revision applies from its effective time: the
sessions still to come from then on are cancelled and rescheduled under it,
and every completed session keeps the exact revision it was delivered under
(HS12 acceptance). A session that falls on a day when another of the patient's
plans already has one is held, and the plan owner gets a Daybook task to
resolve it. Nurses and clinicians in the patient's care deliver sessions.
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import (
    CarePlan,
    Condition,
    Patient,
    PlanCycle,
    PlanRevision,
    Practitioner,
)
from astemia.application.context import RequestContext
from astemia.application.daybook import close_source_tasks, open_task
from astemia.application.errors import NotFound, Unprocessable
from astemia.application.policy import Decision, PolicyEngine
from astemia.application.schemas import (
    CarePlanOut,
    CarePlanSummary,
    CompleteCycle,
    ConditionOut,
    CreatePlan,
    DiscontinuePlan,
    PlanCycleOut,
    PlanRevisionOut,
    RecordCondition,
    ReleaseCycle,
    RevisePlan,
    RevisionIn,
)
from astemia.application.write_path import CommandResult, Unit, WritePath, read_path
from astemia.domain import careplans as cp
from astemia.domain.common import DomainError, new_id
from astemia.domain.events import EventType
from astemia.domain.tasks import TaskStatus, TaskType

PENDING = [s.value for s in cp.PENDING]


def _domain(fn: Any) -> Any:
    try:
        return fn()
    except DomainError as exc:
        raise Unprocessable(str(exc), code=exc.code) from None


def condition_out(row: Condition) -> ConditionOut:
    return ConditionOut.model_validate(row, from_attributes=True)


def plan_out(session: Session, plan: CarePlan) -> CarePlanOut:
    revisions = list(
        session.execute(
            select(PlanRevision)
            .where(PlanRevision.tenant_id == plan.tenant_id, PlanRevision.care_plan_id == plan.id)
            .order_by(PlanRevision.revision_number)
        ).scalars()
    )
    numbers = {r.id: r.revision_number for r in revisions}
    cycles = session.execute(
        select(PlanCycle)
        .where(PlanCycle.tenant_id == plan.tenant_id, PlanCycle.care_plan_id == plan.id)
        .order_by(PlanCycle.scheduled_at, PlanCycle.id)
    ).scalars()
    return CarePlanOut(
        id=plan.id,
        version=plan.version,
        patient_id=plan.patient_id,
        condition_id=plan.condition_id,
        pathway=plan.pathway,
        title=plan.title,
        owner_id=plan.owner_id,
        status=plan.status,
        review_date=plan.review_date,
        current_revision=plan.current_revision,
        discontinuation_reason=plan.discontinuation_reason,
        revisions=[PlanRevisionOut.model_validate(r, from_attributes=True) for r in revisions],
        cycles=[
            PlanCycleOut(
                id=c.id,
                version=c.version,
                plan_revision_id=c.plan_revision_id,
                revision_number=numbers[c.plan_revision_id],
                scheduled_at=c.scheduled_at,
                status=c.status,
                completed_at=c.completed_at,
                completed_by_id=c.completed_by_id,
                outcome_note=c.outcome_note,
            )
            for c in cycles
        ],
    )


def chart_entries(
    session: Session, tenant_id: uuid.UUID, patient_ids: list[uuid.UUID], visible: Any
) -> tuple[list[ConditionOut], list[CarePlanSummary]]:
    conditions = [
        condition_out(c)
        for c in session.execute(
            select(Condition)
            .where(
                Condition.tenant_id == tenant_id,
                Condition.patient_id.in_(patient_ids),
                Condition.certainty != cp.Certainty.REFUTED.value,
            )
            .order_by(Condition.recorded_at.desc(), Condition.id)
        ).scalars()
        if visible(c.sensitivity)
    ]
    next_session = (
        select(PlanCycle.care_plan_id, func.min(PlanCycle.scheduled_at).label("next"))
        .where(PlanCycle.tenant_id == tenant_id, PlanCycle.status.in_(PENDING))
        .group_by(PlanCycle.care_plan_id)
        .subquery()
    )
    plans = [
        CarePlanSummary(
            id=p.id,
            pathway=p.pathway,
            title=p.title,
            owner_id=p.owner_id,
            status=p.status,
            review_date=p.review_date,
            current_revision=p.current_revision,
            next_session=nxt,
        )
        for p, nxt in session.execute(
            select(CarePlan, next_session.c.next)
            .outerjoin(next_session, next_session.c.care_plan_id == CarePlan.id)
            .where(CarePlan.tenant_id == tenant_id, CarePlan.patient_id.in_(patient_ids))
            .order_by(CarePlan.recorded_at.desc(), CarePlan.id)
        ).all()
        if visible(p.sensitivity)
    ]
    return conditions, plans


class CarePlans:
    def __init__(
        self, write_path: WritePath, factory: sessionmaker[Session], policy: PolicyEngine
    ) -> None:
        self.wp = write_path
        self.factory = factory
        self.policy = policy

    def _patient_of(self, ctx: RequestContext, model: Any, id_: uuid.UUID) -> uuid.UUID | None:
        """Care plan work is bound to a care relationship, so the write path
        needs the patient first; an unknown record gives none (not found)."""
        with self.factory() as session:
            return session.execute(
                select(model.patient_id).where(model.tenant_id == ctx.tenant_id, model.id == id_)
            ).scalar_one_or_none()

    # -- conditions --------------------------------------------------------------------

    def record_condition(
        self, ctx: RequestContext, key: str | None, patient_id: uuid.UUID, cmd: RecordCondition
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            patient = u.get(Patient, patient_id)
            row = Condition(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                version=1,
                recorded_at=u.ctx.now,
                author_id=u.ctx.principal.practitioner_id,
                patient_id=patient.id,
                code_system=cmd.code_system,
                code=cmd.code,
                display=cmd.display,
                certainty=cmd.certainty.value,
                onset_date=cmd.onset_date,
                register_code=cmd.register_code.value if cmd.register_code else None,
            )
            u.session.add(row)
            u.session.flush()
            decision = u.authorize("condition:record", patient_id=patient.id)
            event = u.emit(
                EventType.CONDITION_RECORDED,
                "condition",
                row.id,
                1,
                u.ctx.now,
                {
                    "condition_id": str(row.id),
                    "patient_id": str(patient.id),
                    "code_system": row.code_system,
                    "code": row.code,
                    "register": row.register_code,
                },
            )
            u.audit(
                decision,
                "condition.record",
                "condition",
                row.id,
                patient_id=patient.id,
                event_id=event,
            )
            return CommandResult(201, condition_out(row).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="condition.record",
            capability="condition:record",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"patient_id": str(patient_id)},
            handler=handle,
            patient_id=patient_id,
        )

    # -- plans -------------------------------------------------------------------------

    def _revise(
        self, u: Unit, plan: CarePlan, spec: RevisionIn, number: int, reason: str
    ) -> PlanRevision:
        times = _domain(lambda: cp.schedule(spec.effective_from, spec.interval_days, spec.sessions))
        rev = PlanRevision(
            tenant_id=u.ctx.tenant_id,
            id=new_id(),
            version=1,
            recorded_at=u.ctx.now,
            author_id=u.ctx.principal.practitioner_id,
            care_plan_id=plan.id,
            revision_number=number,
            effective_from=spec.effective_from,
            session_type=spec.session_type.value,
            interval_days=spec.interval_days,
            instructions=spec.instructions,
            protocol_code=spec.protocol_code,
            authorised_by_id=u.ctx.principal.practitioner_id,
            reason=reason,
        )
        u.session.add(rev)
        u.session.flush()
        plan.current_revision = number
        # Days on which the patient's other plans already have a session.
        busy = {
            at.date()
            for at in u.session.execute(
                select(PlanCycle.scheduled_at).where(
                    PlanCycle.tenant_id == u.ctx.tenant_id,
                    PlanCycle.patient_id == plan.patient_id,
                    PlanCycle.care_plan_id != plan.id,
                    PlanCycle.status.in_(PENDING),
                )
            ).scalars()
        }
        for at in times:
            held = cp.clashes(at.date(), busy)
            cycle = PlanCycle(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                version=1,
                recorded_at=u.ctx.now,
                effective_at=at,
                care_plan_id=plan.id,
                plan_revision_id=rev.id,
                patient_id=plan.patient_id,
                scheduled_at=at,
                status=(cp.CycleStatus.HELD if held else cp.CycleStatus.SCHEDULED).value,
            )
            u.session.add(cycle)
            u.session.flush()
            if held:
                open_task(
                    u,
                    subject="Resolve a clash between two care plan sessions",
                    task_type=TaskType.GENERAL,
                    due_at=min(at, u.ctx.now + timedelta(days=1)),
                    assignee=plan.owner_id,
                    patient_id=plan.patient_id,
                    source=("plan_cycle", cycle.id),
                )
        u.emit(
            EventType.CARE_PLAN_REVISED,
            "care_plan",
            plan.id,
            plan.version,
            spec.effective_from,
            {
                "care_plan_id": str(plan.id),
                "patient_id": str(plan.patient_id),
                "revision": number,
                "pathway": plan.pathway,
                "sessions": len(times),
            },
        )
        return rev

    def create(self, ctx: RequestContext, key: str | None, cmd: CreatePlan) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            _domain(lambda: cp.check_future(cmd.revision.effective_from, u.ctx.now))
            patient = u.get(Patient, cmd.patient_id)
            if (
                cmd.condition_id is not None
                and u.get(Condition, cmd.condition_id).patient_id != patient.id
            ):
                raise Unprocessable(
                    "the condition is another patient's", code="condition_patient_mismatch"
                )
            u.get(Practitioner, cmd.owner_id)
            plan = CarePlan(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                version=1,
                recorded_at=u.ctx.now,
                author_id=u.ctx.principal.practitioner_id,
                patient_id=patient.id,
                condition_id=cmd.condition_id,
                pathway=cmd.pathway.value,
                title=cmd.title,
                owner_id=cmd.owner_id,
                status=cp.PlanStatus.ACTIVE.value,
                review_date=cmd.review_date,
                current_revision=0,
            )
            u.session.add(plan)
            u.session.flush()
            self._revise(u, plan, cmd.revision, 1, "initial plan")
            decision = u.authorize("careplan:manage", patient_id=patient.id)
            u.audit(decision, "care_plan.create", "care_plan", plan.id, patient_id=patient.id)
            return CommandResult(201, plan_out(u.session, plan).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="care_plan.create",
            capability="careplan:manage",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json"),
            handler=handle,
            patient_id=cmd.patient_id,
        )

    def revise(
        self,
        ctx: RequestContext,
        key: str | None,
        plan_id: uuid.UUID,
        expected: int | None,
        cmd: RevisePlan,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            plan = u.get(CarePlan, plan_id, lock=True)
            u.check_version(plan.version, expected)
            _domain(lambda: cp.check_active(cp.PlanStatus(plan.status)))
            _domain(lambda: cp.check_future(cmd.effective_from, u.ctx.now))
            number = plan.current_revision + 1
            # Sessions from the effective time on follow the new revision; earlier
            # ones, and every completed one, keep the revision they were planned under.
            for cycle in u.session.execute(
                select(PlanCycle)
                .where(
                    PlanCycle.tenant_id == u.ctx.tenant_id,
                    PlanCycle.care_plan_id == plan.id,
                    PlanCycle.status.in_(PENDING),
                    PlanCycle.scheduled_at >= cmd.effective_from,
                )
                .with_for_update()
            ).scalars():
                cycle.status = cp.CycleStatus.CANCELLED.value
                cycle.outcome_note = f"replaced by revision {number}"
                cycle.version += 1
                close_source_tasks(
                    u, ("plan_cycle", cycle.id), TaskStatus.CANCELLED, "session replaced"
                )
            plan.version += 1
            self._revise(u, plan, cmd, number, cmd.reason)
            decision = u.authorize("careplan:manage", patient_id=plan.patient_id)
            u.audit(decision, "care_plan.revise", "care_plan", plan.id, patient_id=plan.patient_id)
            return CommandResult(200, plan_out(u.session, plan).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="care_plan.revise",
            capability="careplan:manage",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"plan_id": str(plan_id), "v": expected},
            handler=handle,
            patient_id=self._patient_of(ctx, CarePlan, plan_id),
            resource=("care_plan", plan_id),
        )

    def discontinue(
        self,
        ctx: RequestContext,
        key: str | None,
        plan_id: uuid.UUID,
        expected: int | None,
        cmd: DiscontinuePlan,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            plan = u.get(CarePlan, plan_id, lock=True)
            u.check_version(plan.version, expected)
            _domain(lambda: cp.check_active(cp.PlanStatus(plan.status)))
            plan.status, plan.discontinuation_reason = cp.PlanStatus.DISCONTINUED.value, cmd.reason
            plan.version += 1
            for cycle in u.session.execute(
                select(PlanCycle)
                .where(
                    PlanCycle.tenant_id == u.ctx.tenant_id,
                    PlanCycle.care_plan_id == plan.id,
                    PlanCycle.status.in_(PENDING),
                )
                .with_for_update()
            ).scalars():
                cycle.status, cycle.outcome_note = cp.CycleStatus.CANCELLED.value, "plan ended"
                cycle.version += 1
                close_source_tasks(u, ("plan_cycle", cycle.id), TaskStatus.CANCELLED, "plan ended")
            decision = u.authorize("careplan:manage", patient_id=plan.patient_id)
            event = u.emit(
                EventType.CARE_PLAN_DISCONTINUED,
                "care_plan",
                plan.id,
                plan.version,
                u.ctx.now,
                {"care_plan_id": str(plan.id), "patient_id": str(plan.patient_id)},
            )
            u.audit(
                decision,
                "care_plan.discontinue",
                "care_plan",
                plan.id,
                patient_id=plan.patient_id,
                event_id=event,
            )
            return CommandResult(200, plan_out(u.session, plan).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="care_plan.discontinue",
            capability="careplan:manage",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"plan_id": str(plan_id), "v": expected},
            handler=handle,
            patient_id=self._patient_of(ctx, CarePlan, plan_id),
            resource=("care_plan", plan_id),
        )

    # -- sessions ----------------------------------------------------------------------

    def complete_cycle(
        self,
        ctx: RequestContext,
        key: str | None,
        cycle_id: uuid.UUID,
        expected: int | None,
        cmd: CompleteCycle,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            cycle = u.get(PlanCycle, cycle_id, lock=True)
            u.check_version(cycle.version, expected)
            cycle.status = _domain(
                lambda: cp.move_cycle(cp.CycleStatus(cycle.status), cp.CycleStatus.COMPLETED)
            ).value
            cycle.completed_at = u.ctx.now
            cycle.completed_by_id = u.ctx.principal.practitioner_id
            cycle.outcome_note = cmd.note
            cycle.version += 1
            plan = u.get(CarePlan, cycle.care_plan_id)
            decision = u.authorize("careplan:deliver", patient_id=cycle.patient_id)
            event = u.emit(
                EventType.PLAN_CYCLE_COMPLETED,
                "plan_cycle",
                cycle.id,
                cycle.version,
                u.ctx.now,
                {
                    "plan_cycle_id": str(cycle.id),
                    "care_plan_id": str(plan.id),
                    "plan_revision_id": str(cycle.plan_revision_id),
                    "patient_id": str(cycle.patient_id),
                },
            )
            u.audit(
                decision,
                "plan_cycle.complete",
                "plan_cycle",
                cycle.id,
                patient_id=cycle.patient_id,
                event_id=event,
            )
            return CommandResult(200, plan_out(u.session, plan).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="plan_cycle.complete",
            capability="careplan:deliver",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"cycle_id": str(cycle_id), "v": expected},
            handler=handle,
            patient_id=self._patient_of(ctx, PlanCycle, cycle_id),
            resource=("plan_cycle", cycle_id),
        )

    def release_cycle(
        self,
        ctx: RequestContext,
        key: str | None,
        cycle_id: uuid.UUID,
        expected: int | None,
        cmd: ReleaseCycle,
    ) -> CommandResult:
        """The plan owner, the named reviewer, resolves a held clash."""

        def handle(u: Unit) -> CommandResult:
            cycle = u.get(PlanCycle, cycle_id, lock=True)
            plan = u.get(CarePlan, cycle.care_plan_id)
            if plan.owner_id != u.ctx.principal.practitioner_id:
                u.deny("not_plan_owner", patient_id=cycle.patient_id)
            u.check_version(cycle.version, expected)
            cycle.status = _domain(
                lambda: cp.move_cycle(cp.CycleStatus(cycle.status), cp.CycleStatus.SCHEDULED)
            ).value
            cycle.outcome_note = cmd.note
            cycle.version += 1
            close_source_tasks(u, ("plan_cycle", cycle.id), TaskStatus.COMPLETED, cmd.note)
            decision = u.authorize("careplan:manage", patient_id=cycle.patient_id)
            u.audit(
                decision,
                "plan_cycle.release",
                "plan_cycle",
                cycle.id,
                patient_id=cycle.patient_id,
            )
            return CommandResult(200, plan_out(u.session, plan).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="plan_cycle.release",
            capability="careplan:manage",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"cycle_id": str(cycle_id), "v": expected},
            handler=handle,
            patient_id=self._patient_of(ctx, PlanCycle, cycle_id),
            resource=("plan_cycle", cycle_id),
        )

    def get(self, ctx: RequestContext, plan_id: uuid.UUID) -> CarePlanOut:
        patient_id = self._patient_of(ctx, CarePlan, plan_id)
        if patient_id is None:
            raise NotFound("not found")

        def read(session: Session, decision: Decision) -> CarePlanOut:
            plan = session.execute(
                select(CarePlan).where(CarePlan.tenant_id == ctx.tenant_id, CarePlan.id == plan_id)
            ).scalar_one()
            return plan_out(session, plan)

        return read_path(
            self.factory,
            self.policy,
            ctx,
            capability="chart:read",
            action="care_plan.read",
            resource_type="care_plan",
            patient_id=patient_id,
            reader=read,
        )
