"""Appointments and referrals (CEDA UG01, HS04, HS05; SA-05). Pure rules.

A slot is available, held or booked. Its state is derived from its holds and
appointments rather than stored, so it can never disagree with them; the data
layer allows one live hold and one booked appointment per slot.
"""

from datetime import datetime, timedelta
from enum import StrEnum

from astemia.domain.common import InvariantViolation, transition

HOLD_DURATION = timedelta(minutes=5)
MAX_SLOTS_PER_RUN = 50


class SlotType(StrEnum):
    NEW = "new"
    FOLLOW_UP = "follow_up"
    URGENT = "urgent"


class Modality(StrEnum):
    IN_PERSON = "in_person"
    VIDEO = "video"
    PHONE = "phone"
    HOME = "home"


REMOTE = frozenset({Modality.VIDEO, Modality.PHONE})


class SlotStatus(StrEnum):
    AVAILABLE = "available"
    HELD = "held"
    BOOKED = "booked"


class AppointmentStatus(StrEnum):
    BOOKED = "booked"
    ATTENDED = "attended"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"
    FAILED_CONNECTION = "failed_connection"
    RESCHEDULED = "rescheduled"


_APPOINTMENT: dict[AppointmentStatus, frozenset[AppointmentStatus]] = {
    AppointmentStatus.BOOKED: frozenset(
        {
            AppointmentStatus.ATTENDED,
            AppointmentStatus.CANCELLED,
            AppointmentStatus.NO_SHOW,
            AppointmentStatus.FAILED_CONNECTION,
            AppointmentStatus.RESCHEDULED,
        }
    ),
}


class AttendanceOutcome(StrEnum):
    ATTENDED = "attended"
    NO_SHOW = "no_show"
    # A video or phone call that never connected: recorded apart from care,
    # and the patient can be rebooked (HS04).
    FAILED_CONNECTION = "failed_connection"


def move_appointment(current: AppointmentStatus, target: AppointmentStatus) -> AppointmentStatus:
    return transition(current, target, _APPOINTMENT, "appointment")


def check_outcome(outcome: AttendanceOutcome, modality: Modality) -> None:
    if outcome is AttendanceOutcome.FAILED_CONNECTION and modality not in REMOTE:
        raise InvariantViolation(
            "only a video or phone appointment can fail to connect", code="not_remote"
        )


def check_slot_run(starts_at: datetime, minutes: int, count: int, now: datetime) -> None:
    if starts_at <= now:
        raise InvariantViolation("slots must start in the future", code="slot_in_past")
    if not 5 <= minutes <= 240:
        raise InvariantViolation("a slot lasts 5 to 240 minutes", code="bad_slot_length")
    if not 1 <= count <= MAX_SLOTS_PER_RUN:
        raise InvariantViolation(
            f"create 1 to {MAX_SLOTS_PER_RUN} slots at a time", code="bad_slot_count"
        )


def slot_run(starts_at: datetime, minutes: int, count: int) -> list[tuple[datetime, datetime]]:
    """Consecutive slots of equal length."""
    step = timedelta(minutes=minutes)
    return [(starts_at + i * step, starts_at + (i + 1) * step) for i in range(count)]


def hold_live(expires_at: datetime, released: bool, at: datetime) -> bool:
    """Holds expire on the server: a hold past its time is stale whatever the
    client believes."""
    return not released and at < expires_at


class ReferralPriority(StrEnum):
    ROUTINE = "routine"
    URGENT = "urgent"


class ReferralStatus(StrEnum):
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SCHEDULED = "scheduled"
    CLOSED = "closed"


_REFERRAL: dict[ReferralStatus, frozenset[ReferralStatus]] = {
    ReferralStatus.SUBMITTED: frozenset({ReferralStatus.ACCEPTED, ReferralStatus.REJECTED}),
    ReferralStatus.ACCEPTED: frozenset({ReferralStatus.SCHEDULED}),
    # A cancelled or failed appointment returns the referral to the waiting list.
    ReferralStatus.SCHEDULED: frozenset({ReferralStatus.CLOSED, ReferralStatus.ACCEPTED}),
}


def move_referral(current: ReferralStatus, target: ReferralStatus) -> ReferralStatus:
    return transition(current, target, _REFERRAL, "referral")


def check_decision(decision: ReferralStatus, reason: str | None) -> None:
    if decision is ReferralStatus.REJECTED and not reason:
        raise InvariantViolation("a rejected referral needs a reason", code="reason_required")


class CareLevel(StrEnum):
    """The level of care an organisation provides (its organisation_type)."""

    PRIMARY = "primary_health_centre"
    GENERAL = "general_hospital"
    TEACHING = "teaching_hospital"
    SPECIALIST = "specialist_hospital"


def care_level(organisation_type: str) -> CareLevel | None:
    try:
        return CareLevel(organisation_type)
    except ValueError:
        return None


class RecordType(StrEnum):
    """What a referral's records package carries (CEDA revision 1.5)."""

    ENCOUNTER = "encounter"
    ORDER = "service_request"
    REPORT = "diagnostic_report"


def check_facilities(referring: object, receiving: object) -> None:
    if referring == receiving:
        raise InvariantViolation("a referral goes to a different facility", code="same_facility")
