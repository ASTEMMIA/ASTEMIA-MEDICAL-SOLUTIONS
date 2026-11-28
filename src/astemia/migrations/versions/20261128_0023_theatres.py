"""Theatres, theatre sessions and theatre cases (CEDA HS03, WF05 step 2).

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

import astemia.adapters.db.types

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "theatre",
        sa.Column("facility_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
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
            ["tenant_id", "facility_id"],
            ["organisation_site.tenant_id", "organisation_site.id"],
            name=op.f("fk_theatre_organisation_site_tenant_id_facility_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_theatre")),
        sa.UniqueConstraint("tenant_id", "code", name=op.f("uq_theatre_tenant_id_code")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_table(
        "theatre_session",
        sa.Column("theatre_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("starts_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.Column("ends_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.Column("capacity_minutes", sa.Integer(), nullable=False),
        sa.Column("booked_minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("status_reason", sa.String(length=500), nullable=True),
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
            ["tenant_id", "theatre_id"],
            ["theatre.tenant_id", "theatre.id"],
            name=op.f("fk_theatre_session_theatre_tenant_id_theatre_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_theatre_session")),
        sa.UniqueConstraint(
            "tenant_id",
            "theatre_id",
            "starts_at",
            name=op.f("uq_theatre_session_tenant_id_theatre_id_starts_at"),
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_table(
        "theatre_case",
        sa.Column("session_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("encounter_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("patient_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("surgeon_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("care_plan_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("procedure", sa.String(length=200), nullable=False),
        sa.Column("procedure_code", sa.String(length=64), nullable=True),
        sa.Column("laterality", sa.String(length=16), nullable=False),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("checklist", sa.JSON(), nullable=False),
        sa.Column("override_reason", sa.String(length=500), nullable=True),
        sa.Column("started_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column("completed_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column("procedure_note", sa.Text(), nullable=True),
        sa.Column("cancelled_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column("cancellation_reason", sa.String(length=500), nullable=True),
        sa.Column(
            "handover_recipient_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True
        ),
        sa.Column("handed_over_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column("handover_note", sa.String(length=2000), nullable=True),
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
            name=op.f("fk_theatre_case_care_plan_tenant_id_care_plan_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "encounter_id"],
            ["encounter.tenant_id", "encounter.id"],
            name=op.f("fk_theatre_case_encounter_tenant_id_encounter_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "handover_recipient_id"],
            ["practitioner.tenant_id", "practitioner.id"],
            name=op.f("fk_theatre_case_practitioner_tenant_id_handover_recipient_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patient.tenant_id", "patient.id"],
            name=op.f("fk_theatre_case_patient_tenant_id_patient_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "session_id"],
            ["theatre_session.tenant_id", "theatre_session.id"],
            name=op.f("fk_theatre_case_theatre_session_tenant_id_session_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "surgeon_id"],
            ["practitioner.tenant_id", "practitioner.id"],
            name=op.f("fk_theatre_case_practitioner_tenant_id_surgeon_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_theatre_case")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_theatre_case_tenant_id_patient_id"),
        "theatre_case",
        ["tenant_id", "patient_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("theatre_case")
    op.drop_table("theatre_session")
    op.drop_table("theatre")
