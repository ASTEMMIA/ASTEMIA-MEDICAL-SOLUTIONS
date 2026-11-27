"""Mental health safeguards: legal status with history, restrictive
interventions with independent review, and safeguarding concerns (CEDA HS13,
B11; ICRS 5.5.9).

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

import astemia.adapters.db.types

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mental_health_legal_status",
        sa.Column("patient_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("legal_basis", sa.String(length=100), nullable=True),
        sa.Column("valid_from", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.Column("valid_until", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column(
            "authorised_by_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False
        ),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("ended_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column("current_marker", mysql.TINYINT(), nullable=True),
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
            name=op.f("fk_mental_health_legal_status_practitioner_tenant_id_authorised_by_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patient.tenant_id", "patient.id"],
            name=op.f("fk_mental_health_legal_status_patient_tenant_id_patient_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_mental_health_legal_status")),
        sa.UniqueConstraint(
            "tenant_id",
            "patient_id",
            "current_marker",
            name=op.f("uq_mental_health_legal_status_tenant_id_patient_id_current_marker"),
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_mental_health_legal_status_tenant_id_valid_until"),
        "mental_health_legal_status",
        ["tenant_id", "valid_until"],
        unique=False,
    )
    op.create_table(
        "safeguarding_concern",
        sa.Column("patient_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("raised_by", sa.String(length=16), nullable=False),
        sa.Column("raised_by_name", sa.String(length=200), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=False),
        sa.Column(
            "about_practitioner_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("respond_by", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.Column("closed_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column("closed_by_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
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
            ["tenant_id", "about_practitioner_id"],
            ["practitioner.tenant_id", "practitioner.id"],
            name=op.f("fk_safeguarding_concern_practitioner_tenant_id_about_practitioner_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "closed_by_id"],
            ["practitioner.tenant_id", "practitioner.id"],
            name=op.f("fk_safeguarding_concern_practitioner_tenant_id_closed_by_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patient.tenant_id", "patient.id"],
            name=op.f("fk_safeguarding_concern_patient_tenant_id_patient_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_safeguarding_concern")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_safeguarding_concern_tenant_id_patient_id"),
        "safeguarding_concern",
        ["tenant_id", "patient_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_safeguarding_concern_tenant_id_status_respond_by"),
        "safeguarding_concern",
        ["tenant_id", "status", "respond_by"],
        unique=False,
    )
    op.create_table(
        "restrictive_intervention",
        sa.Column("patient_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("encounter_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("intervention_type", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column(
            "authorised_by_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False
        ),
        sa.Column("staff_ids", sa.JSON(), nullable=False),
        sa.Column("started_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.Column("ended_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column("injury", sa.Boolean(), nullable=False),
        sa.Column("injury_detail", sa.String(length=500), nullable=True),
        sa.Column("debrief_offered", sa.Boolean(), nullable=True),
        sa.Column(
            "legal_status_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True
        ),
        sa.Column("flags", sa.JSON(), nullable=False),
        sa.Column("review_due_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.Column("reviewed_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column("reviewed_by_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("review_outcome", sa.String(length=16), nullable=True),
        sa.Column("review_note", sa.String(length=1000), nullable=True),
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
            name=op.f("fk_restrictive_intervention_practitioner_tenant_id_authorised_by_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "encounter_id"],
            ["encounter.tenant_id", "encounter.id"],
            name=op.f("fk_restrictive_intervention_encounter_tenant_id_encounter_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "legal_status_id"],
            ["mental_health_legal_status.tenant_id", "mental_health_legal_status.id"],
            name=op.f(
                "fk_restrictive_intervention_mental_health_legal_status_tenant_id_legal_status_id"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patient.tenant_id", "patient.id"],
            name=op.f("fk_restrictive_intervention_patient_tenant_id_patient_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reviewed_by_id"],
            ["practitioner.tenant_id", "practitioner.id"],
            name=op.f("fk_restrictive_intervention_practitioner_tenant_id_reviewed_by_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_restrictive_intervention")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_restrictive_intervention_tenant_id_patient_id_started_at"),
        "restrictive_intervention",
        ["tenant_id", "patient_id", "started_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_restrictive_intervention_tenant_id_reviewed_at_review_due_at"),
        "restrictive_intervention",
        ["tenant_id", "reviewed_at", "review_due_at"],
        unique=False,
    )


def downgrade() -> None:
    # Children first; dropping a table drops its indexes with it.
    for table in (
        "safeguarding_concern",
        "restrictive_intervention",
        "mental_health_legal_status",
    ):
        op.drop_table(table)
