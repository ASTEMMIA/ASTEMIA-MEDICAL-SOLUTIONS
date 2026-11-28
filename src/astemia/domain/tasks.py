"""Daybook tasks (CEDA UG03: Task, Assignment, Notification). Pure rules.

A task belongs to a named owner or to a queue (a role), with a due time. It
moves from open to acknowledged to completed or cancelled. Reassignment keeps
the original deadline and adds to the ownership history. Overdue reminders are
deduplicated by task, policy and escalation step, so a retry or a reassignment
never sends the same reminder twice.
"""

from datetime import datetime, timedelta
from enum import StrEnum

from astemia.domain.common import InvariantViolation, transition

ESCALATION_INTERVAL = timedelta(hours=24)
MAX_STEP = 3
SUPERVISOR_STEP = 2  # from this step a reminder also goes to the supervisors' queue


class TaskType(StrEnum):
    RECALL = "recall"
    REFERRAL_FOLLOW_UP = "referral_follow_up"
    RESULT_FOLLOW_UP = "result_follow_up"
    DOCUMENT_REVIEW = "document_review"
    DISCHARGE_FOLLOW_UP = "discharge_follow_up"
    PLAN_REVIEW = "plan_review"
    HANDOVER = "handover"
    GENERAL = "general"


class Priority(StrEnum):
    ROUTINE = "routine"
    URGENT = "urgent"


class TaskStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


ACTIVE = frozenset({TaskStatus.OPEN, TaskStatus.ACKNOWLEDGED})

_TASK: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.OPEN: frozenset(
        {TaskStatus.ACKNOWLEDGED, TaskStatus.COMPLETED, TaskStatus.CANCELLED}
    ),
    TaskStatus.ACKNOWLEDGED: frozenset({TaskStatus.COMPLETED, TaskStatus.CANCELLED}),
}


def move(current: TaskStatus, target: TaskStatus) -> TaskStatus:
    return transition(current, target, _TASK, "task")


def check_target(assignee: object | None, queue: str | None) -> None:
    """A task has exactly one owner: a named person or a queue."""
    if (assignee is None) == (queue is None):
        raise InvariantViolation(
            "give either a named assignee or a queue", code="assignee_or_queue"
        )


def check_active(status: TaskStatus) -> None:
    if status not in ACTIVE:
        raise InvariantViolation(f"the task is {status}", code="task_closed")


def reminder_step(due_at: datetime, at: datetime) -> int:
    """0 before the deadline; 1 once overdue, then one more step for each
    further day, up to MAX_STEP."""
    if at < due_at:
        return 0
    return min(1 + int((at - due_at) / ESCALATION_INTERVAL), MAX_STEP)


def overdue(status: TaskStatus, due_at: datetime, at: datetime) -> bool:
    return status in ACTIVE and at >= due_at
