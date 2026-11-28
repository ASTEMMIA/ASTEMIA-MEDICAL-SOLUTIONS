"""Emergency access rules (SEC-04): pure domain."""

from datetime import UTC, datetime, timedelta

import pytest

from astemia.domain import access as acc
from astemia.domain.common import InvalidTransition


def at(day: int, hour: int = 10) -> datetime:
    return datetime(2026, 11, day, hour, tzinfo=UTC)  # 23 Nov 2026 is a Monday


def test_a_grant_lasts_thirty_minutes_and_reads_only_the_chart() -> None:
    assert acc.expires_at(at(23)) - at(23) == timedelta(minutes=30)
    assert acc.GRANT_SCOPE == "chart:read"


@pytest.mark.parametrize(
    ("granted", "due"),
    [
        (at(23), at(24)),  # Monday -> Tuesday
        (at(26), at(27)),  # Thursday -> Friday
        (at(27), at(30)),  # Friday -> Monday
        (at(28), at(30)),  # Saturday -> Monday
        (at(29), at(30)),  # Sunday -> Monday
    ],
)
def test_review_is_due_within_one_working_day(granted: datetime, due: datetime) -> None:
    assert acc.review_due(granted) == due


def test_a_grant_is_live_from_its_start_until_just_before_expiry() -> None:
    start = at(23)
    end = acc.expires_at(start)
    assert not acc.is_live(start, end, start - timedelta(seconds=1))
    assert acc.is_live(start, end, start)
    assert acc.is_live(start, end, end - timedelta(microseconds=1))
    assert not acc.is_live(start, end, end)  # the first read after expiry is refused


def test_a_grant_is_reviewed_once() -> None:
    acc.check_reviewable(False)
    with pytest.raises(InvalidTransition) as e:
        acc.check_reviewable(True)
    assert e.value.code == "already_reviewed"
