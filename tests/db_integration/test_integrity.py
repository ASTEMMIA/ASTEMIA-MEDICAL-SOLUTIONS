"""DATA-01/02 and MIG-02 properties, enforced by MySQL itself."""

import hashlib
import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.broker.base import LoggingBroker
from astemia.adapters.db.models import (
    STAGING_TABLES,
    ConsumedEvent,
    Encounter,
    OutboxEvent,
    Party,
    Patient,
    PatientIdentifier,
)
from astemia.workers.outbox_relay import consume_once, relay_once
from tests.fixtures.synthetic import SyntheticTenant, make_tenant

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


def add_patient(s: Session, tid: uuid.UUID) -> uuid.UUID:
    pid = uuid.uuid7()
    s.add(Party(tenant_id=tid, id=pid, recorded_at=NOW, party_type="person"))
    s.flush()
    s.add(
        Patient(
            tenant_id=tid,
            id=pid,
            recorded_at=NOW,
            administrative_sex="female",
            birth_date=date(1990, 5, 1),
            birth_date_precision="day",
            status="active",
        )
    )
    s.flush()
    return pid


def test_cross_tenant_parent_is_rejected(
    factory: sessionmaker[Session], tenant: SyntheticTenant
) -> None:
    """DATA-01: an encounter cannot point at another tenant's patient."""
    other = make_tenant(factory)
    with factory() as s, s.begin():
        foreign_patient = add_patient(s, other.tenant_id)
    with (
        pytest.raises(IntegrityError, match="foreign key constraint fails"),
        factory() as s,
        s.begin(),
    ):
        s.add(
            Encounter(
                tenant_id=tenant.tenant_id,
                id=uuid.uuid7(),
                recorded_at=NOW,
                patient_id=foreign_patient,
                facility_id=tenant.facility_id,
                responsible_practitioner_id=tenant.practitioners["clinician"],
                visit_authority="T",
                visit_number="V1",
                encounter_class="inpatient",
                service="med",
                state="in_progress",
                period_start=NOW,
            )
        )


def test_active_identifier_binds_once_but_can_be_rebound_after_retirement(
    factory: sessionmaker[Session], tenant: SyntheticTenant
) -> None:
    tid = tenant.tenant_id

    def ident(pid: uuid.UUID, active: int | None) -> PatientIdentifier:
        return PatientIdentifier(
            tenant_id=tid,
            id=uuid.uuid7(),
            recorded_at=NOW,
            patient_id=pid,
            issuer="NG-NIN",
            value="12345678901",
            verification_status="verified",
            valid_from=NOW,
            active_marker=active,
        )

    with factory() as s, s.begin():
        a, b = add_patient(s, tid), add_patient(s, tid)
        first = ident(a, 1)
        s.add(first)
    with pytest.raises(IntegrityError, match="uq_patient_identifier"), factory() as s, s.begin():
        s.add(ident(b, 1))
    with factory() as s, s.begin():
        s.get(PatientIdentifier, (tid, first.id)).active_marker = None  # type: ignore[union-attr]
        s.add(ident(b, 1))


def test_outbox_relay_publishes_once_and_consumers_deduplicate(
    factory: sessionmaker[Session], tenant: SyntheticTenant
) -> None:
    eid = uuid.uuid7()
    with factory() as s, s.begin():
        s.add(
            OutboxEvent(
                event_id=eid,
                tenant_id=tenant.tenant_id,
                event_type="test.event",
                schema_version=1,
                aggregate_type="test",
                aggregate_id=uuid.uuid7(),
                aggregate_version=1,
                effective_at=NOW,
                recorded_at=NOW,
                actor_subject="t",
                source_system="astemia",
                correlation_id="c" * 16,
                payload={},
                available_at=NOW,
            )
        )
    broker = LoggingBroker()
    while relay_once(factory, broker):
        pass
    assert [e["event_id"] for e in broker.published].count(str(eid)) == 1
    with factory() as s:
        assert s.get(OutboxEvent, eid).published_at is not None  # type: ignore[union-attr]
    with factory() as s, s.begin():
        assert consume_once(s, "chart-projection", eid) is True
    with factory() as s, s.begin():
        assert consume_once(s, "chart-projection", eid) is False
        assert (
            s.scalar(
                select(func.count()).select_from(ConsumedEvent).where(ConsumedEvent.event_id == eid)
            )
            == 1
        )


def test_staging_reload_adds_zero_duplicates(
    factory: sessionmaker[Session], tenant: SyntheticTenant
) -> None:
    """MIG-02: re-running a batch adds zero duplicates."""
    table = STAGING_TABLES["stg_person"]
    row = {
        "tenant_id": tenant.tenant_id,
        "batch_id": uuid.uuid7(),
        "source_system": "PDI",
        "source_entity": "Person",
        "source_row_key": "P-1",
        "mapping_version": "g6-0.1",
        "loaded_at": NOW,
        "nin": "12345678901",
        "gender": "F",
    }
    row["row_digest"] = hashlib.sha256(b"P-1|12345678901|F").hexdigest()
    with factory() as s, s.begin():
        s.execute(insert(table).values(id=uuid.uuid7(), **row))
    with pytest.raises(IntegrityError), factory() as s, s.begin():
        s.execute(insert(table).values(id=uuid.uuid7(), **row))
