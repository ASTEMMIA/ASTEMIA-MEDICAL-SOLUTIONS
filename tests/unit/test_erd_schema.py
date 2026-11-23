"""The schema built from the AMS ERDs: every entity lands somewhere, NHS is NIN."""

import pytest

from astemia.adapters.db import models
from astemia.adapters.db.legacy_names import nhs_to_nin
from astemia.adapters.db.staging import (
    WIDE_LIMIT,
    extract_dictionary_rows,
    load_erds,
    staging_table_name,
)


def test_every_erd_entity_is_staged_or_in_the_extract_dictionary() -> None:
    extracts = {e["code"] for e in extract_dictionary_rows()[0]}
    for entity in load_erds():
        if entity.wide:
            assert entity.key[:48] in extracts
        else:
            assert staging_table_name(entity) in models.STAGING_TABLES


def test_staging_tables_fit_innodb() -> None:
    for table in models.STAGING_TABLES.values():
        assert len(table.columns) <= WIDE_LIMIT + 11


def test_no_nhs_names_in_the_schema() -> None:
    names = [t.name for t in models.Base.metadata.tables.values()]
    names += [c.name for t in models.Base.metadata.tables.values() for c in t.columns]
    assert not [n for n in names if "nhs" in n.lower()]


def test_no_nhs_labels_in_the_extract_dictionary() -> None:
    _, fields = extract_dictionary_rows()
    assert not [f for f in fields if "NHS" in f["label"].upper()]
    assert any("NHS" in f["source_label"].upper() for f in fields)  # lineage kept


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("nhs_number", "nin"),
        ("old_style_nhs_number", "old_style_nin"),
        ("NHS_NUMBER_PSEUD", "NIN_PSEUD"),
        ("NHS_ID_STATUS_IND", "NIN_STATUS_IND"),
        ("Previous NHS Number", "Previous NIN"),
        ("Date of NHS Exit", "Date of NIN Exit"),
        ("NHS BS Code", "Medicare BS Code"),
    ],
)
def test_nhs_to_nin(before: str, after: str) -> None:
    assert nhs_to_nin(before) == after


def test_credentials_from_the_erd_are_not_canonical_columns() -> None:
    canonical = [
        t for name, t in models.Base.metadata.tables.items() if not name.startswith("stg_")
    ]
    cols = {c.name for t in canonical for c in t.columns}
    assert not cols & {"password", "shared_secret", "logon_name", "forti_token_id"}
