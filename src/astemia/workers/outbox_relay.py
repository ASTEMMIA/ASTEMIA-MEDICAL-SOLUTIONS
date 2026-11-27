"""Outbox relay (DATA-02 step 7): publish committed events, at least once.

Rows are claimed with SELECT ... FOR UPDATE SKIP LOCKED so several relays can
run side by side. A crash after publish and before marking means the event is
sent again; consumers deduplicate by event ID (ConsumedEvent).
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.broker.base import Broker
from astemia.adapters.db.models import ConsumedEvent, OutboxEvent

log = logging.getLogger("astemia.outbox")
MAX_ATTEMPTS = 10


def envelope(e: OutboxEvent) -> dict[str, Any]:
    """DATA-03 event envelope."""
    return {
        "event_id": str(e.event_id),
        "tenant_id": str(e.tenant_id),
        "event_type": e.event_type,
        "schema_version": e.schema_version,
        "aggregate_type": e.aggregate_type,
        "aggregate_id": str(e.aggregate_id),
        "aggregate_version": e.aggregate_version,
        "effective_at": e.effective_at.isoformat(),
        "recorded_at": e.recorded_at.isoformat(),
        "actor": e.actor_subject,
        "source_system": e.source_system,
        "correlation_id": e.correlation_id,
        "payload": e.payload,
    }


def relay_once(factory: sessionmaker[Session], broker: Broker, batch: int = 100) -> int:
    now = datetime.now(UTC)
    sent = 0
    with factory() as session, session.begin():
        rows = (
            session.execute(
                select(OutboxEvent)
                .where(
                    OutboxEvent.published_at.is_(None),
                    OutboxEvent.available_at <= now,
                    OutboxEvent.attempts < MAX_ATTEMPTS,
                )
                .order_by(OutboxEvent.available_at, OutboxEvent.event_id)
                .limit(batch)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        for e in rows:
            try:
                broker.publish(f"astemia.{e.event_type}", str(e.aggregate_id), envelope(e))
            except Exception:  # broker fault: back off and retry later
                e.attempts += 1
                e.available_at = now + timedelta(seconds=min(2**e.attempts, 900))
                log.warning("publish failed for %s (attempt %s)", e.event_id, e.attempts)
                continue
            e.published_at = now
            e.attempts += 1
            sent += 1
    return sent


def consume_once(session: Session, consumer: str, event_id: Any) -> bool:
    """Record a consumed event inside the consumer's own transaction. Returns
    False when it was already processed, so the business effect is skipped."""
    if session.get(ConsumedEvent, (consumer, event_id)) is not None:
        return False
    session.add(ConsumedEvent(consumer=consumer, event_id=event_id, consumed_at=datetime.now(UTC)))
    session.flush()
    return True
