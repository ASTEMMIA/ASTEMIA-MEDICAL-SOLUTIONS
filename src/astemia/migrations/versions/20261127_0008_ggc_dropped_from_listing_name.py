"""Drop "GGC" from the directory listing name.

"Shops in Astemia Medical Solutions GGC" becomes "Shops in Astemia Medical
Solutions", in the directory listing and in every tenant's search aliases.
The Greater Glasgow and Clyde directory itself is kept.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LISTINGS = {"Shops in Astemia Medical Solutions GGC": "Shops in Astemia Medical Solutions"}


def _listings(pairs: dict[str, str]) -> None:
    conn = op.get_bind()
    for old, new in pairs.items():
        conn.execute(
            sa.text(
                "UPDATE service_directory_listing SET listing = :new "
                "WHERE directory = 'nhsggc' AND listing = :old"
            ),
            {"old": old, "new": new},
        )
        # A tenant that already has the new alias for the same service keeps
        # that one; the old alias is removed rather than duplicated.
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
    _listings(LISTINGS)


def downgrade() -> None:
    _listings({new: old for old, new in LISTINGS.items()})
