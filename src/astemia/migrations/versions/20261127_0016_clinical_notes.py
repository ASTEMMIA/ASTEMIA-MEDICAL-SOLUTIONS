"""Clinical notes: entries and their revisions; a signed revision is never
changed (CEDA SA-07; UG02, WF01 step 3).

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

import astemia.adapters.db.types

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "clinical_entry",
        sa.Column("patient_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("encounter_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("note_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
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
            name=op.f("fk_clinical_entry_encounter_tenant_id_encounter_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patient.tenant_id", "patient.id"],
            name=op.f("fk_clinical_entry_patient_tenant_id_patient_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_clinical_entry")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_clinical_entry_tenant_id_patient_id_recorded_at"),
        "clinical_entry",
        ["tenant_id", "patient_id", "recorded_at"],
        unique=False,
    )
    op.create_table(
        "entry_revision",
        sa.Column("entry_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("supersedes_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("amendment_reason", sa.String(length=500), nullable=True),
        sa.Column("signed_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column("signed_by_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("draft_marker", mysql.TINYINT(), nullable=True),
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
            ["tenant_id", "entry_id"],
            ["clinical_entry.tenant_id", "clinical_entry.id"],
            name=op.f("fk_entry_revision_clinical_entry_tenant_id_entry_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "signed_by_id"],
            ["practitioner.tenant_id", "practitioner.id"],
            name=op.f("fk_entry_revision_practitioner_tenant_id_signed_by_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supersedes_id"],
            ["entry_revision.tenant_id", "entry_revision.id"],
            name=op.f("fk_entry_revision_entry_revision_tenant_id_supersedes_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_entry_revision")),
        sa.UniqueConstraint(
            "tenant_id",
            "entry_id",
            "draft_marker",
            name=op.f("uq_entry_revision_tenant_id_entry_id_draft_marker"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "entry_id",
            "revision_number",
            name=op.f("uq_entry_revision_tenant_id_entry_id_revision_number"),
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )


def downgrade() -> None:
    # Children first; dropping a table drops its indexes with it.
    for table in ("entry_revision", "clinical_entry"):
        op.drop_table(table)
