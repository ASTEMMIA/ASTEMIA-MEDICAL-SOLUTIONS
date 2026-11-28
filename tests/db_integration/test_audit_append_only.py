"""The audit trail cannot be changed or removed (hardening P0; ICRS 4.5.40)."""

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import AuditEvent
from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import register


def test_audit_events_are_append_only(api: Api, factory: sessionmaker[Session]) -> None:
    register(api)  # writes audit events for this tenant
    with factory() as s:
        event_id = s.scalar(
            select(AuditEvent.id).where(AuditEvent.tenant_id == api.tenant.tenant_id).limit(1)
        )
    assert event_id is not None
    for statement in (
        update(AuditEvent).where(AuditEvent.id == event_id).values(outcome="success"),
        delete(AuditEvent).where(AuditEvent.id == event_id),
    ):
        with factory() as s, pytest.raises(DatabaseError, match="append-only"):
            s.execute(statement)
            s.commit()
    with factory() as s:
        assert s.get(AuditEvent, (api.tenant.tenant_id, event_id)) is not None


def test_database_errors_do_not_carry_personal_data(
    api: Api, factory: sessionmaker[Session]
) -> None:
    """A statement's values (names, NINs, note text) never reach an error
    message, and so never reach a log."""
    register(api)
    with factory() as s:
        event_id = s.scalar(
            select(AuditEvent.id).where(AuditEvent.tenant_id == api.tenant.tenant_id).limit(1)
        )
    with factory() as s, pytest.raises(DatabaseError) as raised:
        s.execute(
            update(AuditEvent)
            .where(AuditEvent.id == event_id)
            .values(reason_code="12345678901")  # refused by the append-only trigger
        )
    message = str(raised.value)
    assert "12345678901" not in message and "parameters hidden" in message
