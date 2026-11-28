"""Address changes (CEDA revision 1.8)."""

import pytest

from astemia.domain.common import InvariantViolation
from astemia.domain.identity import AddressChangeReason as R
from astemia.domain.identity import check_address_change


def test_address_change_rules() -> None:
    check_address_change("active", R.MOVED, same_as_current=False)
    check_address_change("closed", R.CORRECTION, same_as_current=False)
    check_address_change("temporary", R.IDENTIFIED, same_as_current=False)
    for status, reason, same, code in (
        ("merged", R.MOVED, False, "patient_merged"),
        ("active", R.IDENTIFIED, False, "not_temporary"),
        ("active", R.CORRECTION, True, "address_unchanged"),
    ):
        with pytest.raises(InvariantViolation) as e:
            check_address_change(status, reason, same_as_current=same)
        assert e.value.code == code
