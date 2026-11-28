"""Discharge (CEDA HS05, WF06 step 3, ST08).

A clinician or nurse in the patient's care drafts the discharge summary. A
clinician signs the discharge off in one transaction: the summary is signed,
the encounter is finished with its disposition, and every outstanding item
gets a Daybook task with a named owner. Orders still waiting for a result go
to their result owner; result reviews still open go to their assignee; items
the coordinator lists go to the owner or queue they name, or, under a
supervised exception, to the team supervisors with the reason. A second
discharge of the same encounter is refused.
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import (
    DiagnosticReport,
    DischargeSummary,
    Encounter,
    ResultReview,
    ServiceRequest,
    Task,
)
from astemia.application.context import RequestContext
from astemia.application.daybook import open_task
from astemia.application.errors import Conflict, Unprocessable
from astemia.application.policy import PolicyEngine
from astemia.application.schemas import Discharge, DischargeSummaryOut, DraftDischarge
from astemia.application.write_path import CommandResult, Unit, WritePath
from astemia.domain import discharge as dg
from astemia.domain import encounter as enc
from astemia.domain.common import DomainError, new_id
from astemia.domain.diagnostics import ReviewState, ServiceRequestStatus
from astemia.domain.events import EventType
from astemia.domain.tasks import Priority, TaskType

RESULT_FOLLOW_UP = timedelta(days=2)


def _domain(fn: Any) -> Any:
    try:
        return fn()
    except DomainError as exc:
        raise Unprocessable(str(exc), code=exc.code) from None


def summary_out(session: Session, row: DischargeSummary) -> DischargeSummaryOut:
    tasks = session.execute(
        select(Task.id)
        .where(
            Task.tenant_id == row.tenant_id,
            Task.origin_type == "discharge_summary",
            Task.origin_id == row.id,
        )
        .order_by(Task.recorded_at, Task.id)
    ).scalars()
    return DischargeSummaryOut(
        id=row.id,
        version=row.version,
        encounter_id=row.encounter_id,
        patient_id=row.patient_id,
        status=row.status,
        disposition=row.disposition,
        summary=row.summary,
        follow_up=row.follow_up,
        author_id=row.author_id,
        discharged_at=row.discharged_at,
        signed_at=row.signed_at,
        signed_by_id=row.signed_by_id,
        tasks=list(tasks),
    )


def signed_discharges(
    session: Session, tenant_id: uuid.UUID, patient_ids: list[uuid.UUID], visible: Any
) -> list[DischargeSummaryOut]:
    rows = session.execute(
        select(DischargeSummary)
        .where(
            DischargeSummary.tenant_id == tenant_id,
            DischargeSummary.patient_id.in_(patient_ids),
            DischargeSummary.status == dg.SummaryStatus.SIGNED.value,
        )
        .order_by(DischargeSummary.discharged_at.desc(), DischargeSummary.id)
    ).scalars()
    return [summary_out(session, r) for r in rows if visible(r.sensitivity)]


def _summary(u: Unit, encounter_id: uuid.UUID) -> DischargeSummary | None:
    return u.session.execute(
        select(DischargeSummary)
        .where(
            DischargeSummary.tenant_id == u.ctx.tenant_id,
            DischargeSummary.encounter_id == encounter_id,
        )
        .with_for_update()
    ).scalar_one_or_none()


def _pending_results(u: Unit, encounter: Encounter) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """(order or review id, accountable owner) for every result the patient
    leaves without: orders not yet resulted, and reviews not yet acknowledged."""
    tid = u.ctx.tenant_id
    waiting = [
        (o.id, o.result_owner_id)
        for o in u.session.execute(
            select(ServiceRequest).where(
                ServiceRequest.tenant_id == tid,
                ServiceRequest.encounter_id == encounter.id,
                ServiceRequest.status == ServiceRequestStatus.ACTIVE.value,
            )
        ).scalars()
    ]
    unreviewed = [
        (r.id, r.assignee_id)
        for r in u.session.execute(
            select(ResultReview)
            .join(
                DiagnosticReport,
                (DiagnosticReport.tenant_id == ResultReview.tenant_id)
                & (DiagnosticReport.id == ResultReview.report_id),
            )
            .join(
                ServiceRequest,
                (ServiceRequest.tenant_id == DiagnosticReport.tenant_id)
                & (ServiceRequest.id == DiagnosticReport.service_request_id),
            )
            .where(
                ResultReview.tenant_id == tid,
                ServiceRequest.encounter_id == encounter.id,
                ResultReview.state.in_([ReviewState.OPEN.value, ReviewState.ESCALATED.value]),
            )
        ).scalars()
    ]
    return waiting + unreviewed


class Discharges:
    def __init__(
        self, write_path: WritePath, factory: sessionmaker[Session], policy: PolicyEngine
    ) -> None:
        self.wp = write_path
        self.factory = factory
        self.policy = policy

    def _patient_of(self, ctx: RequestContext, encounter_id: uuid.UUID) -> uuid.UUID | None:
        with self.factory() as session:
            return session.execute(
                select(Encounter.patient_id).where(
                    Encounter.tenant_id == ctx.tenant_id, Encounter.id == encounter_id
                )
            ).scalar_one_or_none()

    def draft(
        self,
        ctx: RequestContext,
        key: str | None,
        encounter_id: uuid.UUID,
        expected: int | None,
        cmd: DraftDischarge,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            encounter = u.get(Encounter, encounter_id, lock=True)
            existing = _summary(u, encounter.id)
            if existing is not None:
                if existing.status == dg.SummaryStatus.SIGNED:
                    raise Conflict(
                        "this encounter is already discharged", code="already_discharged"
                    )
                u.check_version(existing.version, expected)
                existing.disposition, existing.summary = cmd.disposition.value, cmd.summary
                existing.follow_up = cmd.follow_up
                existing.version += 1
                row, status = existing, 200
            else:
                row = DischargeSummary(
                    tenant_id=u.ctx.tenant_id,
                    id=new_id(),
                    version=1,
                    recorded_at=u.ctx.now,
                    author_id=u.ctx.principal.practitioner_id,
                    sensitivity=encounter.sensitivity,
                    encounter_id=encounter.id,
                    patient_id=encounter.patient_id,
                    status=dg.SummaryStatus.DRAFT.value,
                    disposition=cmd.disposition.value,
                    summary=cmd.summary,
                    follow_up=cmd.follow_up,
                )
                u.session.add(row)
                status = 201
            u.session.flush()
            decision = u.authorize("note:write", patient_id=encounter.patient_id)
            u.audit(
                decision,
                "discharge_summary.draft",
                "discharge_summary",
                row.id,
                patient_id=encounter.patient_id,
            )
            return CommandResult(status, summary_out(u.session, row).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="discharge_summary.draft",
            capability="note:write",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json")
            | {"encounter_id": str(encounter_id), "v": expected},
            handler=handle,
            patient_id=self._patient_of(ctx, encounter_id),
        )

    def discharge(
        self,
        ctx: RequestContext,
        key: str | None,
        encounter_id: uuid.UUID,
        expected: int | None,
        cmd: Discharge,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            encounter = u.get(Encounter, encounter_id, lock=True)
            u.check_version(encounter.version, expected)
            if cmd.discharged_at > u.ctx.now or cmd.discharged_at < encounter.period_start:
                raise Unprocessable(
                    "the discharge time must be after admission and not in the future",
                    code="bad_discharge_time",
                )
            summary = _summary(u, encounter.id)
            _domain(lambda: dg.check_draft(dg.SummaryStatus(summary.status) if summary else None))
            assert summary is not None
            if summary.status == dg.SummaryStatus.SIGNED:
                raise Conflict("this encounter is already discharged", code="already_discharged")
            routes = [
                _domain(lambda i=i: dg.route_item(i.owner_id, i.queue, i.exception_reason))
                for i in cmd.outstanding
            ]
            encounter.state = _domain(
                lambda: enc.move(enc.EncounterState(encounter.state), enc.EncounterState.FINISHED)
            ).value
            encounter.period_end = cmd.discharged_at
            encounter.disposition = summary.disposition
            encounter.version += 1
            summary.status = dg.SummaryStatus.SIGNED.value
            summary.discharged_at = cmd.discharged_at
            summary.signed_at, summary.signed_by_id = u.ctx.now, u.ctx.principal.practitioner_id
            summary.version += 1
            origin = ("discharge_summary", summary.id)
            for _, owner in _pending_results(u, encounter):
                open_task(
                    u,
                    subject="Follow up a result still pending at discharge",
                    task_type=TaskType.RESULT_FOLLOW_UP,
                    due_at=u.ctx.now + RESULT_FOLLOW_UP,
                    assignee=owner,
                    patient_id=encounter.patient_id,
                    priority=Priority.URGENT,
                    source=origin,
                )
            for item, (owner, queue) in zip(cmd.outstanding, routes, strict=True):
                supervised = item.owner_id is None and item.queue is None
                subject = f"No owner: {item.description}"[:200] if supervised else item.description
                open_task(
                    u,
                    subject=subject,
                    task_type=TaskType.DISCHARGE_FOLLOW_UP,
                    due_at=item.due_at,
                    assignee=owner,
                    queue=queue,
                    patient_id=encounter.patient_id,
                    source=origin,
                )
            u.session.flush()
            decision = u.authorize("discharge:sign", patient_id=encounter.patient_id)
            event = u.emit(
                EventType.ENCOUNTER_DISCHARGED,
                "encounter",
                encounter.id,
                encounter.version,
                cmd.discharged_at,
                {
                    "encounter_id": str(encounter.id),
                    "patient_id": str(encounter.patient_id),
                    "disposition": encounter.disposition,
                    "discharge_summary_id": str(summary.id),
                },
            )
            u.audit(
                decision,
                "encounter.discharge",
                "encounter",
                encounter.id,
                patient_id=encounter.patient_id,
                event_id=event,
            )
            return CommandResult(200, summary_out(u.session, summary).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="encounter.discharge",
            capability="discharge:sign",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json")
            | {"encounter_id": str(encounter_id), "v": expected},
            handler=handle,
            patient_id=self._patient_of(ctx, encounter_id),
            resource=("encounter", encounter_id),
        )
