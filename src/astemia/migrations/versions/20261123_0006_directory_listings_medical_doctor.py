"""Apply the medical doctor naming to directory listings, with no exceptions.

The NHSGGC listings "GP Out of Hours", "GP Service" and "Out of Hours GP
Service" are renamed in the directory crosswalk and in every tenant's search
aliases. The listing URLs are the publisher's own addresses and stay as they are.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RENAMES = {
    "GP Out of Hours": "Medical Doctor Out of Hours",
    "GP Service": "Medical Doctor Service",
    "Out of Hours GP Service": "Out of Hours Medical Doctor Service",
}


def _apply(pairs: dict[str, str]) -> None:
    conn = op.get_bind()
    for old, new in pairs.items():
        conn.execute(
            sa.text(
                "UPDATE service_directory_listing SET listing = :new "
                "WHERE directory = 'nhsggc' AND listing = :old"
            ),
            {"old": old, "new": new},
        )
        # Rename tenant aliases; drop an old alias where the service already
        # has the new one (the unique key is tenant, alias, service).
        conn.execute(
            sa.text(
                "DELETE a FROM service_alias a JOIN service_alias b "
                "ON b.tenant_id = a.tenant_id AND b.service_id = a.service_id AND b.alias = :new "
                "WHERE a.alias = :old"
            ),
            {"old": old, "new": new},
        )
        conn.execute(
            sa.text(
                "UPDATE service_alias SET alias = :new, version = version + 1 WHERE alias = :old"
            ),
            {"old": old, "new": new},
        )


def upgrade() -> None:
    _apply(RENAMES)


def downgrade() -> None:
    _apply({new: old for old, new in RENAMES.items()})
