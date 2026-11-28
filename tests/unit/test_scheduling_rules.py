"""Appointment and referral rules (UG01, HS04, HS05): pure domain."""

from datetime import UTC, datetime, timedelta

import pytest

from astemia.domain import scheduling as sch
from astemia.domain.common import InvalidTransition, InvariantViolation

NOW = datetime(2026, 11, 23, 9, tzinfo=UTC)
A, R = sch.AppointmentStatus, sch.ReferralStatus


def test_slot_runs_are_consecutive_and_bounded() -> None:
    assert sch.slot_run(NOW, 15, 3) == [
        (NOW, NOW + timedelta(minutes=15)),
        (NOW + timedelta(minutes=15), NOW + timedelta(minutes=30)),
        (NOW + timedelta(minutes=30), NOW + timedelta(minutes=45)),
    ]
    later = NOW + timedelta(days=1)
    sch.check_slot_run(later, 15, 1, NOW)
    for args, code in (
        ((NOW, 15, 1), "slot_in_past"),
        ((later, 4, 1), "bad_slot_length"),
        ((later, 241, 1), "bad_slot_length"),
        ((later, 15, 0), "bad_slot_count"),
        ((later, 15, sch.MAX_SLOTS_PER_RUN + 1), "bad_slot_count"),
    ):
        with pytest.raises(InvariantViolation) as e:
            sch.check_slot_run(*args, NOW)
        assert e.value.code == code


def test_holds_expire_on_the_server() -> None:
    expires = NOW + sch.HOLD_DURATION
    assert sch.hold_live(expires, False, NOW)
    assert not sch.hold_live(expires, False, expires)  # stale at the deadline
    assert not sch.hold_live(expires, True, NOW)  # used or cleared


@pytest.mark.parametrize("target", [A.ATTENDED, A.CANCELLED, A.NO_SHOW, A.RESCHEDULED])
def test_a_booked_appointment_ends_once(target: sch.AppointmentStatus) -> None:
    assert sch.move_appointment(A.BOOKED, target) is target
    with pytest.raises(InvalidTransition):
        sch.move_appointment(target, A.CANCELLED)


def test_only_a_remote_appointment_can_fail_to_connect() -> None:
    sch.check_outcome(sch.AttendanceOutcome.FAILED_CONNECTION, sch.Modality.VIDEO)
    sch.check_outcome(sch.AttendanceOutcome.ATTENDED, sch.Modality.IN_PERSON)
    with pytest.raises(InvariantViolation) as e:
        sch.check_outcome(sch.AttendanceOutcome.FAILED_CONNECTION, sch.Modality.HOME)
    assert e.value.code == "not_remote"


def test_referral_lifecycle() -> None:
    assert sch.move_referral(R.SUBMITTED, R.ACCEPTED) is R.ACCEPTED
    assert sch.move_referral(R.ACCEPTED, R.SCHEDULED) is R.SCHEDULED
    assert sch.move_referral(R.SCHEDULED, R.ACCEPTED) is R.ACCEPTED  # back to the list
    assert sch.move_referral(R.SCHEDULED, R.CLOSED) is R.CLOSED
    for current, target in ((R.SUBMITTED, R.SCHEDULED), (R.REJECTED, R.ACCEPTED)):
        with pytest.raises(InvalidTransition):
            sch.move_referral(current, target)
    sch.check_decision(R.ACCEPTED, None)
    with pytest.raises(InvariantViolation) as e:
        sch.check_decision(R.REJECTED, "")
    assert e.value.code == "reason_required"
