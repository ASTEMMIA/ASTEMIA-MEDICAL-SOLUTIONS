"""Daybook tasks (CEDA UG03: Task, Assignment, Notification).

A task is owned by a named practitioner or by a queue, which is a role: every
member holding that role sees it, and acknowledging claims it. Reassignment
keeps the original deadline and is added to the ownership history, so an
overdue task stays overdue and visible to its new owner. Team supervisors see
every task. Reminders are sent by the worker in astemia.workers.reminders.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import Practitioner, Task, TaskAssignment
from astemia.application.context import RequestContext
from astemia.application.errors import AccessDenied, Unprocessable
from astemia.application.policy import PolicyEngine
from astemia.application.schemas import (
    AssignmentOut,
    CancelTask,
    CompleteTask,
    CreateTask,
    ReassignTask,
    TaskOut,
)
from astemia.application.write_path import CommandResult, Unit, WritePath, audit_row
from astemia.domain import tasks as tk
from astemia.domain.common import DomainError, new_id
from astemia.domain.events import EventType


def _domain(fn: Any) -> Any:
    try:
        return fn()
    except DomainError as exc:
        raise Unprocessable(str(exc), code=exc.code) from None


def task_out(session: Session, row: Task, at: datetime) -> TaskOut:
    history = session.execute(
        select(TaskAssignment)
        .where(TaskAssignment.tenant_id == row.tenant_id, TaskAssignment.task_id == row.id)
        .order_by(TaskAssignment.recorded_at, TaskAssignment.id)
    ).scalars()
    return TaskOut(
        id=row.id,
        version=row.version,
        patient_id=row.patient_id,
        subject=row.subject,
        task_type=row.task_type,
        priority=row.priority,
        status=row.status,
        due_at=row.due_at,
        overdue=tk.overdue(tk.TaskStatus(row.status), row.due_at, at),
        assignee_id=row.assignee_id,
        queue=row.queue,
        origin_type=row.origin_type,
        origin_id=row.origin_id,
        escalation_step=row.escalation_step,
        created_by_id=row.author_id,
        acknowledged_at=row.acknowledged_at,
        completed_at=row.completed_at,
        completed_by_id=row.completed_by_id,
        outcome_note=row.outcome_note,
        history=[
            AssignmentOut(
                assignee_id=h.assignee_id,
                queue=h.queue,
                reason=h.reason,
                assigned_by_id=h.author_id,
                recorded_at=h.recorded_at,
            )
            for h in history
        ],
    )


def _assign(u: Unit, task: Task, assignee: uuid.UUID | None, queue: str | None, why: str) -> None:
    if assignee is not None:
        u.get(Practitioner, assignee)
    task.assignee_id, task.queue = assignee, queue
    u.session.add(
        TaskAssignment(
            tenant_id=u.ctx.tenant_id,
            id=new_id(),
            version=1,
            recorded_at=u.ctx.now,
            author_id=u.ctx.principal.practitioner_id,
            task_id=task.id,
            assignee_id=assignee,
            queue=queue,
            reason=why,
        )
    )
    u.emit(
        EventType.TASK_ASSIGNED,
        "task",
        task.id,
        task.version,
        u.ctx.now,
        {
            "task_id": str(task.id),
            "assignee_id": str(assignee) if assignee else None,
            "queue": queue,
            "due_at": task.due_at.isoformat(),
        },
    )


def open_task(
    u: Unit,
    *,
    subject: str,
    task_type: tk.TaskType,
    due_at: datetime,
    assignee: uuid.UUID | None = None,
    queue: str | None = None,
    patient_id: uuid.UUID | None = None,
    priority: tk.Priority = tk.Priority.ROUTINE,
    source: tuple[str, uuid.UUID] | None = None,
) -> Task:
    """Open a task, from a request or from another workflow (a filed document,
    a discharge). The subject is the only text and never holds clinical detail."""
    _domain(lambda: tk.check_target(assignee, queue))
    task = Task(
        tenant_id=u.ctx.tenant_id,
        id=new_id(),
        version=1,
        recorded_at=u.ctx.now,
        author_id=u.ctx.principal.practitioner_id,
        patient_id=patient_id,
        subject=subject,
        task_type=task_type.value,
        priority=priority.value,
        status=tk.TaskStatus.OPEN.value,
        due_at=due_at,
        origin_type=source[0] if source else None,
        origin_id=source[1] if source else None,
        escalation_step=0,
    )
    u.session.add(task)
    u.session.flush()
    _assign(u, task, assignee, queue, "created")
    return task


def close_source_tasks(
    u: Unit, source: tuple[str, uuid.UUID], status: tk.TaskStatus, note: str
) -> None:
    """Complete or cancel the open tasks another workflow raised, when that
    workflow's own step is done (a document reviewed or re-filed)."""
    for task in u.session.execute(
        select(Task)
        .where(
            Task.tenant_id == u.ctx.tenant_id,
            Task.origin_type == source[0],
            Task.origin_id == source[1],
            Task.status.in_([s.value for s in tk.ACTIVE]),
        )
        .with_for_update()
    ).scalars():
        task.status = status.value
        task.completed_at, task.completed_by_id = u.ctx.now, u.ctx.principal.practitioner_id
        task.outcome_note = note
        task.version += 1


class Daybook:
    def __init__(
        self, write_path: WritePath, factory: sessionmaker[Session], policy: PolicyEngine
    ) -> None:
        self.wp = write_path
        self.factory = factory
        self.policy = policy

    @staticmethod
    def _mine(u: Unit, task: Task) -> bool:
        return task.assignee_id == u.ctx.principal.practitioner_id or (
            task.queue is not None and task.queue in u.ctx.principal.roles
        )

    def _supervisor(self, u: Unit) -> bool:
        return self.policy.decide(u.session, u.ctx, "task:supervise").allowed

    def _load(self, u: Unit, task_id: uuid.UUID, expected: int | None) -> Task:
        """Only the owner, a member of the owning queue or a supervisor acts on a
        task; anyone else is told it does not exist."""
        task = u.get(Task, task_id, lock=True)
        if not (self._mine(u, task) or self._supervisor(u)):
            u.deny("not_task_owner", conceal=True, patient_id=task.patient_id)
        u.check_version(task.version, expected)
        return task

    def _run(
        self,
        ctx: RequestContext,
        key: str | None,
        operation: str,
        task_id: uuid.UUID | None,
        payload: dict[str, Any],
        handle: Any,
    ) -> CommandResult:
        return self.wp.run(
            ctx,
            operation=operation,
            capability="task:assign",
            idempotency_key=key,
            payload=payload | ({"task_id": str(task_id)} if task_id else {}),
            handler=handle,
            resource=("task", task_id) if task_id else None,
        )

    def _done(self, u: Unit, task: Task, action: str, status: int = 200) -> CommandResult:
        decision = u.authorize("task:assign")
        u.audit(decision, action, "task", task.id, patient_id=task.patient_id)
        return CommandResult(status, task_out(u.session, task, u.ctx.now).model_dump(mode="json"))

    def create(self, ctx: RequestContext, key: str | None, cmd: CreateTask) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            task = open_task(
                u,
                subject=cmd.subject,
                task_type=cmd.task_type,
                due_at=cmd.due_at,
                assignee=cmd.assignee_id,
                queue=cmd.queue,
                patient_id=cmd.patient_id,
                priority=cmd.priority,
            )
            return self._done(u, task, "task.create", 201)

        return self._run(ctx, key, "task.create", None, cmd.model_dump(mode="json"), handle)

    def acknowledge(
        self, ctx: RequestContext, key: str | None, task_id: uuid.UUID, expected: int | None
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            task = self._load(u, task_id, expected)
            task.status = _domain(
                lambda: tk.move(tk.TaskStatus(task.status), tk.TaskStatus.ACKNOWLEDGED)
            ).value
            task.acknowledged_at = u.ctx.now
            task.version += 1
            if task.assignee_id is None:  # acknowledging a queue task claims it
                _assign(u, task, u.ctx.principal.practitioner_id, None, "claimed from queue")
            return self._done(u, task, "task.acknowledge")

        return self._run(ctx, key, "task.acknowledge", task_id, {"v": expected}, handle)

    def complete(
        self,
        ctx: RequestContext,
        key: str | None,
        task_id: uuid.UUID,
        expected: int | None,
        cmd: CompleteTask,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            task = self._load(u, task_id, expected)
            task.status = _domain(
                lambda: tk.move(tk.TaskStatus(task.status), tk.TaskStatus.COMPLETED)
            ).value
            task.completed_at, task.completed_by_id = u.ctx.now, u.ctx.principal.practitioner_id
            task.outcome_note = cmd.note
            task.version += 1
            u.emit(
                EventType.TASK_COMPLETED,
                "task",
                task.id,
                task.version,
                u.ctx.now,
                {"task_id": str(task.id), "completed_by_id": str(task.completed_by_id)},
            )
            return self._done(u, task, "task.complete")

        return self._run(
            ctx,
            key,
            "task.complete",
            task_id,
            cmd.model_dump(mode="json") | {"v": expected},
            handle,
        )

    def cancel(
        self,
        ctx: RequestContext,
        key: str | None,
        task_id: uuid.UUID,
        expected: int | None,
        cmd: CancelTask,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            task = self._load(u, task_id, expected)
            task.status = _domain(
                lambda: tk.move(tk.TaskStatus(task.status), tk.TaskStatus.CANCELLED)
            ).value
            task.completed_at, task.completed_by_id = u.ctx.now, u.ctx.principal.practitioner_id
            task.outcome_note = cmd.reason
            task.version += 1
            return self._done(u, task, "task.cancel")

        return self._run(
            ctx, key, "task.cancel", task_id, cmd.model_dump(mode="json") | {"v": expected}, handle
        )

    def reassign(
        self,
        ctx: RequestContext,
        key: str | None,
        task_id: uuid.UUID,
        expected: int | None,
        cmd: ReassignTask,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            task = self._load(u, task_id, expected)
            _domain(lambda: tk.check_active(tk.TaskStatus(task.status)))
            _domain(lambda: tk.check_target(cmd.assignee_id, cmd.queue))
            # The new owner acknowledges afresh; the deadline does not move.
            task.status, task.acknowledged_at = tk.TaskStatus.OPEN.value, None
            task.version += 1
            _assign(u, task, cmd.assignee_id, cmd.queue, cmd.reason)
            return self._done(u, task, "task.reassign")

        return self._run(
            ctx,
            key,
            "task.reassign",
            task_id,
            cmd.model_dump(mode="json") | {"v": expected},
            handle,
        )

    def worklist(self, ctx: RequestContext, *, view: str, limit: int) -> list[TaskOut]:
        """mine: assigned to me or my queues. all: every active task, overdue
        first (supervisors only)."""
        with self.factory() as session:
            capability = "task:supervise" if view == "all" else "task:assign"
            decision = self.policy.decide(session, ctx, capability)
            session.add(
                audit_row(
                    ctx,
                    decision,
                    f"task.worklist.{view}",
                    "task",
                    None,
                    None,
                    "success" if decision.allowed else "denied",
                )
            )
            session.commit()
            if not decision.allowed:
                raise AccessDenied(decision.reason, code=decision.reason)
            stmt = select(Task).where(
                Task.tenant_id == ctx.tenant_id,
                Task.status.in_([s.value for s in tk.ACTIVE]),
            )
            if view == "mine":
                stmt = stmt.where(
                    or_(
                        Task.assignee_id == ctx.principal.practitioner_id,
                        Task.queue.in_(ctx.principal.roles),
                    )
                )
            rows = session.execute(stmt.order_by(Task.due_at, Task.id).limit(limit)).scalars()
            return [task_out(session, t, ctx.now) for t in rows]
