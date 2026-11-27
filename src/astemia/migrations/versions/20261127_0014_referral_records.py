"""Referrals carry the patient's historical records: referring and receiving
facilities with their care levels, and the records package (CEDA revision 1.5).
Expand only.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import astemia.adapters.db.types

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "referral_record",
        sa.Column("tenant_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("referral_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("record_type", sa.String(length=32), nullable=False),
        sa.Column("record_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("patient_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=False),
        sa.Column("recorded_at", astemia.adapters.db.types.UTCDateTime(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "referral_id"],
            ["referral.tenant_id", "referral.id"],
            name=op.f("fk_referral_record_referral_tenant_id_referral_id"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_referral_record")),
        sa.UniqueConstraint(
            "tenant_id",
            "referral_id",
            "record_type",
            "record_id",
            name=op.f("uq_referral_record_tenant_id_referral_id_record_type_record_id"),
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.add_column(
        "referral",
        sa.Column(
            "referring_facility_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True
        ),
    )
    op.add_column(
        "referral",
        sa.Column(
            "receiving_facility_id", astemia.adapters.db.types.BinaryUUID(length=16), nullable=True
        ),
    )
    op.add_column("referral", sa.Column("referring_level", sa.String(length=32), nullable=True))
    op.add_column("referral", sa.Column("receiving_level", sa.String(length=32), nullable=True))
    op.add_column("referral", sa.Column("records_count", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_referral_organisation_site_tenant_id_receiving_facility_id"),
        "referral",
        "organisation_site",
        ["tenant_id", "receiving_facility_id"],
        ["tenant_id", "id"],
    )
    op.create_foreign_key(
        op.f("fk_referral_organisation_site_tenant_id_referring_facility_id"),
        "referral",
        "organisation_site",
        ["tenant_id", "referring_facility_id"],
        ["tenant_id", "id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_referral_organisation_site_tenant_id_referring_facility_id"),
        "referral",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_referral_organisation_site_tenant_id_receiving_facility_id"),
        "referral",
        type_="foreignkey",
    )
    op.drop_column("referral", "records_count")
    op.drop_column("referral", "receiving_level")
    op.drop_column("referral", "referring_level")
    op.drop_column("referral", "receiving_facility_id")
    op.drop_column("referral", "referring_facility_id")
    op.drop_table("referral_record")
