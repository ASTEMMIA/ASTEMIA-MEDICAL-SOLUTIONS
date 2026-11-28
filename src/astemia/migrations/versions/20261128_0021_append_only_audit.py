"""The audit trail is append-only: the database refuses any update or delete
of an audit event, whatever the application does (hardening P0; ICRS 4.5.40).
Write-once storage outside the database follows with production key
management (PROGRAMME.md, P4).

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REFUSE = "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_event is append-only'"


def upgrade() -> None:
    op.execute(
        f"CREATE TRIGGER audit_event_no_update BEFORE UPDATE ON audit_event FOR EACH ROW {REFUSE}"
    )
    op.execute(
        f"CREATE TRIGGER audit_event_no_delete BEFORE DELETE ON audit_event FOR EACH ROW {REFUSE}"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_event_no_delete")
    op.execute("DROP TRIGGER IF EXISTS audit_event_no_update")
