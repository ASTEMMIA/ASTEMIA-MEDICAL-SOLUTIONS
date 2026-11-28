"""Scheduling and referral: slots, holds, appointments, referrals (CEDA SA-05;
UG01, HS04, HS05). A referral names the care episode it summarises.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

import astemia.adapters.db.types

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "slot",
        sa.Column("facility_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column(
            "practitioner_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False
        ),
        sa.Column("service", sa.String(length=64), nullable=False),
        sa.Column(
            "clinical_service_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True
        ),
        sa.Column("slot_type", sa.String(length=16), nullable=False),
        sa.Column("modality", sa.String(length=16), nullable=False),
        sa.Column("starts_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.Column("ends_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
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
            ["tenant_id", "clinical_service_id"],
            ["clinical_service.tenant_id", "clinical_service.id"],
            name=op.f("fk_slot_clinical_service_tenant_id_clinical_service_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "facility_id"],
            ["organisation_site.tenant_id", "organisation_site.id"],
            name=op.f("fk_slot_organisation_site_tenant_id_facility_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "practitioner_id"],
            ["practitioner.tenant_id", "practitioner.id"],
            name=op.f("fk_slot_practitioner_tenant_id_practitioner_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_slot")),
        sa.UniqueConstraint(
            "tenant_id",
            "practitioner_id",
            "starts_at",
            name=op.f("uq_slot_tenant_id_practitioner_id_starts_at"),
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_slot_tenant_id_facility_id_starts_at"),
        "slot",
        ["tenant_id", "facility_id", "starts_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_slot_tenant_id_service_starts_at"),
        "slot",
        ["tenant_id", "service", "starts_at"],
        unique=False,
    )
    op.create_table(
        "referral",
        sa.Column("patient_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("referrer_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column(
            "source_encounter_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False
        ),
        sa.Column("requesting_service", sa.String(length=64), nullable=True),
        sa.Column("receiving_service", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("decided_by_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column("decided_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column("decision_reason", sa.String(length=500), nullable=True),
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
            ["tenant_id", "decided_by_id"],
            ["practitioner.tenant_id", "practitioner.id"],
            name=op.f("fk_referral_practitioner_tenant_id_decided_by_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patient.tenant_id", "patient.id"],
            name=op.f("fk_referral_patient_tenant_id_patient_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "referrer_id"],
            ["practitioner.tenant_id", "practitioner.id"],
            name=op.f("fk_referral_practitioner_tenant_id_referrer_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_encounter_id"],
            ["encounter.tenant_id", "encounter.id"],
            name=op.f("fk_referral_encounter_tenant_id_source_encounter_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_referral")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_referral_tenant_id_patient_id"),
        "referral",
        ["tenant_id", "patient_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_referral_tenant_id_receiving_service_status"),
        "referral",
        ["tenant_id", "receiving_service", "status"],
        unique=False,
    )
    op.create_table(
        "slot_hold",
        sa.Column("slot_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("holder_subject", sa.String(length=255), nullable=False),
        sa.Column("expires_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.Column("released_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=True),
        sa.Column("live_marker", mysql.TINYINT(), nullable=True),
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
            ["tenant_id", "slot_id"],
            ["slot.tenant_id", "slot.id"],
            name=op.f("fk_slot_hold_slot_tenant_id_slot_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_slot_hold")),
        sa.UniqueConstraint(
            "tenant_id",
            "slot_id",
            "live_marker",
            name=op.f("uq_slot_hold_tenant_id_slot_id_live_marker"),
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_table(
        "appointment",
        sa.Column("patient_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("slot_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("referral_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column(
            "rescheduled_from_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True
        ),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("booked_marker", mysql.TINYINT(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("cancel_reason", sa.String(length=500), nullable=True),
        sa.Column("encounter_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True),
        sa.Column(
            "outcome_recorded_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=True
        ),
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
            name=op.f("fk_appointment_encounter_tenant_id_encounter_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "patient_id"],
            ["patient.tenant_id", "patient.id"],
            name=op.f("fk_appointment_patient_tenant_id_patient_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "referral_id"],
            ["referral.tenant_id", "referral.id"],
            name=op.f("fk_appointment_referral_tenant_id_referral_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "rescheduled_from_id"],
            ["appointment.tenant_id", "appointment.id"],
            name=op.f("fk_appointment_appointment_tenant_id_rescheduled_from_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "slot_id"],
            ["slot.tenant_id", "slot.id"],
            name=op.f("fk_appointment_slot_tenant_id_slot_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_appointment")),
        sa.UniqueConstraint(
            "tenant_id",
            "slot_id",
            "booked_marker",
            name=op.f("uq_appointment_tenant_id_slot_id_booked_marker"),
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_appointment_tenant_id_patient_id"),
        "appointment",
        ["tenant_id", "patient_id"],
        unique=False,
    )


def downgrade() -> None:
    # Children first; dropping a table drops its indexes with it.
    for table in ("slot_hold", "appointment", "referral", "slot"):
        op.drop_table(table)
