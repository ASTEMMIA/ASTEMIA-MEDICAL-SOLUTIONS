"""Theatre sessions and cases (CEDA HS03, WF05 step 2). Pure rules.

A session is a block of time in one theatre. A case books part of a session
against an open encounter; the session cannot be overbooked, and a session
whose theatre is unavailable takes no case. The safety checklist (sign in and
time out before the operation starts, sign out before it ends) is recorded
step by step; a missing step needs an authorised override with a reason.
Cancelling a scheduled case gives its time back. Recovery hands the patient
to a named, accountable recipient.
"""

from datetime import datetime
from enum import StrEnum

from astemia.domain.common import InvariantViolation, transition


class SessionStatus(StrEnum):
    OPEN = "open"
    UNAVAILABLE = "unavailable"  # equipment, staffing or estates


class CaseStatus(StrEnum):
    SCHEDULED = "scheduled"
    IN_THEATRE = "in_theatre"
    COMPLETED = "completed"  # in recovery
    HANDED_OVER = "handed_over"
    CANCELLED = "cancelled"


class Laterality(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    BILATERAL = "bilateral"
    NOT_APPLICABLE = "not_applicable"


class ChecklistStep(StrEnum):
    SIGN_IN = "sign_in"
    TIME_OUT = "time_out"
    SIGN_OUT = "sign_out"


BEFORE_START = (ChecklistStep.SIGN_IN, ChecklistStep.TIME_OUT)
BEFORE_END = (ChecklistStep.SIGN_OUT,)

# Each step belongs to one stage of the case.
STEP_STAGE: dict[ChecklistStep, CaseStatus] = {
    ChecklistStep.SIGN_IN: CaseStatus.SCHEDULED,
    ChecklistStep.TIME_OUT: CaseStatus.SCHEDULED,
    ChecklistStep.SIGN_OUT: CaseStatus.IN_THEATRE,
}

_ALLOWED: dict[CaseStatus, frozenset[CaseStatus]] = {
    CaseStatus.SCHEDULED: frozenset({CaseStatus.IN_THEATRE, CaseStatus.CANCELLED}),
    CaseStatus.IN_THEATRE: frozenset({CaseStatus.COMPLETED}),
    CaseStatus.COMPLETED: frozenset({CaseStatus.HANDED_OVER}),
}


def move(current: CaseStatus, target: CaseStatus) -> CaseStatus:
    return transition(current, target, _ALLOWED, "theatre case")


def check_session_times(starts_at: datetime, ends_at: datetime) -> int:
    """The session's length in minutes; it must end after it starts, on the same day."""
    minutes = int((ends_at - starts_at).total_seconds() // 60)
    if minutes <= 0 or minutes > 24 * 60:
        raise InvariantViolation(
            "a session ends after it starts and lasts at most a day", code="bad_session_times"
        )
    return minutes


def check_booking(
    status: SessionStatus, theatre_active: bool, capacity: int, booked: int, minutes: int
) -> None:
    """A case fits only in an open session of an active theatre with time left."""
    if status is not SessionStatus.OPEN or not theatre_active:
        raise InvariantViolation("that theatre session is unavailable", code="theatre_unavailable")
    if booked + minutes > capacity:
        raise InvariantViolation(
            f"the session has {capacity - booked} minutes left; the case needs {minutes}",
            code="session_full",
        )


def missing_steps(
    done: set[ChecklistStep], needed: tuple[ChecklistStep, ...], override_reason: str | None
) -> list[ChecklistStep]:
    """Steps not yet recorded. Without an override reason, any gap refuses."""
    missing = [s for s in needed if s not in done]
    if missing and not override_reason:
        raise InvariantViolation(
            "complete the safety checklist first ("
            + ", ".join(s.value for s in missing)
            + "), or record an override with a reason",
            code="checklist_incomplete",
        )
    return missing


def check_step(step: ChecklistStep, status: CaseStatus, done: set[ChecklistStep]) -> None:
    if step in done:
        raise InvariantViolation(f"{step.value} is already recorded", code="step_recorded")
    if STEP_STAGE[step] is not status:
        raise InvariantViolation(
            f"{step.value} is recorded while the case is {STEP_STAGE[step].value}",
            code="step_out_of_order",
        )
