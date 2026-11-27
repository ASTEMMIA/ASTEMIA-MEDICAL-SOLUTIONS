"""Discharge rules (HS05, ST08): pure domain."""

import pytest

from astemia.domain import discharge as dg
from astemia.domain.common import InvariantViolation


def test_every_outstanding_item_has_one_owner_or_a_supervised_exception() -> None:
    assert dg.route_item("dr-one", None, None) == ("dr-one", None)
    assert dg.route_item(None, "nurse", None) == (None, "nurse")
    assert dg.route_item(None, None, "No district nurse covers the area") == (
        None,
        dg.SUPERVISOR_QUEUE,
    )
    for owner, queue, reason, code in (
        (None, None, None, "owner_required"),
        (None, None, "", "owner_required"),
        ("dr-one", "nurse", None, "assignee_or_queue"),
    ):
        with pytest.raises(InvariantViolation) as e:
            dg.route_item(owner, queue, reason)
        assert e.value.code == code


def test_a_discharge_needs_a_drafted_summary() -> None:
    dg.check_draft(dg.SummaryStatus.DRAFT)
    with pytest.raises(InvariantViolation) as e:
        dg.check_draft(None)
    assert e.value.code == "summary_required"
