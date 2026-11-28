"""Discharge (CEDA HS05, WF06 step 3, ST08). Pure rules.

A discharge summary is drafted, then signed off with the discharge, which
closes the encounter once. Every outstanding item leaves with a named owner:
pending results go to their result owner, open result reviews to their
assignee, and anything else to the owner or queue the coordinator names. A
missing owner blocks the discharge unless a supervised exception is recorded,
which sends the item to the team supervisors with the reason.
"""

from enum import StrEnum

from astemia.domain.common import InvariantViolation

SUPERVISOR_QUEUE = "team_supervisor"


class Disposition(StrEnum):
    HOME = "home"
    HOME_WITH_SUPPORT = "home_with_support"
    TRANSFERRED = "transferred"
    SELF_DISCHARGE = "self_discharge"  # against medical advice
    DIED = "died"


class OutstandingKind(StrEnum):
    MEDICATION = "medication"
    REFERRAL = "referral"
    FOLLOW_UP = "follow_up"


class SummaryStatus(StrEnum):
    DRAFT = "draft"
    SIGNED = "signed"


def route_item[T](
    owner: T | None, queue: str | None, exception_reason: str | None
) -> tuple[T | None, str | None]:
    """Who an outstanding item goes to. Exactly one named owner or queue; with
    neither, only a recorded supervised exception lets the discharge proceed."""
    if owner is not None and queue is not None:
        raise InvariantViolation("name an owner or a queue, not both", code="assignee_or_queue")
    if owner is None and queue is None:
        if not exception_reason:
            raise InvariantViolation(
                "every outstanding item needs a named owner, or a supervised exception "
                "with a reason",
                code="owner_required",
            )
        return None, SUPERVISOR_QUEUE
    return owner, queue


def check_draft(status: SummaryStatus | None) -> None:
    if status is None:
        raise InvariantViolation(
            "draft the discharge summary before signing off the discharge",
            code="summary_required",
        )
