"""Emergency access (CEDA SEC-04, WF02 step 4; SA-04 EmergencyGrant).

A clinician with no care relationship states a purpose and gets read-only
access to one patient's chart for 30 minutes. The policy re-checks the grant at
every read, so the first read after expiry is refused. Each grant raises a
privacy alert (an outbox event) and waits in a review queue that a privacy
officer clears within one working day.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import EmergencyGrant, Patient
from astemia.application.context import RequestContext
from astemia.application.errors import Conflict, Unprocessable
from astemia.application.policy import Decision, PolicyEngine
from astemia.application.schemas import (
    EmergencyGrantOut,
    RequestEmergencyAccess,
    ReviewEmergencyAccess,
)
from astemia.application.write_path import CommandResult, Unit, WritePath, read_path
from astemia.domain import access as acc
from astemia.domain.common import DomainError, new_id
from astemia.domain.events import EventType


def grant_out(row: EmergencyGrant, at: datetime) -> EmergencyGrantOut:
    return EmergencyGrantOut(
        id=row.id,
        version=row.version,
        patient_id=row.patient_id,
        practitioner_id=row.practitioner_id,
        purpose=row.purpose,
        scope=row.scope,
        starts_at=row.starts_at,
        expires_at=row.expires_at,
        live=acc.is_live(row.starts_at, row.expires_at, at),
        step_up=row.step_up,
        review_due_at=row.review_due_at,
        review_overdue=row.reviewed_at is None and at > row.review_due_at,
        reviewed_at=row.reviewed_at,
        reviewed_by_id=row.reviewed_by_id,
        review_outcome=row.review_outcome,
        review_note=row.review_note,
    )


class EmergencyAccess:
    def __init__(
        self, write_path: WritePath, factory: sessionmaker[Session], policy: PolicyEngine
    ) -> None:
        self.wp = write_path
        self.factory = factory
        self.policy = policy

    def request(
        self, ctx: RequestContext, key: str | None, cmd: RequestEmergencyAccess
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            me = u.ctx.principal.practitioner_id
            if me is None:
                u.deny("no_practitioner", patient_id=cmd.patient_id)
            assert me is not None
            patient = u.get(Patient, cmd.patient_id)
            if self.policy.decide(u.session, u.ctx, "chart:read", patient_id=patient.id).allowed:
                raise Conflict(
                    "you can already read this chart; emergency access is not needed",
                    code="access_not_needed",
                )
            live = u.session.execute(
                select(EmergencyGrant.id).where(
                    EmergencyGrant.tenant_id == u.ctx.tenant_id,
                    EmergencyGrant.practitioner_id == me,
                    EmergencyGrant.expires_at > u.ctx.now,
                )
            ).first()
            if live is not None:
                raise Conflict(
                    "emergency access covers one patient at a time; another grant is still live",
                    code="grant_active",
                )
            grant = EmergencyGrant(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                version=1,
                recorded_at=u.ctx.now,
                effective_at=u.ctx.now,
                author_id=me,
                author_role="clinician",
                patient_id=patient.id,
                practitioner_id=me,
                purpose=cmd.purpose,
                scope=acc.GRANT_SCOPE,
                starts_at=u.ctx.now,
                expires_at=acc.expires_at(u.ctx.now),
                step_up=acc.StepUp.NOT_AVAILABLE.value,
                review_due_at=acc.review_due(u.ctx.now),
            )
            u.session.add(grant)
            u.session.flush()
            decision = u.authorize("emergency:request")
            # The privacy alert. The purpose stays out of the event: it can hold
            # clinical detail, and the reviewer reads it from the grant.
            event = u.emit(
                EventType.EMERGENCY_ACCESS_GRANTED,
                "emergency_grant",
                grant.id,
                1,
                u.ctx.now,
                {
                    "grant_id": str(grant.id),
                    "patient_id": str(patient.id),
                    "practitioner_id": str(me),
                    "expires_at": grant.expires_at.isoformat(),
                    "review_due_at": grant.review_due_at.isoformat(),
                },
            )
            u.audit(
                decision,
                "emergency_access.grant",
                "emergency_grant",
                grant.id,
                patient_id=patient.id,
                event_id=event,
            )
            return CommandResult(201, grant_out(grant, u.ctx.now).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="emergency_access.grant",
            capability="emergency:request",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json"),
            handler=handle,
        )

    def grants(self, ctx: RequestContext, *, reviewed: bool, limit: int) -> list[EmergencyGrantOut]:
        def read(session: Session, decision: Decision) -> list[EmergencyGrantOut]:
            done = EmergencyGrant.reviewed_at.is_not(None)
            rows = session.execute(
                select(EmergencyGrant)
                .where(
                    EmergencyGrant.tenant_id == ctx.tenant_id,
                    done if reviewed else ~done,
                )
                .order_by(EmergencyGrant.review_due_at, EmergencyGrant.id)
                .limit(limit)
            ).scalars()
            return [grant_out(r, ctx.now) for r in rows]

        return read_path(
            self.factory,
            self.policy,
            ctx,
            capability="emergency:review",
            action="emergency_access.list",
            resource_type="emergency_grant",
            patient_id=None,
            reader=read,
        )

    def review(
        self,
        ctx: RequestContext,
        key: str | None,
        grant_id: uuid.UUID,
        expected: int | None,
        cmd: ReviewEmergencyAccess,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            me = u.ctx.principal.practitioner_id
            if me is None:
                u.deny("no_practitioner")
            grant = u.get(EmergencyGrant, grant_id, lock=True)
            if grant.practitioner_id == me:
                u.deny("own_grant", patient_id=grant.patient_id)
            u.check_version(grant.version, expected)
            try:
                acc.check_reviewable(grant.reviewed_at is not None)
            except DomainError as exc:
                raise Unprocessable(str(exc), code=exc.code) from None
            grant.reviewed_at, grant.reviewed_by_id = u.ctx.now, me
            grant.review_outcome, grant.review_note = cmd.outcome, cmd.note
            grant.version += 1
            decision = u.authorize("emergency:review")
            event = u.emit(
                EventType.EMERGENCY_ACCESS_REVIEWED,
                "emergency_grant",
                grant.id,
                grant.version,
                u.ctx.now,
                {"grant_id": str(grant.id), "outcome": cmd.outcome},
            )
            u.audit(
                decision,
                "emergency_access.review",
                "emergency_grant",
                grant.id,
                patient_id=grant.patient_id,
                event_id=event,
            )
            return CommandResult(200, grant_out(grant, u.ctx.now).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="emergency_access.review",
            capability="emergency:review",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"grant_id": str(grant_id), "v": expected},
            handler=handle,
            resource=("emergency_grant", grant_id),
        )
