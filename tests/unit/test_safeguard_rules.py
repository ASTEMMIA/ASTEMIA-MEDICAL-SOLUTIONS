"""Mental health safeguard rules (HS13, ICRS 5.5.9): pure domain."""

from datetime import UTC, datetime, timedelta

import pytest

from astemia.domain import safeguards as sg
from astemia.domain.common import InvalidTransition, InvariantViolation

NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)  # 13:00 in Lagos
L = sg.LegalStatus


def code(fn: object) -> str:
    with pytest.raises((InvariantViolation, InvalidTransition)) as e:
        fn()  # type: ignore[operator]
    return e.value.code


def test_intervention_times() -> None:
    sg.check_intervention(NOW - timedelta(hours=1), None, NOW)
    sg.check_intervention(NOW - timedelta(hours=1), NOW, NOW)
    assert code(lambda: sg.check_intervention(NOW + timedelta(minutes=1), None, NOW)) == "bad_time"
    assert code(lambda: sg.check_intervention(NOW, NOW, NOW)) == "bad_time"
    assert (
        code(lambda: sg.check_intervention(NOW - timedelta(hours=1), NOW + timedelta(1), NOW))
        == "bad_time"
    )


def test_nobody_reviews_their_own_conduct() -> None:
    sg.check_independent("lead", {"nurse", None})
    assert code(lambda: sg.check_independent("lead", ["lead"])) == "conflict_of_interest"
    sg.check_reviewable(False)
    assert code(lambda: sg.check_reviewable(True)) == "already_reviewed"


def test_legal_status_rules() -> None:
    until = NOW + timedelta(days=28)
    sg.check_legal_status(L.DETAINED_TREATMENT, "MHA s.3", NOW, until, NOW)
    sg.check_legal_status(L.INFORMAL, None, NOW, None, NOW)
    cases = [
        ((L.DETAINED_ASSESSMENT, None, NOW, until), "legal_basis_required"),
        ((L.EMERGENCY_HOLDING, "s.136", NOW, None), "legal_basis_required"),
        ((L.DETAINED_TREATMENT, "s.3", NOW, NOW), "bad_time"),
        ((L.INFORMAL, None, NOW, until), "bad_time"),
        ((L.INFORMAL, None, NOW + timedelta(hours=1), None), "bad_time"),
    ]
    for args, expected in cases:
        assert code(lambda args=args: sg.check_legal_status(*args, NOW)) == expected


def test_lapse_and_expiry_warning() -> None:
    soon, later = NOW + timedelta(hours=10), NOW + timedelta(days=10)
    assert sg.expiring(soon, NOW) and not sg.expiring(later, NOW) and not sg.expiring(None, NOW)
    assert not sg.expiring(NOW - timedelta(hours=1), NOW)  # already lapsed, not expiring
    assert sg.lapsed(L.DETAINED_TREATMENT, NOW, NOW)
    assert not sg.lapsed(L.DETAINED_TREATMENT, soon, NOW)
    assert not sg.lapsed(L.INFORMAL, None, NOW)


def test_intervention_flags() -> None:
    F = sg.Flag
    assert sg.intervention_flags(None, None, False, NOW) == [F.NO_LEGAL_STATUS]
    assert sg.intervention_flags(L.INFORMAL, None, True, NOW) == [F.INFORMAL_PATIENT, F.INJURY]
    assert sg.intervention_flags(L.DETAINED_TREATMENT, NOW, False, NOW) == [F.DETENTION_LAPSED]
    assert sg.intervention_flags(L.DETAINED_TREATMENT, NOW + timedelta(1), False, NOW) == []


@pytest.mark.parametrize(
    ("hour_utc", "out_of_hours"),
    [(5, True), (6, False), (18, False), (19, True), (22, True), (4, True)],
)
def test_access_flags_use_local_working_hours(hour_utc: int, out_of_hours: bool) -> None:
    at = NOW.replace(hour=hour_utc)  # Lagos is UTC+1: 06:00 UTC is 07:00 local
    assert (sg.Flag.OUT_OF_HOURS in sg.access_flags("success", None, at)) is out_of_hours


def test_access_flags_for_refusals_and_emergency_reads() -> None:
    assert sg.access_flags("denied", "no_care_relationship", NOW) == [sg.Flag.DENIED]
    assert sg.access_flags("success", "emergency_grant", NOW) == [sg.Flag.EMERGENCY_ACCESS]


def test_a_concern_closes_once() -> None:
    S = sg.ConcernStatus
    assert sg.close_concern(S.OPEN, S.UPHELD) is S.UPHELD
    with pytest.raises(InvalidTransition):
        sg.close_concern(S.UPHELD, S.NOT_UPHELD)
