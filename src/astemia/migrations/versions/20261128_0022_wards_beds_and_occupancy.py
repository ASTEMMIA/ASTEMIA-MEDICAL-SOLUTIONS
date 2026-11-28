"""Wards, beds and bed occupancy (CEDA HS03, WF02 step 3).

One open occupancy per bed and per encounter, guarded by unique keys on
active_marker.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

import astemia.adapters.db.types

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ward",
        sa.Column("facility_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("specialty", sa.String(length=64), nullable=True),
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
            name=op.f("fk_ward_organisation_site_tenant_id_facility_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_ward")),
        sa.UniqueConstraint("tenant_id", "code", name=op.f("uq_ward_tenant_id_code")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_table(
        "bed",
        sa.Column("ward_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("isolation_capable", sa.Boolean(), nullable=False),
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
            ["tenant_id", "ward_id"],
            ["ward.tenant_id", "ward.id"],
            name=op.f("fk_bed_ward_tenant_id_ward_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_bed")),
        sa.UniqueConstraint(
            "tenant_id", "ward_id", "code", name=op.f("uq_bed_tenant_id_ward_id_code")
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_table(
        "bed_occupancy",
        sa.Column("bed_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("encounter_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("patient_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("start_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.Column("end_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column("end_reason", sa.String(length=16), nullable=True),
        sa.Column("isolation", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("previous_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("active_marker", mysql.TINYINT(), nullable=True),
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
            ["tenant_id", "bed_id"],
            ["bed.tenant_id", "bed.id"],
            name=op.f("fk_bed_occupancy_bed_tenant_id_bed_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "encounter_id"],
            ["encounter.tenant_id", "encounter.id"],
            name=op.f("fk_bed_occupancy_encounter_tenant_id_encounter_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patient.tenant_id", "patient.id"],
            name=op.f("fk_bed_occupancy_patient_tenant_id_patient_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "previous_id"],
            ["bed_occupancy.tenant_id", "bed_occupancy.id"],
            name=op.f("fk_bed_occupancy_bed_occupancy_tenant_id_previous_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_bed_occupancy")),
        sa.UniqueConstraint(
            "tenant_id",
            "bed_id",
            "active_marker",
            name=op.f("uq_bed_occupancy_tenant_id_bed_id_active_marker"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "encounter_id",
            "active_marker",
            name=op.f("uq_bed_occupancy_tenant_id_encounter_id_active_marker"),
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_bed_occupancy_tenant_id_encounter_id_start_at"),
        "bed_occupancy",
        ["tenant_id", "encounter_id", "start_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("bed_occupancy")
    op.drop_table("bed")
    op.drop_table("ward")
