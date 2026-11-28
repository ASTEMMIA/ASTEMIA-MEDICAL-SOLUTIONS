"""Daybook rules (UG03): pure domain."""

from datetime import UTC, datetime, timedelta

import pytest

from astemia.domain import tasks as tk
from astemia.domain.common import InvalidTransition, InvariantViolation

DUE = datetime(2026, 11, 23, 9, tzinfo=UTC)
S = tk.TaskStatus


def test_task_lifecycle() -> None:
    assert tk.move(S.OPEN, S.ACKNOWLEDGED) is S.ACKNOWLEDGED
    assert tk.move(S.ACKNOWLEDGED, S.COMPLETED) is S.COMPLETED
    assert tk.move(S.OPEN, S.CANCELLED) is S.CANCELLED
    for current, target in ((S.COMPLETED, S.OPEN), (S.CANCELLED, S.COMPLETED)):
        with pytest.raises(InvalidTransition):
            tk.move(current, target)
    tk.check_active(S.ACKNOWLEDGED)
    with pytest.raises(InvariantViolation) as e:
        tk.check_active(S.COMPLETED)
    assert e.value.code == "task_closed"


def test_one_owner_a_person_or_a_queue() -> None:
    tk.check_target("someone", None)
    tk.check_target(None, "nurse")
    for assignee, queue in (("someone", "nurse"), (None, None)):
        with pytest.raises(InvariantViolation) as e:
            tk.check_target(assignee, queue)
        assert e.value.code == "assignee_or_queue"


@pytest.mark.parametrize(
    ("after", "step"),
    [
        (timedelta(seconds=-1), 0),
        (timedelta(0), 1),
        (timedelta(hours=23, minutes=59), 1),
        (timedelta(hours=24), 2),
        (timedelta(hours=48), 3),
        (timedelta(days=30), 3),
    ],
)
def test_reminder_steps(after: timedelta, step: int) -> None:
    assert tk.reminder_step(DUE, DUE + after) == step


def test_overdue_means_active_and_past_due() -> None:
    assert tk.overdue(S.OPEN, DUE, DUE)
    assert not tk.overdue(S.OPEN, DUE, DUE - timedelta(seconds=1))
    assert not tk.overdue(S.COMPLETED, DUE, DUE + timedelta(days=1))
