"""Mental health safeguards (CEDA HS13, B11; ICRS 5.5.9-5.5.15). Pure rules.

Fair treatment is made checkable: every restrictive intervention is logged
and independently reviewed, the patient's legal status is always known, with
its history and expiry, and anyone can raise a concern that a safeguarding lead
must answer. Nobody reviews their own conduct.
"""

from collections.abc import Collection
from datetime import datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from astemia.domain.common import InvalidTransition, InvariantViolation, transition

# Pilot site time: out-of-hours access is judged in local time.
LOCAL = ZoneInfo("Africa/Lagos")
WORKING_HOURS = (7, 20)  # 07:00 to 20:00
EXPIRY_WARNING = timedelta(hours=72)
CONCERN_RESPONSE = timedelta(days=5)


class InterventionType(StrEnum):
    PHYSICAL_RESTRAINT = "physical_restraint"
    MECHANICAL_RESTRAINT = "mechanical_restraint"
    SECLUSION = "seclusion"
    RAPID_TRANQUILLISATION = "rapid_tranquillisation"


class ReviewOutcome(StrEnum):
    APPROPRIATE = "appropriate"
    CONCERNS = "concerns"  # practice to change; follow-up recorded in the note
    ESCALATED = "escalated"  # referred on, for example to a safeguarding investigation


def check_intervention(started_at: datetime, ended_at: datetime | None, now: datetime) -> None:
    if started_at > now:
        raise InvariantViolation("an intervention cannot start in the future", code="bad_time")
    if ended_at is not None and not started_at < ended_at <= now:
        raise InvariantViolation(
            "an intervention ends after it starts and not in the future", code="bad_time"
        )


def check_independent(reviewer: object, involved: Collection[object]) -> None:
    """Nobody reviews an intervention they authorised or took part in, or a
    concern raised about them."""
    if reviewer in involved:
        raise InvariantViolation(
            "you were involved, so another reviewer must look at this",
            code="conflict_of_interest",
        )


def check_reviewable(reviewed: bool) -> None:
    if reviewed:
        raise InvalidTransition("this has already been reviewed", code="already_reviewed")


class LegalStatus(StrEnum):
    """The patient's legal status under mental health law (ICRS 5.5.9)."""

    INFORMAL = "informal"
    EMERGENCY_HOLDING = "emergency_holding"
    DETAINED_ASSESSMENT = "detained_assessment"
    DETAINED_TREATMENT = "detained_treatment"
    COMMUNITY_TREATMENT = "community_treatment"


DETAINED = frozenset(
    {
        LegalStatus.EMERGENCY_HOLDING,
        LegalStatus.DETAINED_ASSESSMENT,
        LegalStatus.DETAINED_TREATMENT,
        LegalStatus.COMMUNITY_TREATMENT,
    }
)


def check_legal_status(
    status: LegalStatus,
    legal_basis: str | None,
    valid_from: datetime,
    valid_until: datetime | None,
    now: datetime,
) -> None:
    if valid_from > now:
        raise InvariantViolation("a legal status starts now or in the past", code="bad_time")
    if status in DETAINED:
        if not legal_basis or valid_until is None:
            raise InvariantViolation(
                "a compulsory power needs its legal basis and an expiry",
                code="legal_basis_required",
            )
        if valid_until <= valid_from:
            raise InvariantViolation("the power must expire after it starts", code="bad_time")
    elif valid_until is not None:
        raise InvariantViolation("informal status does not expire", code="bad_time")


def lapsed(status: LegalStatus, valid_until: datetime | None, at: datetime) -> bool:
    """A compulsory power past its expiry with nothing recorded to replace it."""
    return status in DETAINED and valid_until is not None and at >= valid_until


def expiring(valid_until: datetime | None, at: datetime) -> bool:
    return valid_until is not None and at < valid_until <= at + EXPIRY_WARNING


class Flag(StrEnum):
    """Why an intervention or an access needs a closer look."""

    INFORMAL_PATIENT = "informal_patient"  # restricted while not detained
    DETENTION_LAPSED = "detention_lapsed"  # restricted under an expired power
    NO_LEGAL_STATUS = "no_legal_status"
    INJURY = "injury"
    DENIED = "denied"
    EMERGENCY_ACCESS = "emergency_access"
    OUT_OF_HOURS = "out_of_hours"


def intervention_flags(
    status: LegalStatus | None, valid_until: datetime | None, injury: bool, at: datetime
) -> list[Flag]:
    flags: list[Flag] = []
    if status is None:
        flags.append(Flag.NO_LEGAL_STATUS)
    elif status is LegalStatus.INFORMAL:
        flags.append(Flag.INFORMAL_PATIENT)
    elif lapsed(status, valid_until, at):
        flags.append(Flag.DETENTION_LAPSED)
    if injury:
        flags.append(Flag.INJURY)
    return flags


def access_flags(outcome: str, reason_code: str | None, at: datetime) -> list[Flag]:
    flags: list[Flag] = []
    if outcome == "denied":
        flags.append(Flag.DENIED)
    if reason_code == "emergency_grant":
        flags.append(Flag.EMERGENCY_ACCESS)
    start, end = WORKING_HOURS
    if not start <= at.astimezone(LOCAL).hour < end:
        flags.append(Flag.OUT_OF_HOURS)
    return flags


class RaisedBy(StrEnum):
    PATIENT = "patient"
    FAMILY = "family"
    ADVOCATE = "advocate"
    STAFF = "staff"


class ConcernCategory(StrEnum):
    RESTRICTIVE_PRACTICE = "restrictive_practice"
    NEGLECT = "neglect"
    DIGNITY = "dignity"
    MEDICATION = "medication"
    ABUSE = "abuse"
    OTHER = "other"


class ConcernStatus(StrEnum):
    OPEN = "open"
    UPHELD = "upheld"
    NOT_UPHELD = "not_upheld"


_CONCERN: dict[ConcernStatus, frozenset[ConcernStatus]] = {
    ConcernStatus.OPEN: frozenset({ConcernStatus.UPHELD, ConcernStatus.NOT_UPHELD}),
}


def close_concern(current: ConcernStatus, outcome: ConcernStatus) -> ConcernStatus:
    return transition(current, outcome, _CONCERN, "concern")
