"""Identity stewardship: review-task detail on duplicate candidates and merge
lineage for unmerge (UG02, WF01 steps 1 and 4, E3, HS02). Expand only.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("duplicate_candidate", sa.Column("reasons", sa.JSON(), nullable=True))
    op.add_column("duplicate_candidate", sa.Column("origin", sa.String(16), nullable=True))
    op.add_column("duplicate_candidate", sa.Column("note", sa.String(500), nullable=True))
    op.add_column("merge_link", sa.Column("lineage", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("merge_link", "lineage")
    op.drop_column("duplicate_candidate", "note")
    op.drop_column("duplicate_candidate", "origin")
    op.drop_column("duplicate_candidate", "reasons")
