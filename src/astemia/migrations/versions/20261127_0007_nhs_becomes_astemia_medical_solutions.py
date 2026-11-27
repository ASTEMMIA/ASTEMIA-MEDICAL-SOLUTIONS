"""NHS becomes Astemia Medical Solutions; the NHS number and NHS ID stay NIN.

* Staging columns that carried a non-identifier NHS term are renamed in place,
  so any staged values are kept (for example nin_status becomes
  astemia_medical_solutions_status).
* The business-service code and name (ERD "NHS BS Code/Name") no longer share
  the Medicare columns: they get their own astemia_medical_solutions_bs_*
  columns.
* national_extract_field labels and keys follow the same rule; the original
  label stays in source_label.
* The directory listing "Shops in NHSGGC" becomes "Shops in Astemia Medical
  Solutions GGC", in the crosswalk and in every tenant's search aliases.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from astemia.adapters.db.staging import extract_dictionary_rows

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RENAMES = [
    ("stg_patient_service_user", "nin_status", "astemia_medical_solutions_status"),
    ("stg_patient_service_user", "current_nin_status", "current_astemia_medical_solutions_status"),
    ("stg_patient_service_user", "date_of_nin_exit", "date_of_astemia_medical_solutions_exit"),
    ("stg_person", "nin_status", "astemia_medical_solutions_status"),
    ("stg_person_history", "nin_status", "astemia_medical_solutions_status"),
]
ADDED = [
    ("stg_business_clinical_service", "astemia_medical_solutions_bs_code"),
    ("stg_business_clinical_service", "astemia_medical_solutions_bs_name"),
]


def _labels() -> None:
    conn = op.get_bind()
    _, fields = extract_dictionary_rows()
    for f in fields:
        conn.execute(
            sa.text(
                "UPDATE national_extract_field SET label = :label, field_key = :key "
                "WHERE extract_code = :code AND position = :pos "
                "AND (label <> :label OR field_key <> :key)"
            ),
            {
                "label": f["label"],
                "key": f["field_key"],
                "code": f["extract_code"],
                "pos": f["position"],
            },
        )


LISTINGS = {"Shops in NHSGGC": "Shops in Astemia Medical Solutions GGC"}


def _listings(pairs: dict[str, str]) -> None:
    conn = op.get_bind()
    for old, new in pairs.items():
        conn.execute(
            sa.text(
                "UPDATE service_directory_listing SET listing = :new "
                "WHERE directory = 'nhsggc' AND listing = :old"
            ),
            {"old": old, "new": new},
        )
        conn.execute(
            sa.text(
                "DELETE a FROM service_alias a JOIN service_alias b "
                "ON b.tenant_id = a.tenant_id AND b.service_id = a.service_id AND b.alias = :new "
                "WHERE a.alias = :old"
            ),
            {"old": old, "new": new},
        )
        conn.execute(
            sa.text(
                "UPDATE service_alias SET alias = :new, version = version + 1 WHERE alias = :old"
            ),
            {"old": old, "new": new},
        )


def upgrade() -> None:
    for table, old, new in RENAMES:
        op.alter_column(
            table, old, new_column_name=new, existing_type=sa.Text(), existing_nullable=True
        )
    for table, column in ADDED:
        op.add_column(table, sa.Column(column, sa.Text(), nullable=True))
    _labels()
    _listings(LISTINGS)


def downgrade() -> None:
    """Columns go back to their 0006 names; the BS columns are dropped (their
    values, if any, are lost: in 0006 they shared the Medicare columns).
    Dictionary labels keep their current form; listing names go back."""
    _listings({new: old for old, new in LISTINGS.items()})
    for table, column in ADDED:
        op.drop_column(table, column)
    for table, old, new in RENAMES:
        op.alter_column(
            table, new, new_column_name=old, existing_type=sa.Text(), existing_nullable=True
        )
