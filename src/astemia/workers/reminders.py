"""Daybook reminders (CEDA UG03): one reminder per overdue task, policy and
escalation step, whoever owns the task when it is sent.

The unique key on task_notification is the guard: a retried or concurrent run,
or a run straight after a reassignment, finds the step already sent and skips
it. From the second step a reminder also goes to the team supervisors.
Delivery (message, SMS) reads the task.reminder events from the outbox.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import OutboxEvent, Task, TaskNotification
from astemia.domain import tasks as tk
from astemia.domain.events import SCHEMA_VERSION, EventType

POLICY = "overdue"
ACTOR = "system:reminders"


def _event(task: Task, step: int, now: datetime) -> OutboxEvent:
    kind = EventType.TASK_ESCALATED if step >= tk.SUPERVISOR_STEP else EventType.TASK_REMINDER
    return OutboxEvent(
        event_id=uuid.uuid7(),
        tenant_id=task.tenant_id,
        event_type=kind.value,
        schema_version=SCHEMA_VERSION[kind],
        aggregate_type="task",
        aggregate_id=task.id,
        aggregate_version=task.version,
        effective_at=now,
        recorded_at=now,
        actor_subject=ACTOR,
        source_system="astemia",
        correlation_id=uuid.uuid4().hex,
        payload={
            "task_id": str(task.id),
            "step": step,
            "assignee_id": str(task.assignee_id) if task.assignee_id else None,
            "queue": task.queue,
            "supervisors": step >= tk.SUPERVISOR_STEP,
            "due_at": task.due_at.isoformat(),
        },
        available_at=now,
    )


def send_reminders(factory: sessionmaker[Session], now: datetime | None = None) -> int:
    """Send the reminders now due. Returns how many were sent."""
    at = now or datetime.now(UTC)
    sent = 0
    with factory() as session, session.begin():
        overdue = session.execute(
            select(Task)
            .where(
                Task.status.in_([s.value for s in tk.ACTIVE]),
                Task.due_at <= at,
            )
            .order_by(Task.due_at)
            .with_for_update(skip_locked=True)
        ).scalars()
        for task in overdue:
            step = tk.reminder_step(task.due_at, at)
            try:
                with session.begin_nested():
                    session.add(
                        TaskNotification(
                            tenant_id=task.tenant_id,
                            id=uuid.uuid7(),
                            task_id=task.id,
                            policy=POLICY,
                            step=step,
                            recipient_id=task.assignee_id,
                            recipient_queue=task.queue,
                            created_at=at,
                        )
                    )
            except IntegrityError:
                continue  # this step was already sent
            task.escalation_step = step
            session.add(_event(task, step, at))
            sent += 1
    return sent
