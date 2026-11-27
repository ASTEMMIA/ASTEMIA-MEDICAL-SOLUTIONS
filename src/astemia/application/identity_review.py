"""Explainable matching and identity review tasks (UG02, WF01 steps 1 and 4).

This sits beside the patient index (astemia.application.patient_index): the
index searches by NIN or name prefix and lists exact duplicate groups; this
module scores near matches (spelling variants, year-only birth dates, mother's
name) and says why, and turns the ambiguous ones into review tasks that an
identity steward resolves as different people or by merging the pair.
"""

import uuid
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import DuplicateCandidate, Patient, PatientIdentifier, PersonName
from astemia.application import views
from astemia.application.context import RequestContext
from astemia.application.errors import Conflict, Unprocessable
from astemia.application.policy import Decision, PolicyEngine
from astemia.application.schemas import (
    MatchOut,
    MatchQuery,
    RegisterPatient,
    ResolveReview,
    ReviewTaskOut,
)
from astemia.application.write_path import CommandResult, Unit, WritePath, read_path
from astemia.domain import identity as idn
from astemia.domain.common import DomainError, EffectivePrecision, new_id
from astemia.domain.events import EventType

MAX_CANDIDATES = 10
OPEN = [s.value for s in idn.OPEN_STATUSES]


def _domain(fn: Any) -> Any:
    try:
        return fn()
    except DomainError as exc:
        raise Unprocessable(str(exc), code=exc.code) from None


def probe_from(cmd: RegisterPatient | MatchQuery) -> idn.Demographics:
    """Only identifiers that bind actively take part: a retired number kept as
    a previous identifier never makes two records the same person."""
    active = [
        (i.issuer, _domain(lambda i=i: idn.validate_identifier(i.issuer, i.value)), i.verified)
        for i in cmd.identifiers
        if idn.binds_actively(i.issuer)
    ]
    return idn.Demographics(
        family_name=cmd.family_name,
        given_name=cmd.given_names.split()[0],
        birth_date=cmd.birth_date,
        birth_date_precision=cmd.birth_date_precision,
        administrative_sex=cmd.administrative_sex.value,
        mother_name=cmd.mother_name,
        identifiers=frozenset((iss, v) for iss, v, _ in active),
        verified=frozenset((iss, v) for iss, v, ok in active if ok),
    )


def find_matches(
    session: Session,
    tenant_id: uuid.UUID,
    probe: idn.Demographics,
    at: datetime,
    *,
    exclude: uuid.UUID | None = None,
) -> list[tuple[Patient, idn.MatchScore]]:
    """Blocked candidate search (same or similar-sounding family name, same date
    of birth, or the same active identifier), then a score per candidate. Every
    current name counts, so a merged record is still found by its alias."""
    current = (
        PersonName.tenant_id == tenant_id,
        PersonName.effective_from <= at,
        or_(PersonName.effective_to.is_(None), PersonName.effective_to > at),
    )
    by_name = select(PersonName.party_id).where(
        *current,
        or_(
            PersonName.family_name == probe.family_name,
            PersonName.family_name_phonetic == idn.phonetic(probe.family_name),
        ),
    )
    clauses = [Patient.id.in_(by_name), Patient.birth_date == probe.birth_date]
    if probe.identifiers:
        clauses.append(
            Patient.id.in_(
                select(PatientIdentifier.patient_id).where(
                    PatientIdentifier.tenant_id == tenant_id,
                    PatientIdentifier.active_marker == 1,
                    or_(
                        *(
                            (PatientIdentifier.issuer == iss) & (PatientIdentifier.value == v)
                            for iss, v in probe.identifiers
                        )
                    ),
                )
            )
        )
    stmt = select(Patient).where(
        Patient.tenant_id == tenant_id, Patient.status.in_(OPEN), or_(*clauses)
    )
    if exclude is not None:
        stmt = stmt.where(Patient.id != exclude)
    patients = list(session.execute(stmt.limit(500)).scalars())
    ids = [p.id for p in patients]
    names: dict[uuid.UUID, list[PersonName]] = defaultdict(list)
    idents: dict[uuid.UUID, list[PatientIdentifier]] = defaultdict(list)
    if ids:
        for n in session.execute(
            select(PersonName).where(*current, PersonName.party_id.in_(ids))
        ).scalars():
            names[n.party_id].append(n)
        for i in session.execute(
            select(PatientIdentifier).where(
                PatientIdentifier.tenant_id == tenant_id,
                PatientIdentifier.patient_id.in_(ids),
                PatientIdentifier.active_marker == 1,
            )
        ).scalars():
            idents[i.patient_id].append(i)
    scored = []
    for p in patients:
        held = frozenset((i.issuer, i.value) for i in idents[p.id])
        verified = frozenset(
            (i.issuer, i.value)
            for i in idents[p.id]
            if i.verification_status == idn.VerificationStatus.VERIFIED
        )
        best = max(
            (
                idn.score_match(
                    probe,
                    idn.Demographics(
                        family_name=n.family_name,
                        given_name=n.given_name,
                        birth_date=p.birth_date,
                        birth_date_precision=EffectivePrecision(p.birth_date_precision),
                        administrative_sex=p.administrative_sex,
                        mother_name=p.mother_name,
                        identifiers=held,
                        verified=verified,
                    ),
                )
                for n in names[p.id]
            ),
            key=lambda m: m.score,
            default=idn.MatchScore(0, ()),
        )
        if best.band is not None:
            scored.append((p, best))
    scored.sort(key=lambda pm: (-pm[1].score, pm[0].id))
    return scored[:MAX_CANDIDATES]


def open_review(
    u: Unit, a: uuid.UUID, b: uuid.UUID, match: idn.MatchScore, *, origin: str
) -> DuplicateCandidate:
    """An identity review task for a pair; a new record has no earlier pair."""
    record1, record2 = sorted((a, b))
    task = DuplicateCandidate(
        tenant_id=u.ctx.tenant_id,
        id=new_id(),
        version=1,
        recorded_at=u.ctx.now,
        author_id=u.ctx.principal.practitioner_id,
        record1_id=record1,
        record2_id=record2,
        weighting=Decimal(match.score),
        resolved=False,
        reasons=list(match.reasons),
        origin=origin,
    )
    u.session.add(task)
    u.session.flush()
    u.emit(
        EventType.IDENTITY_REVIEW_OPENED,
        "duplicate_candidate",
        task.id,
        1,
        u.ctx.now,
        {
            "task_id": str(task.id),
            "record1_id": str(record1),
            "record2_id": str(record2),
            "score": match.score,
            "origin": origin,
        },
    )
    return task


def review_new_registration(u: Unit, patient_id: uuid.UUID, cmd: RegisterPatient) -> list[str]:
    """WF01: likely and possible matches of a new record go to a steward. The
    registration itself goes ahead (ICRS 3.2.8: alert, never block)."""
    matches = find_matches(
        u.session, u.ctx.tenant_id, probe_from(cmd), u.ctx.now, exclude=patient_id
    )
    return [str(open_review(u, patient_id, p.id, m, origin="registration").id) for p, m in matches]


def resolve_on_merge(u: Unit, a: uuid.UUID, b: uuid.UUID) -> list[uuid.UUID]:
    """A merge of the pair answers its open review tasks."""
    record1, record2 = sorted((a, b))
    tasks = list(
        u.session.execute(
            select(DuplicateCandidate).where(
                DuplicateCandidate.tenant_id == u.ctx.tenant_id,
                DuplicateCandidate.record1_id == record1,
                DuplicateCandidate.record2_id == record2,
                DuplicateCandidate.resolved.is_(False),
            )
        ).scalars()
    )
    for task in tasks:
        task.resolved, task.resolution = True, "merged"
        task.resolved_at, task.resolved_by_id = u.ctx.now, u.ctx.principal.practitioner_id
        task.version += 1
    return [t.id for t in tasks]


class IdentityReview:
    def __init__(
        self, write_path: WritePath, factory: sessionmaker[Session], policy: PolicyEngine
    ) -> None:
        self.wp = write_path
        self.factory = factory
        self.policy = policy

    def match(self, ctx: RequestContext, query: MatchQuery) -> MatchOut:
        probe = probe_from(query)

        def read(session: Session, decision: Decision) -> MatchOut:
            matches = find_matches(session, ctx.tenant_id, probe, ctx.now)
            return MatchOut(
                candidates=[
                    views.candidate(session, p, m, masks=decision.masks, at=ctx.now)
                    for p, m in matches
                ]
            )

        return read_path(
            self.factory,
            self.policy,
            ctx,
            capability="patient:search",
            action="patient_index.match",
            resource_type="patient_index",
            patient_id=None,
            reader=read,
        )

    def tasks(self, ctx: RequestContext, *, resolved: bool, limit: int) -> list[ReviewTaskOut]:
        def read(session: Session, decision: Decision) -> list[ReviewTaskOut]:
            rows = session.execute(
                select(DuplicateCandidate)
                .where(
                    DuplicateCandidate.tenant_id == ctx.tenant_id,
                    DuplicateCandidate.resolved == resolved,
                )
                .order_by(DuplicateCandidate.weighting.desc(), DuplicateCandidate.id)
                .limit(limit)
            ).scalars()
            return [views.review_task(session, t, masks=decision.masks, at=ctx.now) for t in rows]

        return read_path(
            self.factory,
            self.policy,
            ctx,
            capability="patient:merge",
            action="identity_review.list",
            resource_type="duplicate_candidate",
            patient_id=None,
            reader=read,
        )

    def resolve(
        self,
        ctx: RequestContext,
        key: str | None,
        task_id: uuid.UUID,
        expected: int | None,
        cmd: ResolveReview,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            task = u.get(DuplicateCandidate, task_id, lock=True)
            u.check_version(task.version, expected)
            if task.resolved:
                raise Conflict("this review is already resolved", code="review_already_resolved")
            task.resolved, task.resolution = True, cmd.resolution
            task.resolved_at, task.resolved_by_id = u.ctx.now, u.ctx.principal.practitioner_id
            task.note = cmd.reason
            task.version += 1
            decision = u.authorize("patient:merge")
            event = u.emit(
                EventType.IDENTITY_REVIEW_RESOLVED,
                "duplicate_candidate",
                task.id,
                task.version,
                u.ctx.now,
                {"task_id": str(task.id), "resolution": cmd.resolution},
            )
            for pid in (task.record1_id, task.record2_id):
                u.audit(
                    decision,
                    "identity_review.resolve",
                    "duplicate_candidate",
                    task.id,
                    patient_id=pid,
                    event_id=event,
                )
            u.session.flush()
            body = views.review_task(u.session, task, masks=decision.masks, at=u.ctx.now)
            return CommandResult(200, body.model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="identity_review.resolve",
            capability="patient:merge",
            idempotency_key=key,
            payload={"task_id": str(task_id), **cmd.model_dump(mode="json")},
            handler=handle,
        )
