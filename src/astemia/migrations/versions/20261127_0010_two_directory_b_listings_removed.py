"""Remove two directory B listings.

Directory B positions 41 and 52 are removed, with the search aliases tenants
created from them. The services they mapped to stay in the catalogue. Other
positions are not renumbered: a position is the publisher's listing order.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BASE = "https://www.nhsggc.scot/hospitals-services/services-a-to-z/"
# (position, listing, URL slug, service code)
REMOVED: list[tuple[int, str, str, str]] = [
    (41, "Esteem Glasgow", "esteem-glasgow/", "D39-07"),
    (52, "Glasgow City Youth Health Service", "glasgow-city-youth-health-service/", "D36-08"),
]


def upgrade() -> None:
    conn = op.get_bind()
    for pos, listing, _, _ in REMOVED:
        conn.execute(
            sa.text(
                "DELETE FROM service_directory_listing "
                "WHERE directory = 'directory_b' AND position = :pos AND listing = :listing"
            ),
            {"pos": pos, "listing": listing},
        )
        conn.execute(
            sa.text("DELETE FROM service_alias WHERE alias = :listing"),
            {"listing": listing},
        )


def downgrade() -> None:
    """Restores the two listings. Tenant aliases are not restored; a tenant
    that needs them provisions the catalogue again."""
    conn = op.get_bind()
    for pos, listing, slug, code in REMOVED:
        conn.execute(
            sa.text(
                "INSERT INTO service_directory_listing "
                "(directory, position, listing, url, service_code, snapshot) "
                "VALUES ('directory_b', :pos, :listing, :url, :code, '2026-11-23')"
            ),
            {"pos": pos, "listing": listing, "url": BASE + slug, "code": code},
        )
