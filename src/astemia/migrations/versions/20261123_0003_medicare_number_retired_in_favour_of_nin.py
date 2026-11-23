"""Retire medicare_number in favour of the NIN.

Data-only and expand-safe:
* any Medicare number still holding an active binding becomes a previous
  identifier (active_marker NULL), so only the NIN binds a patient;
* national-extract fields that carry the patient identifier are mapped to the
  NIN for outbound returns.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from astemia.adapters.db.legacy_names import identifier_mapping

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE patient_identifier SET identifier_type = 'previous', active_marker = NULL, "
        "version = version + 1 WHERE issuer = 'NG-MEDICARE' AND active_marker IS NOT NULL"
    )
    conn = op.get_bind()
    fields = conn.execute(
        sa.text("SELECT extract_code, position, label FROM national_extract_field")
    ).all()
    for code, position, label in fields:
        mapping = identifier_mapping(label)
        if mapping:
            conn.execute(
                sa.text(
                    "UPDATE national_extract_field SET canonical_mapping = :m "
                    "WHERE extract_code = :c AND position = :p"
                ),
                {"m": mapping, "c": code, "p": position},
            )


def downgrade() -> None:
    op.execute(
        "UPDATE national_extract_field SET canonical_mapping = NULL "
        "WHERE canonical_mapping LIKE '%NG-NIN%'"
    )
    # Previous Medicare identifiers are not re-activated: that would undo a
    # business decision, not a schema change.
