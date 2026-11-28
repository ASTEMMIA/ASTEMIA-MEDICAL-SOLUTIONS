"""Radiology: imaging requests and studies, and the full text of a narrative
report (CEDA HS07, WF05 step 1). Expand only: one new nullable column.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

import astemia.adapters.db.types

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "imaging_request",
        sa.Column(
            "service_request_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False
        ),
        sa.Column("patient_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("modality", sa.String(length=8), nullable=False),
        sa.Column("body_site", sa.String(length=100), nullable=False),
        sa.Column("laterality", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("protocol", sa.String(length=200), nullable=True),
        sa.Column("vetting_note", sa.String(length=1000), nullable=True),
        sa.Column("vetted_by_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("vetted_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column("scheduled_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column("accession_number", sa.String(length=32), nullable=True),
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
            name=op.f("fk_imaging_request_patient_tenant_id_patient_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "service_request_id"],
            ["service_request.tenant_id", "service_request.id"],
            name=op.f("fk_imaging_request_service_request_tenant_id_service_request_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "vetted_by_id"],
            ["practitioner.tenant_id", "practitioner.id"],
            name=op.f("fk_imaging_request_practitioner_tenant_id_vetted_by_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_imaging_request")),
        sa.UniqueConstraint(
            "tenant_id",
            "accession_number",
            name=op.f("uq_imaging_request_tenant_id_accession_number"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "service_request_id",
            name=op.f("uq_imaging_request_tenant_id_service_request_id"),
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_imaging_request_tenant_id_state"),
        "imaging_request",
        ["tenant_id", "state"],
        unique=False,
    )
    op.create_table(
        "imaging_study",
        sa.Column("study_instance_uid", sa.String(length=64), nullable=False),
        sa.Column("accession_number", sa.String(length=32), nullable=False),
        sa.Column("modality", sa.String(length=8), nullable=False),
        sa.Column("performed_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.Column("pacs_reference", sa.String(length=255), nullable=False),
        sa.Column("received_issuer", sa.String(length=32), nullable=False),
        sa.Column("received_identifier", sa.String(length=64), nullable=False),
        sa.Column("received_birth_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("conflicts", sa.JSON(), nullable=False),
        sa.Column(
            "imaging_request_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True
        ),
        sa.Column("patient_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("linked_by_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("linked_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column("link_reason", sa.String(length=500), nullable=True),
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
            ["tenant_id", "imaging_request_id"],
            ["imaging_request.tenant_id", "imaging_request.id"],
            name=op.f("fk_imaging_study_imaging_request_tenant_id_imaging_request_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "linked_by_id"],
            ["practitioner.tenant_id", "practitioner.id"],
            name=op.f("fk_imaging_study_practitioner_tenant_id_linked_by_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patient.tenant_id", "patient.id"],
            name=op.f("fk_imaging_study_patient_tenant_id_patient_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_imaging_study")),
        sa.UniqueConstraint(
            "tenant_id",
            "study_instance_uid",
            name=op.f("uq_imaging_study_tenant_id_study_instance_uid"),
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_imaging_study_tenant_id_status"),
        "imaging_study",
        ["tenant_id", "status"],
        unique=False,
    )
    op.add_column("diagnostic_report", sa.Column("presented_form", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("diagnostic_report", "presented_form")
    op.drop_table("imaging_study")
    op.drop_table("imaging_request")
