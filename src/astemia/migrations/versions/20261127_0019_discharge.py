"""Discharge summaries, one per encounter (CEDA HS05, ST08).

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

import astemia.adapters.db.types

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discharge_summary",
        sa.Column("encounter_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("patient_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("disposition", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("follow_up", sa.String(length=2000), nullable=True),
        sa.Column("discharged_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column("signed_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column("signed_by_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
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
            ["tenant_id", "encounter_id"],
            ["encounter.tenant_id", "encounter.id"],
            name=op.f("fk_discharge_summary_encounter_tenant_id_encounter_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patient.tenant_id", "patient.id"],
            name=op.f("fk_discharge_summary_patient_tenant_id_patient_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "signed_by_id"],
            ["practitioner.tenant_id", "practitioner.id"],
            name=op.f("fk_discharge_summary_practitioner_tenant_id_signed_by_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_discharge_summary")),
        sa.UniqueConstraint(
            "tenant_id", "encounter_id", name=op.f("uq_discharge_summary_tenant_id_encounter_id")
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )


def downgrade() -> None:
    op.drop_table("discharge_summary")
