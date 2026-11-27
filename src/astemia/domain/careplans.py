"""Conditions and care plans (CEDA HS12; SA-08 CarePlan, PlanRevision,
PlanCycle; Condition). Pure rules.

A care plan follows an approved pathway and is made of revisions. Each
revision schedules sessions (a dialysis session, a chemotherapy cycle, a
review). A new revision applies only from its effective time onwards: the
sessions still to come move to it, and every completed session keeps the
exact revision it was delivered under. A session that clashes with another
plan's session for the same patient on the same day is held for a named
reviewer.
"""

from datetime import date, datetime, timedelta
from enum import StrEnum

from astemia.domain.common import InvalidTransition, InvariantViolation, transition

MAX_SESSIONS = 52


class Certainty(StrEnum):
    PROVISIONAL = "provisional"
    CONFIRMED = "confirmed"
    REFUTED = "refuted"


class Pathway(StrEnum):
    DIABETES = "diabetes"
    RENAL = "renal"
    CARDIOVASCULAR = "cardiovascular"
    ONCOLOGY = "oncology"
    OLDER_PERSON = "older_person"


class SessionType(StrEnum):
    DIALYSIS = "dialysis"
    TREATMENT_CYCLE = "treatment_cycle"
    MONITORING = "monitoring"
    REVIEW = "review"


class PlanStatus(StrEnum):
    ACTIVE = "active"
    DISCONTINUED = "discontinued"


class CycleStatus(StrEnum):
    SCHEDULED = "scheduled"
    HELD = "held"  # a schedule conflict waiting for its reviewer
    COMPLETED = "completed"
    CANCELLED = "cancelled"


_CYCLE: dict[CycleStatus, frozenset[CycleStatus]] = {
    CycleStatus.SCHEDULED: frozenset({CycleStatus.COMPLETED, CycleStatus.CANCELLED}),
    CycleStatus.HELD: frozenset({CycleStatus.SCHEDULED, CycleStatus.CANCELLED}),
}

PENDING = frozenset({CycleStatus.SCHEDULED, CycleStatus.HELD})


def move_cycle(current: CycleStatus, target: CycleStatus) -> CycleStatus:
    return transition(current, target, _CYCLE, "session")


def schedule(start: datetime, interval_days: int, sessions: int) -> list[datetime]:
    if not 1 <= interval_days <= 365:
        raise InvariantViolation("sessions are 1 to 365 days apart", code="bad_interval")
    if not 1 <= sessions <= MAX_SESSIONS:
        raise InvariantViolation(
            f"schedule 1 to {MAX_SESSIONS} sessions at a time", code="bad_session_count"
        )
    step = timedelta(days=interval_days)
    return [start + i * step for i in range(sessions)]


def check_future(effective_from: datetime, now: datetime) -> None:
    """Revisions change instructions from now on, never the past."""
    if effective_from < now:
        raise InvariantViolation(
            "a revision applies from now or later, not to past sessions", code="bad_effective_time"
        )


def check_active(status: PlanStatus) -> None:
    if status is not PlanStatus.ACTIVE:
        raise InvalidTransition(f"the plan is {status}", code="plan_not_active")


def clashes(day: date, other_days: set[date]) -> bool:
    return day in other_days
