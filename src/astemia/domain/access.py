"""Emergency access (CEDA SEC-04, WF02 step 4). Pure rules: no I/O.

Pilot limits: one patient, read-only, 30 minutes, no bulk export, a recorded
purpose, an immediate privacy alert and review within one working day.
"""

from datetime import datetime, timedelta
from enum import StrEnum

from astemia.domain.common import InvalidTransition

GRANT_DURATION = timedelta(minutes=30)
# The only capability an emergency grant can satisfy: reading the chart.
GRANT_SCOPE = "chart:read"


class ReviewOutcome(StrEnum):
    APPROPRIATE = "appropriate"
    INAPPROPRIATE = "inappropriate"


class StepUp(StrEnum):
    """Step-up authentication at the moment of the request (SEC-02). The pilot
    identity provider cannot perform it yet, so grants record that it was not
    available rather than claiming it happened."""

    NOT_AVAILABLE = "not_available"


def expires_at(granted_at: datetime) -> datetime:
    return granted_at + GRANT_DURATION


def review_due(granted_at: datetime) -> datetime:
    """One working day later. A deadline that falls at a weekend moves to the
    same time on the Monday."""
    due = granted_at + timedelta(days=1)
    while due.weekday() >= 5:  # Saturday, Sunday
        due += timedelta(days=1)
    return due


def is_live(starts_at: datetime, ends_at: datetime, at: datetime) -> bool:
    """Checked again at every read: an expired grant denies the next one."""
    return starts_at <= at < ends_at


def check_reviewable(reviewed: bool) -> None:
    if reviewed:
        raise InvalidTransition("this grant has already been reviewed", code="already_reviewed")
