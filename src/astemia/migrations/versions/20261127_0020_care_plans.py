"""Conditions and care plans: plans, their revisions and sessions (CEDA HS12;
SA-08).

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

import astemia.adapters.db.types

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "condition",
        sa.Column("patient_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("certainty", sa.String(length=16), nullable=False),
        sa.Column("onset_date", sa.Date(), nullable=True),
        sa.Column("register_code", sa.String(length=32), nullable=True),
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
        sa.Column("code_system", sa.String(length=128), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("display", sa.String(length=255), nullable=False),
        sa.Column("original_system", sa.String(length=128), nullable=True),
        sa.Column("original_code", sa.String(length=64), nullable=True),
        sa.Column("map_version", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patient.tenant_id", "patient.id"],
            name=op.f("fk_condition_patient_tenant_id_patient_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_condition")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_condition_tenant_id_patient_id"),
        "condition",
        ["tenant_id", "patient_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_condition_tenant_id_register_code_certainty"),
        "condition",
        ["tenant_id", "register_code", "certainty"],
        unique=False,
    )
    op.create_table(
        "care_plan",
        sa.Column("patient_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("condition_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("pathway", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("owner_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("review_date", sa.Date(), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("discontinuation_reason", sa.String(length=500), nullable=True),
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
            ["tenant_id", "condition_id"],
            ["condition.tenant_id", "condition.id"],
            name=op.f("fk_care_plan_condition_tenant_id_condition_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_id"],
            ["practitioner.tenant_id", "practitioner.id"],
            name=op.f("fk_care_plan_practitioner_tenant_id_owner_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patient.tenant_id", "patient.id"],
            name=op.f("fk_care_plan_patient_tenant_id_patient_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_care_plan")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_care_plan_tenant_id_patient_id"),
        "care_plan",
        ["tenant_id", "patient_id"],
        unique=False,
    )
    op.create_table(
        "plan_revision",
        sa.Column("care_plan_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("effective_from", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.Column("session_type", sa.String(length=32), nullable=False),
        sa.Column("interval_days", sa.Integer(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("protocol_code", sa.String(length=64), nullable=True),
        sa.Column(
            "authorised_by_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False
        ),
        sa.Column("reason", sa.String(length=500), nullable=False),
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
            ["tenant_id", "authorised_by_id"],
            ["practitioner.tenant_id", "practitioner.id"],
            name=op.f("fk_plan_revision_practitioner_tenant_id_authorised_by_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "care_plan_id"],
            ["care_plan.tenant_id", "care_plan.id"],
            name=op.f("fk_plan_revision_care_plan_tenant_id_care_plan_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_plan_revision")),
        sa.UniqueConstraint(
            "tenant_id",
            "care_plan_id",
            "revision_number",
            name=op.f("uq_plan_revision_tenant_id_care_plan_id_revision_number"),
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_table(
        "plan_cycle",
        sa.Column("care_plan_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column(
            "plan_revision_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False
        ),
        sa.Column("patient_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("scheduled_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("completed_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column(
            "completed_by_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True
        ),
        sa.Column("outcome_note", sa.String(length=1000), nullable=True),
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
            ["tenant_id", "care_plan_id"],
            ["care_plan.tenant_id", "care_plan.id"],
            name=op.f("fk_plan_cycle_care_plan_tenant_id_care_plan_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "completed_by_id"],
            ["practitioner.tenant_id", "practitioner.id"],
            name=op.f("fk_plan_cycle_practitioner_tenant_id_completed_by_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patient.tenant_id", "patient.id"],
            name=op.f("fk_plan_cycle_patient_tenant_id_patient_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "plan_revision_id"],
            ["plan_revision.tenant_id", "plan_revision.id"],
            name=op.f("fk_plan_cycle_plan_revision_tenant_id_plan_revision_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_plan_cycle")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_plan_cycle_tenant_id_care_plan_id_scheduled_at"),
        "plan_cycle",
        ["tenant_id", "care_plan_id", "scheduled_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_plan_cycle_tenant_id_patient_id_scheduled_at"),
        "plan_cycle",
        ["tenant_id", "patient_id", "scheduled_at"],
        unique=False,
    )


def downgrade() -> None:
    # Children first; dropping a table drops its indexes with it.
    for table in ("plan_cycle", "plan_revision", "care_plan", "condition"):
        op.drop_table(table)
