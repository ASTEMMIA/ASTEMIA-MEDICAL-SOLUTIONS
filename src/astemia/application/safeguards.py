"""Mental health safeguards (CEDA HS13, B11; ICRS 5.5.9-5.5.15).

Four records make the fair treatment of a mental health patient checkable:

* restrictive interventions (restraint, seclusion, rapid tranquillisation),
  never edited or deleted, each reviewed by a safeguarding lead who took no
  part in it, and flagged when the patient was informal, had no recorded legal
  status or was held under a lapsed power;
* the patient's legal status, with its history, expiry warnings and lapse;
* concerns raised by the patient, family, an advocate or staff, answered by a
  safeguarding lead who is not the subject of the concern;
* an access report of everyone who read or changed the patient's records,
  for a safeguarding lead or the patient's appointed advocate.

Every read and write here is audited, and the free text (reasons, notes,
descriptions) never goes into events.
"""

import uuid
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import (
    AuditEvent,
    Encounter,
    LegitimateRelationship,
    Membership,
    MentalHealthLegalStatus,
    Patient,
    Practitioner,
    RestrictiveIntervention,
    SafeguardingConcern,
)
from astemia.application import views
from astemia.application.context import RequestContext
from astemia.application.errors import AccessDenied, Unprocessable
from astemia.application.policy import RELATIONSHIP_BOUND, Decision, PolicyEngine
from astemia.application.schemas import (
    AccessEntry,
    AccessReportOut,
    ActorSummary,
    AppointAdvocate,
    CloseConcern,
    ConcernOut,
    EndIntervention,
    InterventionOut,
    LegalStatusOut,
    RaiseConcern,
    RecordIntervention,
    ReviewIntervention,
    SetLegalStatus,
)
from astemia.application.write_path import CommandResult, Unit, WritePath, audit_row
from astemia.domain import safeguards as sg
from astemia.domain.access import review_due
from astemia.domain.common import DomainError, new_id
from astemia.domain.events import EventType

SENSITIVITY = "mental_health"
REPORT_WINDOW = timedelta(days=90)


def _domain(fn: Any) -> Any:
    try:
        return fn()
    except DomainError as exc:
        raise Unprocessable(str(exc), code=exc.code) from None


def _envelope(u: Unit) -> dict[str, Any]:
    return {
        "tenant_id": u.ctx.tenant_id,
        "id": new_id(),
        "version": 1,
        "recorded_at": u.ctx.now,
        "author_id": u.ctx.principal.practitioner_id,
        "author_role": ",".join(u.ctx.principal.roles)[:64],
        "sensitivity": SENSITIVITY,
    }


def _reviewer(u: Unit) -> uuid.UUID:
    me = u.ctx.principal.practitioner_id
    if me is None:
        u.deny("no_practitioner")
    assert me is not None
    return me


def intervention_out(row: RestrictiveIntervention, at: datetime) -> InterventionOut:
    minutes = int((row.ended_at - row.started_at).total_seconds() // 60) if row.ended_at else None
    return InterventionOut(
        id=row.id,
        version=row.version,
        patient_id=row.patient_id,
        encounter_id=row.encounter_id,
        intervention_type=row.intervention_type,
        reason=row.reason,
        authorised_by_id=row.authorised_by_id,
        recorded_by_id=row.author_id,
        staff_ids=[uuid.UUID(s) for s in row.staff_ids],
        started_at=row.started_at,
        ended_at=row.ended_at,
        duration_minutes=minutes,
        injury=row.injury,
        injury_detail=row.injury_detail,
        debrief_offered=row.debrief_offered,
        legal_status_id=row.legal_status_id,
        flags=row.flags,
        review_due_at=row.review_due_at,
        review_overdue=row.reviewed_at is None and at > row.review_due_at,
        reviewed_at=row.reviewed_at,
        reviewed_by_id=row.reviewed_by_id,
        review_outcome=row.review_outcome,
        review_note=row.review_note,
    )


def concern_out(row: SafeguardingConcern, at: datetime) -> ConcernOut:
    return ConcernOut(
        id=row.id,
        version=row.version,
        patient_id=row.patient_id,
        raised_by=row.raised_by,
        raised_by_name=row.raised_by_name,
        recorded_by=row.source_id,
        category=row.category,
        description=row.description,
        about_practitioner_id=row.about_practitioner_id,
        status=row.status,
        respond_by=row.respond_by,
        overdue=row.status == sg.ConcernStatus.OPEN and at > row.respond_by,
        closed_at=row.closed_at,
        closed_by_id=row.closed_by_id,
        outcome_note=row.outcome_note,
        recorded_at=row.recorded_at,
    )


class Safeguards:
    def __init__(
        self, write_path: WritePath, factory: sessionmaker[Session], policy: PolicyEngine
    ) -> None:
        self.wp = write_path
        self.factory = factory
        self.policy = policy

    # -- reads: decided, audited, then returned ---------------------------------------

    def _read[T](
        self,
        ctx: RequestContext,
        *,
        capabilities: tuple[str, ...],
        action: str,
        patient_id: uuid.UUID | None,
        reader: Callable[[Session, Decision], T],
    ) -> T:
        """The first capability the caller holds decides. A relationship-bound
        one (an advocate's or the care team's) needs a relationship with the
        patient; a safeguarding lead's does not."""
        with self.factory() as session:
            decision: Decision | None = None
            for capability in capabilities:
                bound = capability in RELATIONSHIP_BOUND
                decision = self.policy.decide(
                    session, ctx, capability, patient_id=patient_id if bound else None
                )
                if decision.allowed:
                    break
            assert decision is not None
            if not decision.allowed:
                session.add(
                    audit_row(ctx, decision, action, "patient", patient_id, patient_id, "denied")
                )
                session.commit()
                raise AccessDenied(
                    decision.reason, code=decision.reason, conceal=patient_id is not None
                )
            # A lead's capability is not bound to a relationship, so nothing
            # above has looked the patient up: one outside this tenant (or no
            # patient at all) is concealed like any other (tenant isolation).
            if patient_id is not None and session.get(Patient, (ctx.tenant_id, patient_id)) is None:
                session.add(audit_row(ctx, decision, action, "patient", patient_id, None, "denied"))
                session.commit()
                raise AccessDenied("not found", code="not_found", conceal=True)
            result = reader(session, decision)
            session.add(
                audit_row(ctx, decision, action, "patient", patient_id, patient_id, "success")
            )
            session.commit()
        return result

    # -- restrictive interventions ----------------------------------------------------

    def record_intervention(
        self, ctx: RequestContext, key: str | None, cmd: RecordIntervention
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            _domain(lambda: sg.check_intervention(cmd.started_at, cmd.ended_at, u.ctx.now))
            patient = u.get(Patient, cmd.patient_id)
            if cmd.encounter_id is not None:
                encounter = u.get(Encounter, cmd.encounter_id)
                if encounter.patient_id != patient.id:
                    raise Unprocessable(
                        "encounter does not belong to this patient",
                        code="encounter_patient_mismatch",
                    )
            for pid in {cmd.authorised_by_id, *cmd.staff_ids}:
                u.get(Practitioner, pid)
            legal = views.current_legal_status(u.session, u.ctx.tenant_id, patient.id)
            flags = sg.intervention_flags(
                sg.LegalStatus(legal.status) if legal else None,
                legal.valid_until if legal else None,
                cmd.injury,
                cmd.started_at,
            )
            row = RestrictiveIntervention(
                patient_id=patient.id,
                encounter_id=cmd.encounter_id,
                intervention_type=cmd.intervention_type.value,
                reason=cmd.reason,
                authorised_by_id=cmd.authorised_by_id,
                staff_ids=[str(s) for s in cmd.staff_ids],
                started_at=cmd.started_at,
                ended_at=cmd.ended_at,
                effective_at=cmd.started_at,
                injury=cmd.injury,
                injury_detail=cmd.injury_detail,
                debrief_offered=cmd.debrief_offered,
                legal_status_id=legal.id if legal else None,
                flags=[f.value for f in flags],
                review_due_at=review_due(u.ctx.now),
                **_envelope(u),
            )
            u.session.add(row)
            u.session.flush()
            decision = u.authorize("safeguarding:record", patient_id=patient.id)
            event = u.emit(
                EventType.RESTRICTIVE_INTERVENTION_RECORDED,
                "restrictive_intervention",
                row.id,
                1,
                cmd.started_at,
                {
                    "intervention_id": str(row.id),
                    "patient_id": str(patient.id),
                    "type": row.intervention_type,
                    "flags": row.flags,
                    "review_due_at": row.review_due_at.isoformat(),
                },
            )
            u.audit(
                decision,
                "restrictive_intervention.record",
                "restrictive_intervention",
                row.id,
                patient_id=patient.id,
                event_id=event,
            )
            return CommandResult(201, intervention_out(row, u.ctx.now).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="restrictive_intervention.record",
            capability="safeguarding:record",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json"),
            handler=handle,
            patient_id=cmd.patient_id,
        )

    def end_intervention(
        self,
        ctx: RequestContext,
        key: str | None,
        intervention_id: uuid.UUID,
        expected: int | None,
        cmd: EndIntervention,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            row = u.get(RestrictiveIntervention, intervention_id, lock=True)
            u.check_version(row.version, expected)
            if row.ended_at is not None:
                raise Unprocessable("this intervention has already ended", code="already_ended")
            _domain(lambda: sg.check_intervention(row.started_at, cmd.ended_at, u.ctx.now))
            row.ended_at, row.debrief_offered = cmd.ended_at, cmd.debrief_offered
            if cmd.injury:
                row.injury, row.injury_detail = True, cmd.injury_detail
                if sg.Flag.INJURY.value not in row.flags:
                    row.flags = [*row.flags, sg.Flag.INJURY.value]
            row.version += 1
            decision = u.authorize("safeguarding:record", patient_id=row.patient_id)
            event = u.emit(
                EventType.RESTRICTIVE_INTERVENTION_ENDED,
                "restrictive_intervention",
                row.id,
                row.version,
                cmd.ended_at,
                {"intervention_id": str(row.id), "patient_id": str(row.patient_id)},
            )
            u.audit(
                decision,
                "restrictive_intervention.end",
                "restrictive_intervention",
                row.id,
                patient_id=row.patient_id,
                event_id=event,
            )
            return CommandResult(200, intervention_out(row, u.ctx.now).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="restrictive_intervention.end",
            capability="safeguarding:record",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json")
            | {"intervention_id": str(intervention_id), "v": expected},
            handler=handle,
            resource=("restrictive_intervention", intervention_id),
            # Recording is bound to a care relationship with the patient.
            patient_id=self._patient_of(ctx, intervention_id),
        )

    def _patient_of(self, ctx: RequestContext, intervention_id: uuid.UUID) -> uuid.UUID | None:
        """An unknown intervention gives no patient, which the policy refuses
        as not found."""
        with self.factory() as session:
            return session.execute(
                select(RestrictiveIntervention.patient_id).where(
                    RestrictiveIntervention.tenant_id == ctx.tenant_id,
                    RestrictiveIntervention.id == intervention_id,
                )
            ).scalar_one_or_none()

    def review_intervention(
        self,
        ctx: RequestContext,
        key: str | None,
        intervention_id: uuid.UUID,
        expected: int | None,
        cmd: ReviewIntervention,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            me = _reviewer(u)
            row = u.get(RestrictiveIntervention, intervention_id, lock=True)
            u.check_version(row.version, expected)
            _domain(lambda: sg.check_reviewable(row.reviewed_at is not None))
            involved = {row.authorised_by_id, row.author_id, *map(uuid.UUID, row.staff_ids)}
            _domain(lambda: sg.check_independent(me, involved))
            row.reviewed_at, row.reviewed_by_id = u.ctx.now, me
            row.review_outcome, row.review_note = cmd.outcome.value, cmd.note
            row.version += 1
            decision = u.authorize("safeguarding:review")
            event = u.emit(
                EventType.RESTRICTIVE_INTERVENTION_REVIEWED,
                "restrictive_intervention",
                row.id,
                row.version,
                u.ctx.now,
                {"intervention_id": str(row.id), "outcome": cmd.outcome.value},
            )
            u.audit(
                decision,
                "restrictive_intervention.review",
                "restrictive_intervention",
                row.id,
                patient_id=row.patient_id,
                event_id=event,
            )
            return CommandResult(200, intervention_out(row, u.ctx.now).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="restrictive_intervention.review",
            capability="safeguarding:review",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json")
            | {"intervention_id": str(intervention_id), "v": expected},
            handler=handle,
            resource=("restrictive_intervention", intervention_id),
        )

    def interventions(self, ctx: RequestContext, patient_id: uuid.UUID) -> list[InterventionOut]:
        def read(session: Session, decision: Decision) -> list[InterventionOut]:
            rows = session.execute(
                select(RestrictiveIntervention)
                .where(
                    RestrictiveIntervention.tenant_id == ctx.tenant_id,
                    RestrictiveIntervention.patient_id == patient_id,
                )
                .order_by(RestrictiveIntervention.started_at.desc())
            ).scalars()
            return [intervention_out(r, ctx.now) for r in rows]

        return self._read(
            ctx,
            capabilities=("safeguarding:review", "safeguarding:view"),
            action="restrictive_intervention.list",
            patient_id=patient_id,
            reader=read,
        )

    def review_queue(
        self, ctx: RequestContext, *, reviewed: bool, limit: int
    ) -> list[InterventionOut]:
        def read(session: Session, decision: Decision) -> list[InterventionOut]:
            done = RestrictiveIntervention.reviewed_at.is_not(None)
            rows = session.execute(
                select(RestrictiveIntervention)
                .where(
                    RestrictiveIntervention.tenant_id == ctx.tenant_id,
                    done if reviewed else ~done,
                )
                .order_by(RestrictiveIntervention.review_due_at, RestrictiveIntervention.id)
                .limit(limit)
            ).scalars()
            return [intervention_out(r, ctx.now) for r in rows]

        return self._read(
            ctx,
            capabilities=("safeguarding:review",),
            action="restrictive_intervention.queue",
            patient_id=None,
            reader=read,
        )

    # -- legal status -------------------------------------------------------------------

    def set_legal_status(
        self, ctx: RequestContext, key: str | None, patient_id: uuid.UUID, cmd: SetLegalStatus
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            _domain(
                lambda: sg.check_legal_status(
                    cmd.status, cmd.legal_basis, cmd.valid_from, cmd.valid_until, u.ctx.now
                )
            )
            patient = u.get(Patient, patient_id, lock=True)  # one change at a time
            u.get(Practitioner, cmd.authorised_by_id)
            previous = views.current_legal_status(u.session, u.ctx.tenant_id, patient.id)
            if previous is not None:
                previous.ended_at, previous.current_marker = u.ctx.now, None
                previous.version += 1
                u.session.flush()
            row = MentalHealthLegalStatus(
                patient_id=patient.id,
                status=cmd.status.value,
                legal_basis=cmd.legal_basis,
                valid_from=cmd.valid_from,
                valid_until=cmd.valid_until,
                effective_at=cmd.valid_from,
                authorised_by_id=cmd.authorised_by_id,
                reason=cmd.reason,
                current_marker=1,
                **_envelope(u),
            )
            u.session.add(row)
            u.session.flush()
            decision = u.authorize("mh_legal:manage", patient_id=patient.id)
            event = u.emit(
                EventType.LEGAL_STATUS_CHANGED,
                "mental_health_legal_status",
                row.id,
                1,
                cmd.valid_from,
                {
                    "patient_id": str(patient.id),
                    "status": row.status,
                    "previous_status": previous.status if previous else None,
                    "valid_until": row.valid_until.isoformat() if row.valid_until else None,
                },
            )
            u.audit(
                decision,
                "mental_health_legal_status.set",
                "mental_health_legal_status",
                row.id,
                patient_id=patient.id,
                event_id=event,
            )
            return CommandResult(201, views.legal_status(row, u.ctx.now).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="mental_health_legal_status.set",
            capability="mh_legal:manage",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"patient_id": str(patient_id)},
            handler=handle,
            patient_id=patient_id,
        )

    def legal_history(self, ctx: RequestContext, patient_id: uuid.UUID) -> list[LegalStatusOut]:
        def read(session: Session, decision: Decision) -> list[LegalStatusOut]:
            rows = session.execute(
                select(MentalHealthLegalStatus)
                .where(
                    MentalHealthLegalStatus.tenant_id == ctx.tenant_id,
                    MentalHealthLegalStatus.patient_id == patient_id,
                )
                .order_by(
                    MentalHealthLegalStatus.valid_from.desc(), MentalHealthLegalStatus.id.desc()
                )
            ).scalars()
            return [views.legal_status(r, ctx.now) for r in rows]

        return self._read(
            ctx,
            capabilities=("safeguarding:review", "safeguarding:view"),
            action="mental_health_legal_status.history",
            patient_id=patient_id,
            reader=read,
        )

    def expiring(self, ctx: RequestContext) -> list[LegalStatusOut]:
        """Compulsory powers that expire within 72 hours or have lapsed (ICRS
        5.5.11: reminder alerts)."""

        def read(session: Session, decision: Decision) -> list[LegalStatusOut]:
            rows = session.execute(
                select(MentalHealthLegalStatus)
                .where(
                    MentalHealthLegalStatus.tenant_id == ctx.tenant_id,
                    MentalHealthLegalStatus.current_marker == 1,
                    MentalHealthLegalStatus.valid_until.is_not(None),
                    MentalHealthLegalStatus.valid_until <= ctx.now + sg.EXPIRY_WARNING,
                )
                .order_by(MentalHealthLegalStatus.valid_until)
            ).scalars()
            return [views.legal_status(r, ctx.now) for r in rows]

        return self._read(
            ctx,
            capabilities=("safeguarding:review",),
            action="mental_health_legal_status.expiring",
            patient_id=None,
            reader=read,
        )

    # -- concerns -------------------------------------------------------------------------

    def raise_concern(
        self, ctx: RequestContext, key: str | None, cmd: RaiseConcern
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            patient = u.get(Patient, cmd.patient_id)
            if cmd.about_practitioner_id is not None:
                u.get(Practitioner, cmd.about_practitioner_id)
            row = SafeguardingConcern(
                patient_id=patient.id,
                raised_by=cmd.raised_by.value,
                raised_by_name=cmd.raised_by_name,
                category=cmd.category.value,
                description=cmd.description,
                about_practitioner_id=cmd.about_practitioner_id,
                status=sg.ConcernStatus.OPEN.value,
                respond_by=u.ctx.now + sg.CONCERN_RESPONSE,
                source_id=u.ctx.principal.subject[:128],
                **_envelope(u),
            )
            u.session.add(row)
            u.session.flush()
            decision = u.authorize("concern:raise")
            event = u.emit(
                EventType.CONCERN_RAISED,
                "safeguarding_concern",
                row.id,
                1,
                u.ctx.now,
                {
                    "concern_id": str(row.id),
                    "patient_id": str(patient.id),
                    "category": row.category,
                    "raised_by": row.raised_by,
                    "respond_by": row.respond_by.isoformat(),
                },
            )
            u.audit(
                decision,
                "safeguarding_concern.raise",
                "safeguarding_concern",
                row.id,
                patient_id=patient.id,
                event_id=event,
            )
            # The person who raised it gets an acknowledgement, not the record.
            body = {
                "id": str(row.id),
                "status": row.status,
                "respond_by": row.respond_by.isoformat(),
            }
            return CommandResult(201, body)

        return self.wp.run(
            ctx,
            operation="safeguarding_concern.raise",
            capability="concern:raise",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json"),
            handler=handle,
        )

    def close_concern(
        self,
        ctx: RequestContext,
        key: str | None,
        concern_id: uuid.UUID,
        expected: int | None,
        cmd: CloseConcern,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            me = _reviewer(u)
            row = u.get(SafeguardingConcern, concern_id, lock=True)
            u.check_version(row.version, expected)
            _domain(lambda: sg.check_independent(me, {row.about_practitioner_id}))
            row.status = _domain(
                lambda: sg.close_concern(
                    sg.ConcernStatus(row.status), sg.ConcernStatus(cmd.outcome)
                )
            ).value
            row.closed_at, row.closed_by_id, row.outcome_note = u.ctx.now, me, cmd.note
            row.version += 1
            decision = u.authorize("safeguarding:review")
            event = u.emit(
                EventType.CONCERN_CLOSED,
                "safeguarding_concern",
                row.id,
                row.version,
                u.ctx.now,
                {"concern_id": str(row.id), "outcome": row.status},
            )
            u.audit(
                decision,
                "safeguarding_concern.close",
                "safeguarding_concern",
                row.id,
                patient_id=row.patient_id,
                event_id=event,
            )
            return CommandResult(200, concern_out(row, u.ctx.now).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="safeguarding_concern.close",
            capability="safeguarding:review",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"concern_id": str(concern_id), "v": expected},
            handler=handle,
            resource=("safeguarding_concern", concern_id),
        )

    def concerns(
        self, ctx: RequestContext, *, status: sg.ConcernStatus, limit: int
    ) -> list[ConcernOut]:
        def read(session: Session, decision: Decision) -> list[ConcernOut]:
            rows = session.execute(
                select(SafeguardingConcern)
                .where(
                    SafeguardingConcern.tenant_id == ctx.tenant_id,
                    SafeguardingConcern.status == status.value,
                )
                .order_by(SafeguardingConcern.respond_by, SafeguardingConcern.id)
                .limit(limit)
            ).scalars()
            return [concern_out(r, ctx.now) for r in rows]

        return self._read(
            ctx,
            capabilities=("safeguarding:review",),
            action="safeguarding_concern.list",
            patient_id=None,
            reader=read,
        )

    # -- advocates and the access report ------------------------------------------------

    def appoint_advocate(
        self, ctx: RequestContext, key: str | None, patient_id: uuid.UUID, cmd: AppointAdvocate
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            patient = u.get(Patient, patient_id)
            u.get(Practitioner, cmd.practitioner_id)
            roles = u.session.execute(
                select(Membership.roles).where(
                    Membership.tenant_id == u.ctx.tenant_id,
                    Membership.practitioner_id == cmd.practitioner_id,
                    # Only a current appointment counts, not a lapsed or suspended one.
                    Membership.active.is_(True),
                    Membership.valid_from <= u.ctx.now,
                    (Membership.valid_to.is_(None)) | (Membership.valid_to > u.ctx.now),
                )
            ).scalars()
            if not any("patient_advocate" in r for r in roles):
                raise Unprocessable(
                    "that practitioner is not a patient advocate", code="not_an_advocate"
                )
            link = LegitimateRelationship(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                recorded_at=u.ctx.now,
                author_id=u.ctx.principal.practitioner_id,
                patient_id=patient.id,
                practitioner_id=cmd.practitioner_id,
                start_at=u.ctx.now,
                creation_reason_code="patient_advocate",
                created_by_id=u.ctx.principal.practitioner_id,
            )
            u.session.add(link)
            u.session.flush()
            decision = u.authorize("safeguarding:review")
            event = u.emit(
                EventType.ADVOCATE_APPOINTED,
                "patient",
                patient.id,
                patient.version,
                u.ctx.now,
                {"patient_id": str(patient.id), "advocate_id": str(cmd.practitioner_id)},
            )
            u.audit(
                decision,
                "patient_advocate.appoint",
                "legitimate_relationship",
                link.id,
                patient_id=patient.id,
                event_id=event,
            )
            body = {
                "relationship_id": str(link.id),
                "patient_id": str(patient.id),
                "advocate_id": str(cmd.practitioner_id),
            }
            return CommandResult(201, body)

        return self.wp.run(
            ctx,
            operation="patient_advocate.appoint",
            capability="safeguarding:review",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"patient_id": str(patient_id)},
            handler=handle,
        )

    def access_report(
        self,
        ctx: RequestContext,
        patient_id: uuid.UUID,
        *,
        start: datetime | None,
        end: datetime | None,
    ) -> AccessReportOut:
        upper = end or ctx.now
        lower = start or upper - REPORT_WINDOW

        def read(session: Session, decision: Decision) -> AccessReportOut:
            rows = session.execute(
                select(AuditEvent)
                .where(
                    AuditEvent.tenant_id == ctx.tenant_id,
                    AuditEvent.patient_id == patient_id,
                    AuditEvent.occurred_at >= lower,
                    AuditEvent.occurred_at < upper,
                )
                .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id)
                .limit(1000)
            ).scalars()
            entries = [
                AccessEntry(
                    occurred_at=a.occurred_at,
                    actor_subject=a.actor_subject,
                    actor_practitioner_id=a.actor_practitioner_id,
                    action=a.action,
                    outcome=a.outcome,
                    reason_code=a.reason_code,
                    flags=[
                        f.value for f in sg.access_flags(a.outcome, a.reason_code, a.occurred_at)
                    ],
                )
                for a in rows
            ]
            counts = Counter(e.actor_subject for e in entries)
            flagged = Counter(e.actor_subject for e in entries if e.flags)
            return AccessReportOut(
                patient_id=patient_id,
                start=lower,
                end=upper,
                entries=entries,
                by_actor=[
                    ActorSummary(actor_subject=s, entries=n, flagged=flagged[s])
                    for s, n in counts.most_common()
                ],
                flagged=sum(flagged.values()),
            )

        return self._read(
            ctx,
            capabilities=("safeguarding:review", "access_report:read"),
            action="access_report.read",
            patient_id=patient_id,
            reader=read,
        )
