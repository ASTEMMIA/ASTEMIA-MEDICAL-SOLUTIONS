"""The write path every command follows (CEDA 10.3, DATA-02, API-02).

1. Tenant bound from verified identity (done by the API before we get here).
2. Access decision; deny early, concealed where policy requires.
3. Idempotency-Key scoped to tenant, principal and operation.
4. Aggregate loaded under lock and expected version compared.
5. Domain transition, which raises on a broken invariant.
6. State, revision, audit intent and outbox event committed together.
7. The relay publishes after commit (astemia.workers.outbox_relay).
"""

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, NoReturn

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import AuditEvent, IdempotencyRecord, OutboxEvent
from astemia.application.context import RequestContext
from astemia.application.errors import (
    AccessDenied,
    Conflict,
    IdempotencyConflict,
    NotFound,
    PreconditionRequired,
    StaleVersion,
)
from astemia.application.policy import Decision, PolicyEngine
from astemia.domain.events import SCHEMA_VERSION, EventType

# Unique constraints whose violation is a business conflict, not a fault.
CONSTRAINT_CONFLICTS = {
    "uq_patient_identifier_tenant_id_issuer_value_active_marker": "identifier_already_bound",
    "uq_encounter_tenant_id_visit_authority_visit_number": "visit_number_exists",
    "uq_service_request_tenant_id_placer_authority_placer_id": "placer_id_exists",
    "uq_service_request_tenant_id_filler_authority_filler_id": "filler_id_exists",
    "uq_ae_attendance_tenant_id_attendance_number": "ae_attendance_number_exists",
    "uq_slot_tenant_id_practitioner_id_starts_at": "slot_exists",
    "uq_slot_hold_tenant_id_slot_id_live_marker": "slot_held",
    "uq_appointment_tenant_id_slot_id_booked_marker": "slot_booked",
    "uq_ward_tenant_id_code": "ward_code_exists",
    "uq_bed_tenant_id_ward_id_code": "bed_code_exists",
    # Two requests raced for one bed, or one encounter: the database keeps one.
    "uq_bed_occupancy_tenant_id_bed_id_active_marker": "bed_occupied",
    "uq_bed_occupancy_tenant_id_encounter_id_active_marker": "already_in_bed",
    "uq_theatre_tenant_id_code": "theatre_code_exists",
}


@dataclass(slots=True)
class CommandResult:
    status_code: int
    body: dict[str, Any]
    replayed: bool = False


@dataclass(slots=True)
class Unit:
    """What a command handler gets: the open transaction and helpers that keep
    audit and outbox inside it."""

    session: Session
    ctx: RequestContext
    policy: PolicyEngine
    events: list[uuid.UUID] = field(default_factory=list)

    def authorize(self, capability: str, *, patient_id: uuid.UUID | None = None) -> Decision:
        decision = self.policy.decide(self.session, self.ctx, capability, patient_id=patient_id)
        if not decision.allowed:
            raise _Denied(decision, capability, patient_id)
        return decision

    def get[T](self, model: type[T], id_: uuid.UUID, *, lock: bool = False) -> T:
        """Tenant-scoped load. A row in another tenant is simply not found."""
        stmt = select(model).where(
            model.tenant_id == self.ctx.tenant_id,  # type: ignore[attr-defined]
            model.id == id_,  # type: ignore[attr-defined]
        )
        if lock:
            stmt = stmt.with_for_update()
        row = self.session.execute(stmt).scalar_one_or_none()
        if row is None:
            raise NotFound(f"{model.__name__} not found")
        return row

    def deny(
        self, reason: str, *, conceal: bool = False, patient_id: uuid.UUID | None = None
    ) -> NoReturn:
        """Refuse after a resource-level check; the denial is audited."""
        decision = Decision(False, uuid.uuid7(), self.policy.version, reason, conceal=conceal)
        raise _Denied(decision, reason, patient_id)

    @staticmethod
    def check_version(current: int, expected: int | None) -> None:
        if expected is None:
            raise PreconditionRequired("If-Match with the expected version is required")
        if current != expected:
            raise StaleVersion(f"expected version {expected}, current is {current}")

    def audit(
        self,
        decision: Decision,
        action: str,
        resource_type: str,
        resource_id: uuid.UUID | None,
        *,
        patient_id: uuid.UUID | None = None,
        outcome: str = "success",
        event_id: uuid.UUID | None = None,
    ) -> None:
        self.session.add(
            audit_row(
                self.ctx,
                decision,
                action,
                resource_type,
                resource_id,
                patient_id,
                outcome,
                event_id,
            )
        )

    def emit(
        self,
        event_type: EventType,
        aggregate_type: str,
        aggregate_id: uuid.UUID,
        aggregate_version: int,
        effective_at: datetime,
        payload: dict[str, Any],
    ) -> uuid.UUID:
        event_id = uuid.uuid7()
        self.session.add(
            OutboxEvent(
                event_id=event_id,
                tenant_id=self.ctx.tenant_id,
                event_type=event_type.value,
                schema_version=SCHEMA_VERSION[event_type],
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                aggregate_version=aggregate_version,
                effective_at=effective_at,
                recorded_at=self.ctx.now,
                actor_subject=self.ctx.principal.subject,
                source_system="astemia",
                correlation_id=self.ctx.correlation_id,
                payload=payload,
                available_at=self.ctx.now,
            )
        )
        self.events.append(event_id)
        return event_id


class _Denied(Exception):
    def __init__(self, decision: Decision, capability: str, patient_id: uuid.UUID | None):
        self.decision, self.capability, self.patient_id = decision, capability, patient_id


def audit_row(
    ctx: RequestContext,
    decision: Decision,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None,
    patient_id: uuid.UUID | None,
    outcome: str,
    event_id: uuid.UUID | None = None,
) -> AuditEvent:
    return AuditEvent(
        tenant_id=ctx.tenant_id,
        id=uuid.uuid7(),
        occurred_at=ctx.now,
        actor_subject=ctx.principal.subject,
        actor_practitioner_id=ctx.principal.practitioner_id,
        purpose=ctx.purpose,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        patient_id=patient_id,
        outcome=outcome,
        policy_version=decision.policy_version,
        decision_id=decision.decision_id,
        # A plain permit needs no reason; a denial or an emergency grant does.
        reason_code=None if decision.allowed and decision.reason == "permit" else decision.reason,
        correlation_id=ctx.correlation_id,
        event_id=event_id,
    )


def request_digest(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


class WritePath:
    def __init__(self, factory: sessionmaker[Session], policy: PolicyEngine) -> None:
        self.factory = factory
        self.policy = policy

    def run(
        self,
        ctx: RequestContext,
        *,
        operation: str,
        capability: str,
        idempotency_key: str | None,
        payload: Any,
        handler: Callable[[Unit], CommandResult],
        patient_id: uuid.UUID | None = None,
        resource: tuple[str, uuid.UUID] | None = None,
    ) -> CommandResult:
        """`operation` is a fixed action name: it names the audit action and
        scopes the Idempotency-Key. The record a command acts on goes in
        `payload` (so a key stays bound to it) and in `resource` (so a refusal
        names it)."""
        if not idempotency_key:
            raise PreconditionRequired(
                "Idempotency-Key header is required", code="idempotency_key_required"
            )
        digest = request_digest(payload)
        try:
            with self.factory() as session, session.begin():
                unit = Unit(session, ctx, self.policy)
                # Step 2 runs before any replay: a replay never leaks an outcome
                # to a caller who is no longer authorised.
                unit.authorize(capability, patient_id=patient_id)
                replay = self._replay(session, ctx, operation, idempotency_key, digest)
                if replay is not None:
                    return replay
                result = handler(unit)
                session.add(
                    IdempotencyRecord(
                        tenant_id=ctx.tenant_id,
                        principal=ctx.principal.subject,
                        operation=operation,
                        idempotency_key=idempotency_key,
                        request_digest=digest,
                        status_code=result.status_code,
                        response_body=result.body,
                    )
                )
                session.flush()
            return result
        except _Denied as denied:
            self._audit_denial(ctx, denied, operation, resource)
            raise AccessDenied(
                denied.decision.reason, code=denied.decision.reason, conceal=denied.decision.conceal
            ) from None
        except IntegrityError as exc:
            return self._resolve_integrity(ctx, operation, idempotency_key, digest, exc)

    def _replay(
        self, session: Session, ctx: RequestContext, operation: str, key: str, digest: str
    ) -> CommandResult | None:
        rec = session.get(IdempotencyRecord, (ctx.tenant_id, ctx.principal.subject, operation, key))
        if rec is None:
            return None
        if rec.request_digest != digest:
            raise IdempotencyConflict("Idempotency-Key was used with different content")
        return CommandResult(rec.status_code, rec.response_body, replayed=True)

    def _resolve_integrity(
        self, ctx: RequestContext, operation: str, key: str, digest: str, exc: IntegrityError
    ) -> CommandResult:
        # A concurrent request with the same key committed first: replay it.
        with self.factory() as session:
            replay = self._replay(session, ctx, operation, key, digest)
        if replay is not None:
            return replay
        message = str(exc.orig)
        for constraint, code in CONSTRAINT_CONFLICTS.items():
            if constraint in message:
                raise Conflict(code.replace("_", " "), code=code) from None
        if "foreign key constraint fails" in message:
            raise NotFound("a referenced record does not exist in this tenant") from None
        raise exc

    def _audit_denial(
        self,
        ctx: RequestContext,
        denied: _Denied,
        operation: str,
        resource: tuple[str, uuid.UUID] | None,
    ) -> None:
        resource_type, resource_id = resource or ("capability", None)
        with self.factory() as session, session.begin():
            session.add(
                audit_row(
                    ctx,
                    denied.decision,
                    operation,
                    resource_type,
                    resource_id,
                    denied.patient_id,
                    "denied",
                )
            )


def read_path[T](
    factory: sessionmaker[Session],
    policy: PolicyEngine,
    ctx: RequestContext,
    *,
    capability: str,
    action: str,
    resource_type: str,
    patient_id: uuid.UUID | None,
    reader: Callable[[Session, Decision], T],
) -> T:
    """Scoped query: decide, read with masks, and commit the audit event before
    any data leaves the service (API-03)."""
    with factory() as session:
        decision = policy.decide(session, ctx, capability, patient_id=patient_id)
        if not decision.allowed:
            session.add(
                audit_row(ctx, decision, action, resource_type, patient_id, patient_id, "denied")
            )
            session.commit()
            raise AccessDenied(decision.reason, code=decision.reason, conceal=decision.conceal)
        result = reader(session, decision)
        session.add(
            audit_row(ctx, decision, action, resource_type, patient_id, patient_id, "success")
        )
        session.commit()
    return result
