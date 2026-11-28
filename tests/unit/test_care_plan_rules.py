"""Care plan rules (HS12, SA-08): pure domain."""

from datetime import UTC, date, datetime, timedelta

import pytest

from astemia.domain import careplans as cp
from astemia.domain.common import InvalidTransition, InvariantViolation

START = datetime(2026, 12, 1, 8, tzinfo=UTC)
C = cp.CycleStatus


def test_sessions_are_scheduled_at_the_interval() -> None:
    assert cp.schedule(START, 2, 3) == [START, START + timedelta(2), START + timedelta(4)]
    for interval, sessions, code in (
        (0, 1, "bad_interval"),
        (366, 1, "bad_interval"),
        (1, 0, "bad_session_count"),
        (1, 53, "bad_session_count"),
    ):
        with pytest.raises(InvariantViolation) as e:
            cp.schedule(START, interval, sessions)
        assert e.value.code == code


def test_revisions_apply_from_now_on_and_only_to_active_plans() -> None:
    cp.check_future(START, START)
    with pytest.raises(InvariantViolation) as e:
        cp.check_future(START - timedelta(seconds=1), START)
    assert e.value.code == "bad_effective_time"
    cp.check_active(cp.PlanStatus.ACTIVE)
    with pytest.raises(InvalidTransition) as e2:
        cp.check_active(cp.PlanStatus.DISCONTINUED)
    assert e2.value.code == "plan_not_active"


def test_session_lifecycle_and_clashes() -> None:
    assert cp.move_cycle(C.SCHEDULED, C.COMPLETED) is C.COMPLETED
    assert cp.move_cycle(C.HELD, C.SCHEDULED) is C.SCHEDULED
    for current, target in ((C.HELD, C.COMPLETED), (C.COMPLETED, C.CANCELLED)):
        with pytest.raises(InvalidTransition):
            cp.move_cycle(current, target)
    assert cp.clashes(date(2026, 12, 1), {date(2026, 12, 1)})
    assert not cp.clashes(date(2026, 12, 2), {date(2026, 12, 1)})
