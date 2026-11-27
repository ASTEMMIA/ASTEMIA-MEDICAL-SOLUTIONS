"""The schema built from the AMS ERDs: every entity lands somewhere, and the owner's
naming rules hold (NIN, Astemia Medical Solutions, medical doctor)."""

import pytest

from astemia.adapters.db import models
from astemia.adapters.db.legacy_names import rename_nhs
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
        ("Date of NHS Exit", "Date of Astemia Medical Solutions Exit"),
        ("NHS BS Code", "Astemia Medical Solutions BS Code"),
        ("NHS Status", "Astemia Medical Solutions Status"),
        ("nhs_status", "astemia_medical_solutions_status"),
        ("NHS Number (Temporary NHS Number/NHAIS)", "NIN (Temporary NIN/NIMC)"),
    ],
)
def test_nhs_naming(before: str, after: str) -> None:
    assert rename_nhs(before) == after


def test_credentials_from_the_erd_are_not_canonical_columns() -> None:
    canonical = [
        t for name, t in models.Base.metadata.tables.items() if not name.startswith("stg_")
    ]
    cols = {c.name for t in canonical for c in t.columns}
    assert not cols & {"password", "shared_secret", "logon_name", "forti_token_id"}


@pytest.mark.parametrize(
    ("label", "mapped"),
    [
        ("MEDICARE Number", "patient_identifier[issuer=NG-NIN].value"),
        ("MEDICARE_ID", "patient_identifier[issuer=NG-NIN].value"),
        ("NIN", "patient_identifier[issuer=NG-NIN].value"),
        ("Status of medicare No", "patient_identifier[issuer=NG-NIN].verification_status"),
        ("MEDICARE_NUMBER_PSEUD", "pseudonymise(patient_identifier[issuer=NG-NIN].value)"),
        ("MEDICARE Service Agreement Line Number", None),
        ("Day Care Attendance (Mental Health MEDICARE Site)", None),
    ],
)
def test_extract_identifier_fields_map_to_nin(label: str, mapped: str | None) -> None:
    from astemia.adapters.db.legacy_names import identifier_mapping

    assert identifier_mapping(label) == mapped


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("Registered GP Number", "Registered Medical Doctor Number"),
        ("GP Practice Registration Number", "Medical Doctor Practice Registration Number"),
        ("GP_CODE", "MEDICAL_DOCTOR_CODE"),
        ("ORG_CODE_GP", "ORG_CODE_MEDICAL_DOCTOR"),
        ("HCA_724_HEADER_VGP", "HCA_724_HEADER_VGP"),  # VGP is not a GP field
    ],
)
def test_gp_becomes_medical_doctor(before: str, after: str) -> None:
    from astemia.adapters.db.legacy_names import localise

    assert localise(before) == after


def test_no_gp_names_in_the_schema_or_dictionary() -> None:
    import re

    gp = re.compile(r"(^|[^a-z])gp([^a-z]|$)")
    names = [t.name for t in models.Base.metadata.tables.values()]
    names += [c.name for t in models.Base.metadata.tables.values() for c in t.columns]
    assert [n for n in names if gp.search(n.lower())] == []
    _, fields = extract_dictionary_rows()
    assert [f["label"] for f in fields if gp.search(f["label"].lower())] == []
    assert any(gp.search(f["source_label"].lower()) for f in fields)  # lineage kept
