"""Identity review tasks: why a pair of records was raised, from where, and the
reviewers' notes, on duplicate_candidate (UG02, WF01). Expand only.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("duplicate_candidate", sa.Column("reasons", sa.JSON(), nullable=True))
    op.add_column("duplicate_candidate", sa.Column("origin", sa.String(16), nullable=True))
    op.add_column("duplicate_candidate", sa.Column("note", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("duplicate_candidate", "note")
    op.drop_column("duplicate_candidate", "origin")
    op.drop_column("duplicate_candidate", "reasons")
