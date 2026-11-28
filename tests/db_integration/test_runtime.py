"""Write-path races and failures, the outbox relay's retry, and the CLI."""

import io
import json
import uuid
from contextlib import redirect_stdout
from datetime import UTC, date, datetime
from typing import Any

import jwt
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from astemia import cli
from astemia.adapters.db.models import Encounter, OutboxEvent, Party, Patient, Tenant
from astemia.adapters.db.session import default_session_factory, transaction
from astemia.application.commands import Commands
from astemia.application.context import Principal, RequestContext
from astemia.application.errors import NotFound
from astemia.application.policy import PilotPolicy
from astemia.application.schemas import AddressIn, RegisterPatient
from astemia.application.write_path import CommandResult, Unit, WritePath
from astemia.config import get_settings
from astemia.workers.outbox_relay import relay_once
from tests.fixtures.synthetic import ADDRESS, SyntheticTenant

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


def registrar(t: SyntheticTenant) -> RequestContext:
    return RequestContext(
        principal=Principal(
            subject=t.subject("registrar"),
            tenant_id=t.tenant_id,
            roles=frozenset({"registrar"}),
            practitioner_id=t.practitioners["registrar"],
        ),
        correlation_id="test-correlation-1",
    )


class RacyWritePath(WritePath):
    """Misses the stored key once, as a concurrent request would in the window
    between its replay check and its commit."""

    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        self.missed = False

    def _replay(self, *args: Any) -> CommandResult | None:  # type: ignore[override]
        if not self.missed:
            self.missed = True
            return None
        return super()._replay(*args)


def test_concurrent_duplicate_request_replays(
    factory: sessionmaker[Session], tenant: SyntheticTenant
) -> None:
    policy = PilotPolicy("test")
    cmd = RegisterPatient(
        family_name="Obi",
        given_names="Ada",
        birth_date=date(1990, 1, 1),
        administrative_sex="female",
        address=AddressIn.model_validate(ADDRESS),
    )
    ctx = registrar(tenant)
    first = Commands(WritePath(factory, policy)).register_patient(ctx, "race-key", cmd)
    second = Commands(RacyWritePath(factory, policy)).register_patient(ctx, "race-key", cmd)
    assert second.replayed and second.body == first.body
    with factory() as s:
        n = s.scalar(
            select(func.count()).select_from(Patient).where(Patient.tenant_id == tenant.tenant_id)
        )
    assert n == 1  # the losing request's writes were rolled back


def test_missing_parent_is_not_found(
    factory: sessionmaker[Session], tenant: SyntheticTenant
) -> None:
    def handler(u: Unit) -> CommandResult:
        u.session.add(
            Encounter(
                tenant_id=u.ctx.tenant_id,
                id=uuid.uuid7(),
                recorded_at=NOW,
                patient_id=uuid.uuid7(),
                facility_id=tenant.facility_id,
                responsible_practitioner_id=tenant.practitioners["clinician"],
                visit_authority="T",
                visit_number="X1",
                encounter_class="inpatient",
                service="med",
                state="in_progress",
                period_start=NOW,
            )
        )
        u.session.flush()
        return CommandResult(201, {})

    wp = WritePath(factory, PilotPolicy("test"))
    with pytest.raises(NotFound, match="does not exist in this tenant"):
        wp.run(
            registrar(tenant),
            operation="t.fk",
            capability="encounter:admit",
            idempotency_key="k-fk",
            payload={},
            handler=handler,
        )


def test_other_integrity_errors_are_not_masked(
    factory: sessionmaker[Session], tenant: SyntheticTenant
) -> None:
    def handler(u: Unit) -> CommandResult:
        u.session.add(
            Party(tenant_id=u.ctx.tenant_id, id=uuid.uuid7(), recorded_at=NOW, party_type=None)
        )
        u.session.flush()
        return CommandResult(201, {})

    wp = WritePath(factory, PilotPolicy("test"))
    with pytest.raises(IntegrityError):
        wp.run(
            registrar(tenant),
            operation="t.null",
            capability="encounter:admit",
            idempotency_key="k-null",
            payload={},
            handler=handler,
        )


def test_transaction_helper_commits(
    factory: sessionmaker[Session], tenant: SyntheticTenant
) -> None:
    pid = uuid.uuid7()
    with transaction(factory) as s:
        s.add(Party(tenant_id=tenant.tenant_id, id=pid, recorded_at=NOW, party_type="person"))
    with factory() as s:
        assert s.get(Party, (tenant.tenant_id, pid)) is not None
    assert default_session_factory() is default_session_factory()


class FailingBroker:
    def publish(self, topic: str, key: str, envelope: dict[str, Any]) -> None:
        raise ConnectionError("broker unavailable")


def test_relay_backs_off_when_the_broker_fails(
    factory: sessionmaker[Session], tenant: SyntheticTenant
) -> None:
    eid = uuid.uuid7()
    with factory() as s, s.begin():
        s.add(
            OutboxEvent(
                event_id=eid,
                tenant_id=tenant.tenant_id,
                event_type="t.event",
                schema_version=1,
                aggregate_type="t",
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
    while relay_once(factory, FailingBroker()):  # nothing is ever marked sent
        pass
    with factory() as s:
        e = s.get(OutboxEvent, eid)
        assert e is not None and e.published_at is None and e.attempts == 1
        assert e.available_at > datetime.now(UTC)  # retried later, with backoff


def run_cli(argv: list[str], factory: sessionmaker[Session]) -> str:
    out = io.StringIO()
    with redirect_stdout(out):
        cli.main(argv, factory=factory)
    return out.getvalue()


def test_cli_seed_dev_creates_a_tenant_once(factory: sessionmaker[Session]) -> None:
    tid = uuid.uuid7()
    ids = json.loads(run_cli(["seed-dev", "--tenant", str(tid)], factory))
    assert ids["tenant_id"] == str(tid)
    assert {"facility_id", "clinician_practitioner_id", "scientist_practitioner_id"} <= ids.keys()
    with factory() as s:
        assert s.get(Tenant, tid) is not None
    with pytest.raises(SystemExit):
        run_cli(["seed-dev", "--tenant", str(tid)], factory)


def test_cli_token_is_a_verifiable_bearer_token(factory: sessionmaker[Session]) -> None:
    tid = uuid.uuid7()
    token = run_cli(
        ["token", "clinician@pilot.astemia.local", "--tenant", str(tid)], factory
    ).strip()
    s = get_settings()
    claims = jwt.decode(
        token,
        s.jwt_key.get_secret_value(),
        algorithms=[s.jwt_algorithm],
        audience=s.jwt_audience,
        issuer=s.jwt_issuer,
    )
    assert claims["sub"] == "clinician@pilot.astemia.local" and claims["tid"] == str(tid)


def test_cli_relay_runs_bounded_cycles(
    factory: sessionmaker[Session], tenant: SyntheticTenant
) -> None:
    eid = uuid.uuid7()
    with factory() as s, s.begin():
        s.add(
            OutboxEvent(
                event_id=eid,
                tenant_id=tenant.tenant_id,
                event_type="t.cli",
                schema_version=1,
                aggregate_type="t",
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
    run_cli(["relay", "--max-cycles", "5", "--interval", "0"], factory)
    with factory() as s:
        assert s.get(OutboxEvent, eid).published_at is not None  # type: ignore[union-attr]


def test_run_relay_sleeps_only_when_idle(factory: sessionmaker[Session]) -> None:
    slept: list[float] = []
    published = cli.run_relay(
        factory, FailingBroker(), interval=0.5, max_cycles=2, sleep=slept.append
    )
    assert published == 0 and slept == [0.5, 0.5]
