"""Migration of existing patient records: batches and source-row lineage
(CEDA MIG-01 to MIG-03).

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

import astemia.adapters.db.types

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "migration_batch",
        sa.Column("source_system", sa.String(length=32), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("loaded_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column("tenant_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("version", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("recorded_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.Column("effective_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column("effective_precision", sa.String(length=16), nullable=True),
        sa.Column("author_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("author_role", sa.String(length=64), nullable=True),
        sa.Column("source_id", sa.String(length=128), nullable=True),
        sa.Column("source_status", sa.String(length=32), nullable=True),
        sa.Column("sensitivity", sa.String(length=32), nullable=False),
        sa.Column("data_absent_reason", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_migration_batch")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_table(
        "migration_record",
        sa.Column("batch_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("source_system", sa.String(length=32), nullable=False),
        sa.Column("source_entity", sa.String(length=64), nullable=False),
        sa.Column("source_row_key", sa.String(length=128), nullable=False),
        sa.Column("row_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("detail", sa.String(length=500), nullable=True),
        sa.Column("patient_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("identity_digest", sa.String(length=64), nullable=True),
        sa.Column("loaded_marker", mysql.TINYINT(), nullable=True),
        sa.Column("tenant_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("version", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("recorded_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.Column("effective_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column("effective_precision", sa.String(length=16), nullable=True),
        sa.Column("author_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("author_role", sa.String(length=64), nullable=True),
        sa.Column("source_id", sa.String(length=128), nullable=True),
        sa.Column("source_status", sa.String(length=32), nullable=True),
        sa.Column("sensitivity", sa.String(length=32), nullable=False),
        sa.Column("data_absent_reason", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["migration_batch.tenant_id", "migration_batch.id"],
            name=op.f("fk_migration_record_migration_batch_tenant_id_batch_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patient.tenant_id", "patient.id"],
            name=op.f("fk_migration_record_patient_tenant_id_patient_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_migration_record")),
        sa.UniqueConstraint(
            "tenant_id",
            "source_system",
            "source_entity",
            "source_row_key",
            "loaded_marker",
            name="uq_migration_record_source_loaded",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "source_system",
            "source_entity",
            "source_row_key",
            "row_digest",
            name="uq_migration_record_source_version",
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_migration_record_tenant_id_batch_id_status"),
        "migration_record",
        ["tenant_id", "batch_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("migration_record")
    op.drop_table("migration_batch")
