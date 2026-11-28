"""Inbound HL7 v2 message log: applied once, results held until their order
(CEDA section 6, WF03).

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

import astemia.adapters.db.types

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interface_message",
        sa.Column("sender", sa.String(length=128), nullable=False),
        sa.Column("control_id", sa.String(length=64), nullable=False),
        sa.Column("message_type", sa.String(length=16), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("raw", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("ack_code", sa.String(length=2), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("detail", sa.String(length=500), nullable=True),
        sa.Column("placer_key", sa.String(length=160), nullable=True),
        sa.Column("patient_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("resource_type", sa.String(length=32), nullable=True),
        sa.Column("resource_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("processed_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
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
            name=op.f("fk_interface_message_patient_tenant_id_patient_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_interface_message")),
        sa.UniqueConstraint(
            "tenant_id",
            "sender",
            "control_id",
            name=op.f("uq_interface_message_tenant_id_sender_control_id"),
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_interface_message_tenant_id_status_placer_key"),
        "interface_message",
        ["tenant_id", "status", "placer_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("interface_message")
