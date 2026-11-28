"""Clinical correspondence: documents, their versions and the original bytes,
fixed by digest (CEDA SA-12; UG04).

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

import astemia.adapters.db.types

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_object",
        sa.Column("tenant_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("media_type", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "content", sa.LargeBinary().with_variant(mysql.LONGBLOB(), "mysql"), nullable=False
        ),
        sa.Column("stored_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "digest", name=op.f("pk_document_object")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_table(
        "document",
        sa.Column("sender", sa.String(length=200), nullable=False),
        sa.Column("received_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.Column("document_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("media_type", sa.String(length=64), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("scan", sa.String(length=16), nullable=False),
        sa.Column("scan_reason", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column("adjudication", sa.String(length=500), nullable=True),
        sa.Column("patient_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("encounter_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("reviewer_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("reviewed_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column("review_note", sa.String(length=1000), nullable=True),
        sa.Column("current_version", sa.Integer(), nullable=False),
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
            name=op.f("fk_document_encounter_tenant_id_encounter_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patient.tenant_id", "patient.id"],
            name=op.f("fk_document_patient_tenant_id_patient_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reviewer_id"],
            ["practitioner.tenant_id", "practitioner.id"],
            name=op.f("fk_document_practitioner_tenant_id_reviewer_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_document")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_document_tenant_id_patient_id"),
        "document",
        ["tenant_id", "patient_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_tenant_id_status_received_at"),
        "document",
        ["tenant_id", "status", "received_at"],
        unique=False,
    )
    op.create_table(
        "document_version",
        sa.Column("document_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("patient_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("encounter_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("document_type", sa.String(length=32), nullable=False),
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
            ["tenant_id", "document_id"],
            ["document.tenant_id", "document.id"],
            name=op.f("fk_document_version_document_tenant_id_document_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "encounter_id"],
            ["encounter.tenant_id", "encounter.id"],
            name=op.f("fk_document_version_encounter_tenant_id_encounter_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patient.tenant_id", "patient.id"],
            name=op.f("fk_document_version_patient_tenant_id_patient_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_document_version")),
        sa.UniqueConstraint(
            "tenant_id",
            "document_id",
            "version_number",
            name=op.f("uq_document_version_tenant_id_document_id_version_number"),
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )


def downgrade() -> None:
    # Children first; dropping a table drops its indexes with it.
    for table in ("document_version", "document", "document_object"):
        op.drop_table(table)
