"""Rename GP to medical doctor.

* stg_patient_service_user: the AHIS GP columns now share their names with the
  ZETTER medical doctor columns. Staged values are copied across where the
  medical doctor column is empty, then the GP columns are dropped.
* national_extract_field: GP labels and field keys become medical doctor; the
  original label stays in source_label.
* Catalogue service D36-07 becomes "Medical doctor out of hours", in the
  template and in every tenant that still uses the template name.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from astemia.adapters.db.staging import extract_dictionary_rows

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STAGING = "stg_patient_service_user"
MERGED = {
    "registered_gp_number": "registered_medical_doctor_number",
    "registered_gp_name": "registered_medical_doctor_name",
    "registered_gp_information": "registered_medical_doctor_information",
    "gp_practice_registration_number": "medical_doctor_practice_registration_number",
}
OLD_SERVICE, NEW_SERVICE = "GP out of hours", "Medical doctor out of hours"


def upgrade() -> None:
    for old, new in MERGED.items():
        # Identifiers cannot be bound parameters; these are fixed constants above.
        copy = f"UPDATE {STAGING} SET {new} = {old} WHERE {new} IS NULL AND {old} IS NOT NULL"  # noqa: S608
        op.execute(copy)
        op.drop_column(STAGING, old)

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

    conn.execute(
        sa.text("UPDATE service_template SET name = :new WHERE code = 'D36-07'"),
        {"new": NEW_SERVICE},
    )
    conn.execute(
        sa.text(
            "UPDATE clinical_service SET name = :new, version = version + 1 "
            "WHERE template_code = 'D36-07' AND name = :old"
        ),
        {"new": NEW_SERVICE, "old": OLD_SERVICE},
    )


def downgrade() -> None:
    """Restores the GP columns (empty: merged values stay in the medical doctor
    columns), the GP labels and the template name. Field keys keep their
    medical doctor form; nothing reads them by the old key."""
    for old in MERGED:
        op.add_column(STAGING, sa.Column(old, sa.Text(), nullable=True))
    op.execute(
        "UPDATE national_extract_field SET label = source_label "
        "WHERE source_label REGEXP '(^|[^A-Za-z])GP([^A-Za-z]|$)'"
    )
    op.get_bind().execute(
        sa.text("UPDATE service_template SET name = :old WHERE code = 'D36-07'"),
        {"old": OLD_SERVICE},
    )
