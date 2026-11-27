from datetime import date
from decimal import Decimal

import pytest

from astemia.domain import diagnostics as dx
from astemia.domain import encounter as enc
from astemia.domain.common import EffectivePrecision, InvalidTransition, InvariantViolation
from astemia.domain.identity import validate_birth_date, validate_identifier


class TestIdentifiers:
    def test_nin_is_eleven_digits(self) -> None:
        assert validate_identifier("NG-NIN", "123 4567 8901") == "12345678901"

    @pytest.mark.parametrize("value", ["1234567890", "123456789012", "ABCDEFGHIJK"])
    def test_bad_nin_rejected(self, value: str) -> None:
        with pytest.raises(InvariantViolation):
            validate_identifier("NG-NIN", value)

    def test_nhs_issuer_no_longer_exists(self) -> None:
        with pytest.raises(InvariantViolation, match="unknown identifier issuer"):
            validate_identifier("UK-NHS", "9434765919")

    def test_medicare_number(self) -> None:
        assert validate_identifier("NG-MEDICARE", "med-00042") == "MED-00042"


def test_birth_date_rules() -> None:
    today = date(2026, 11, 23)
    validate_birth_date(date(1990, 1, 1), EffectivePrecision.YEAR, today)
    with pytest.raises(InvariantViolation):
        validate_birth_date(date(2027, 1, 1), EffectivePrecision.DAY, today)
    with pytest.raises(InvariantViolation):
        validate_birth_date(date(1990, 1, 1), EffectivePrecision.MINUTE, today)


def test_encounter_transitions() -> None:
    assert (
        enc.move(enc.EncounterState.IN_PROGRESS, enc.EncounterState.FINISHED)
        is enc.EncounterState.FINISHED
    )
    with pytest.raises(InvalidTransition):
        enc.move(enc.EncounterState.FINISHED, enc.EncounterState.IN_PROGRESS)


class TestResults:
    def test_quantity_needs_ucum_unit(self) -> None:
        with pytest.raises(InvariantViolation):
            dx.ObservationValue(dx.ValueType.QUANTITY, quantity=Decimal("4.1"))

    @pytest.mark.parametrize(
        ("value", "flag"),
        [("3.0", dx.Flag.LOW), ("4.5", dx.Flag.NORMAL), ("6.1", dx.Flag.HIGH)],
    )
    def test_flags_from_reference_range(self, value: str, flag: dx.Flag) -> None:
        v = dx.ObservationValue(
            dx.ValueType.QUANTITY,
            quantity=Decimal(value),
            unit="mmol/L",
            ref_low=Decimal("3.5"),
            ref_high=Decimal("5.3"),
        )
        assert v.flag() is flag

    def test_second_release_is_an_amendment(self) -> None:
        assert dx.release_status(None, dx.ReportStatus.FINAL) is dx.ReportStatus.FINAL
        assert (
            dx.release_status(dx.ReportStatus.FINAL, dx.ReportStatus.FINAL)
            is dx.ReportStatus.AMENDED
        )

    def test_acknowledged_review_cannot_reopen(self) -> None:
        with pytest.raises(InvalidTransition):
            dx.move_review(dx.ReviewState.ACKNOWLEDGED, dx.ReviewState.ACKNOWLEDGED)


class TestMedicareRetired:
    def test_medicare_cannot_be_a_current_identifier(self) -> None:
        from astemia.domain.identity import IdentifierType, check_issuer_allowed

        for kind in (IdentifierType.CURRENT, IdentifierType.TEMPORARY, IdentifierType.OLD_STYLE):
            with pytest.raises(InvariantViolation) as err:
                check_issuer_allowed("NG-MEDICARE", kind)
            assert err.value.code == "medicare_number_retired"

    def test_medicare_is_kept_as_a_previous_identifier_that_never_binds(self) -> None:
        from astemia.domain.identity import IdentifierType, binds_actively, check_issuer_allowed

        check_issuer_allowed("NG-MEDICARE", IdentifierType.PREVIOUS)
        assert binds_actively("NG-NIN") is True
        assert binds_actively("NG-MEDICARE") is False
