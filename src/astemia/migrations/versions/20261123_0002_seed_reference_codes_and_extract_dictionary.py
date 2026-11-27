"""Seed reference codes (ERD Name Type, Address Type) and the national-extract
field dictionary generated from the AMS ERDs.

Name and address type values are proposed defaults: the ERDs define the
tables but not their values. Confirm with the chief data architect.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from astemia.adapters.db.staging import extract_dictionary_rows

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME_TYPES = [
    ("usual", "Usual name"),
    ("preferred", "Preferred name"),
    ("maiden", "Maiden name"),
    ("alias", "Alias or alternative name"),
    ("previous", "Previous name"),
]
ADDRESS_TYPES = [
    ("home", "Usual home address"),
    ("correspondence", "Correspondence address"),
    ("temporary", "Temporary address"),
    ("work", "Work address"),
    ("billing", "Billing address"),
    ("site", "Organisation site address"),
]


def upgrade() -> None:
    code = sa.table("name_type", sa.column("code", sa.String), sa.column("description", sa.String))
    op.bulk_insert(code, [{"code": c, "description": d} for c, d in NAME_TYPES])
    addr = sa.table(
        "address_type", sa.column("code", sa.String), sa.column("description", sa.String)
    )
    op.bulk_insert(addr, [{"code": c, "description": d} for c, d in ADDRESS_TYPES])

    extracts, fields = extract_dictionary_rows()
    op.bulk_insert(
        sa.table(
            "national_extract",
            sa.column("code", sa.String),
            sa.column("name", sa.String),
            sa.column("source_entities", sa.String),
            sa.column("source_erd", sa.String),
            sa.column("field_count", sa.Integer),
        ),
        extracts,
    )
    op.bulk_insert(
        sa.table(
            "national_extract_field",
            sa.column("extract_code", sa.String),
            sa.column("position", sa.Integer),
            sa.column("field_key", sa.String),
            sa.column("label", sa.String),
            sa.column("source_label", sa.String),
            sa.column("occurrence", sa.Integer),
        ),
        fields,
    )


def downgrade() -> None:
    op.execute("DELETE FROM national_extract_field")
    op.execute("DELETE FROM national_extract")
    op.execute("DELETE FROM address_type")
    op.execute("DELETE FROM name_type")
