"""Emergency access grants (CEDA SA-04 EmergencyGrant, SEC-04, WF02 step 4).

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

import astemia.adapters.db.types

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "emergency_grant",
        sa.Column("patient_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column(
            "practitioner_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False
        ),
        sa.Column("purpose", sa.String(length=500), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("starts_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.Column("expires_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.Column("step_up", sa.String(length=16), nullable=False),
        sa.Column("review_due_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.Column("reviewed_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column("reviewed_by_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("review_outcome", sa.String(length=16), nullable=True),
        sa.Column("review_note", sa.String(length=500), nullable=True),
        sa.Column("tenant_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("version", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("recorded_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.Column("effective_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column("effective_precision", sa.String(length=16), nullable=True),
        sa.Column("author_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("author_role", sa.String(length=64), nullable=True),
        sa.Column("source_system", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=True),
        sa.Column("source_status", sa.String(length=32), nullable=True),
        sa.Column("sensitivity", sa.String(length=32), nullable=False),
        sa.Column("data_absent_reason", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patient.tenant_id", "patient.id"],
            name=op.f("fk_emergency_grant_patient_tenant_id_patient_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "practitioner_id"],
            ["practitioner.tenant_id", "practitioner.id"],
            name=op.f("fk_emergency_grant_practitioner_tenant_id_practitioner_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reviewed_by_id"],
            ["practitioner.tenant_id", "practitioner.id"],
            name=op.f("fk_emergency_grant_practitioner_tenant_id_reviewed_by_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_emergency_grant")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_emergency_grant_tenant_id_practitioner_id_patient_id_expires_at"),
        "emergency_grant",
        ["tenant_id", "practitioner_id", "patient_id", "expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_emergency_grant_tenant_id_reviewed_at_review_due_at"),
        "emergency_grant",
        ["tenant_id", "reviewed_at", "review_due_at"],
        unique=False,
    )


def downgrade() -> None:
    # Dropping the table drops its indexes; dropping an index that backs a
    # foreign key first would be refused.
    op.drop_table("emergency_grant")
