"""Daybook: tasks, their assignment history and deduplicated reminders (CEDA
UG03).

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

import astemia.adapters.db.types

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task",
        sa.Column("patient_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("due_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.Column("assignee_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("queue", sa.String(length=64), nullable=True),
        sa.Column("origin_type", sa.String(length=32), nullable=True),
        sa.Column("origin_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("escalation_step", sa.Integer(), nullable=False),
        sa.Column("acknowledged_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
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
            ["tenant_id", "assignee_id"],
            ["practitioner.tenant_id", "practitioner.id"],
            name=op.f("fk_task_practitioner_tenant_id_assignee_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "completed_by_id"],
            ["practitioner.tenant_id", "practitioner.id"],
            name=op.f("fk_task_practitioner_tenant_id_completed_by_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patient.tenant_id", "patient.id"],
            name=op.f("fk_task_patient_tenant_id_patient_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_task")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_task_tenant_id_assignee_id_status_due_at"),
        "task",
        ["tenant_id", "assignee_id", "status", "due_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_tenant_id_origin_type_origin_id"),
        "task",
        ["tenant_id", "origin_type", "origin_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_tenant_id_queue_status_due_at"),
        "task",
        ["tenant_id", "queue", "status", "due_at"],
        unique=False,
    )
    op.create_table(
        "task_assignment",
        sa.Column("task_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("assignee_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("queue", sa.String(length=64), nullable=True),
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
            ["tenant_id", "assignee_id"],
            ["practitioner.tenant_id", "practitioner.id"],
            name=op.f("fk_task_assignment_practitioner_tenant_id_assignee_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["task.tenant_id", "task.id"],
            name=op.f("fk_task_assignment_task_tenant_id_task_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_task_assignment")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_task_assignment_tenant_id_task_id_recorded_at"),
        "task_assignment",
        ["tenant_id", "task_id", "recorded_at"],
        unique=False,
    )
    op.create_table(
        "task_notification",
        sa.Column("tenant_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("task_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("policy", sa.String(length=32), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("recipient_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("recipient_queue", sa.String(length=64), nullable=True),
        sa.Column("created_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["task.tenant_id", "task.id"],
            name=op.f("fk_task_notification_task_tenant_id_task_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_task_notification")),
        sa.UniqueConstraint(
            "tenant_id",
            "task_id",
            "policy",
            "step",
            name=op.f("uq_task_notification_tenant_id_task_id_policy_step"),
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )


def downgrade() -> None:
    # Children first; dropping a table drops its indexes with it.
    for table in ("task_notification", "task_assignment", "task"):
        op.drop_table(table)
