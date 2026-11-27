"""Domain, type and configuration rules not covered elsewhere."""

from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import MetaData

from astemia.adapters.db.staging import ErdEntity, build_staging_tables
from astemia.adapters.db.types import UTCDateTime
from astemia.adapters.identity.tokens import issue_dev_token
from astemia.catalogue import SCHEMA_CURRENT, directory_rows, template_rows
from astemia.config import Settings, get_settings
from astemia.domain import diagnostics as dx
from astemia.domain.common import InvariantViolation


@pytest.mark.parametrize(
    "kwargs",
    [
        {"value_type": dx.ValueType.STRING},
        {"value_type": dx.ValueType.CODED},
        {
            "value_type": dx.ValueType.QUANTITY,
            "quantity": Decimal(1),
            "unit": "g/L",
            "ref_low": Decimal(5),
            "ref_high": Decimal(2),
        },
    ],
)
def test_invalid_observation_values(kwargs: dict) -> None:  # type: ignore[type-arg]
    with pytest.raises(InvariantViolation):
        dx.ObservationValue(**kwargs)


def test_flags_need_a_quantity_and_a_range() -> None:
    assert dx.ObservationValue(dx.ValueType.STRING, text="positive").flag() is None
    assert (
        dx.ObservationValue(dx.ValueType.QUANTITY, quantity=Decimal(4), unit="g/L").flag() is None
    )


def test_a_report_is_not_cancelled_through_release() -> None:
    with pytest.raises(InvariantViolation):
        dx.release_status(None, dx.ReportStatus.CANCELLED)


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        UTCDateTime().process_bind_param(datetime(2026, 1, 1), None)


def test_erd_fields_that_clash_with_lineage_columns_are_prefixed() -> None:
    entity = ErdEntity("clash", ("Clash",), ("test.json",), ("batch_id", "Name"))
    table = build_staging_tables(MetaData(), [entity])["stg_clash"]
    assert {"batch_id", "src_batch_id", "name"} <= set(table.columns.keys())


def test_directory_rows_cover_both_directories() -> None:
    rows = directory_rows(SCHEMA_CURRENT)
    assert {r["directory"] for r in rows} == {"directory_a", "directory_b"}
    assert len(rows) == 281 + 170


def test_seed_rows_keep_the_migration_0004_form_by_default() -> None:
    """Migration 0004 calls these with no arguments; 0009 renames afterwards."""
    assert {r["directory"] for r in directory_rows()} == {"kch", "nhsggc"}
    groups, _ = template_rows()
    assert all("kch_positions" in g for g in groups)
    current, _ = template_rows(SCHEMA_CURRENT)
    assert [g["directory_a_positions"] for g in current] == [g["kch_positions"] for g in groups]


def test_settings_are_cached() -> None:
    assert get_settings() is get_settings()


def test_development_tokens_are_refused_in_production() -> None:
    import uuid

    with pytest.raises(RuntimeError, match="disabled in production"):
        issue_dev_token(Settings(environment="production"), "x@y", uuid.uuid7())


def test_asgi_entry_point_builds_the_app() -> None:
    from astemia.api import main

    assert main.app.title.startswith("ASTEMIA")
