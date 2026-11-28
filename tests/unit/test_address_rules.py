"""Every patient is registered with a full address and postcode (CEDA revision 1.8)."""

import pytest

from astemia.domain.common import InvariantViolation
from astemia.domain.identity import check_address, normalise_postcode


def test_postcodes_are_checked_for_their_country() -> None:
    assert normalise_postcode("NG", " 101241 ") == "101241"
    assert normalise_postcode("GB", "sw1a1aa") == "SW1A 1AA"
    assert normalise_postcode("GB", "M1  1ae") == "M1 1AE"
    assert normalise_postcode("GH", "GA-184-5671") == "GA-184-5671"
    for country, bad in (
        ("NG", "10124"),
        ("NG", "ABC123"),
        ("GB", "12345"),
        ("GH", "!"),
        ("GB", "M1"),
    ):
        with pytest.raises(InvariantViolation) as e:
            normalise_postcode(country, bad)
        assert e.value.code == "bad_postcode"


def test_an_address_is_required_unless_the_patient_is_unidentified() -> None:
    full = {"country": "NG", "state": "Lagos", "lga": "Eti-Osa"}
    check_address(temporary=False, has_address=True, **full)
    check_address(temporary=True, has_address=False, country=None, state=None, lga=None)
    check_address(temporary=False, has_address=True, country="GB", state=None, lga=None)
    with pytest.raises(InvariantViolation) as e:
        check_address(temporary=False, has_address=False, country=None, state=None, lga=None)
    assert e.value.code == "address_required"
    for missing in ({"state": None}, {"lga": None}):
        with pytest.raises(InvariantViolation) as e:
            check_address(temporary=False, has_address=True, **{**full, **missing})
        assert e.value.code == "address_incomplete"
