"""Rename the two services A-Z directories to directories A and B.

Both directories are now named after the Astemia Medical Solutions for
Integrated Care Records Service, as directory A (281 listings) and directory B
(172 listings). Their keys in service_directory_listing become directory_a and
directory_b, and service_template_group.kch_positions becomes
directory_a_positions. Listing positions, names and mappings are unchanged.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KEYS = {"kch": "directory_a", "nhsggc": "directory_b"}


def _keys(pairs: dict[str, str]) -> None:
    conn = op.get_bind()
    for old, new in pairs.items():
        conn.execute(
            sa.text("UPDATE service_directory_listing SET directory = :new WHERE directory = :old"),
            {"old": old, "new": new},
        )


def upgrade() -> None:
    op.alter_column(
        "service_template_group",
        "kch_positions",
        new_column_name="directory_a_positions",
        existing_type=sa.JSON(),
        existing_nullable=False,
    )
    _keys(KEYS)


def downgrade() -> None:
    _keys({new: old for old, new in KEYS.items()})
    op.alter_column(
        "service_template_group",
        "directory_a_positions",
        new_column_name="kch_positions",
        existing_type=sa.JSON(),
        existing_nullable=False,
    )
