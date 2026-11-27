"""Identity stewardship (UG02, WF01 steps 1 and 4, CEDA E3, HS02).

Matching is explainable: every candidate carries its score and the reasons for
it. Ambiguous matches become identity review tasks (DuplicateCandidate rows).
A merge never moves or rewrites clinical records: they keep the record, author
and source IDs they were written with, and reads of the surviving record follow
the merge (astemia.application.lineage). The merge link keeps what changed,
so an unmerge puts it back.
"""

import uuid
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import (
    DemographicTransaction,
    DuplicateCandidate,
    MergeLink,
    Patient,
    PatientIdentifier,
    PersonName,
)
from astemia.application import views
from astemia.application.context import RequestContext
from astemia.application.errors import Conflict, Unprocessable
from astemia.application.policy import Decision, PolicyEngine
from astemia.application.schemas import (
    CandidateOut,
    MatchOut,
    MatchQuery,
    MergePatient,
    RegisterPatient,
    ResolveReview,
    ReviewTaskOut,
    UnmergePatient,
)
from astemia.application.write_path import CommandResult, Unit, WritePath, read_path
from astemia.domain import identity as idn
from astemia.domain.common import DomainError, EffectivePrecision, new_id
from astemia.domain.events import EventType

MAX_CANDIDATES = 10
MATCHABLE = (idn.PatientStatus.ACTIVE.value, idn.PatientStatus.TEMPORARY.value)


def _domain(fn: Any) -> Any:
    try:
        return fn()
    except DomainError as exc:
        raise Unprocessable(str(exc), code=exc.code) from None


# --- matching -----------------------------------------------------------------


def probe_from(cmd: RegisterPatient | MatchQuery) -> idn.Demographics:
    active = {
        (i.issuer, _domain(lambda i=i: idn.validate_identifier(i.issuer, i.value)), i.verified)
        for i in cmd.identifiers
        if idn.binds_actively(i.issuer)
    }
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
    session: Session, tenant_id: uuid.UUID, probe: idn.Demographics, at: datetime
) -> list[tuple[Patient, idn.MatchScore]]:
    """Blocked candidate search, then a score per candidate. Names of every
    current type count, so a merged record is found by its alias too."""
    name_hits = select(PersonName.party_id).where(
        PersonName.tenant_id == tenant_id,
        PersonName.effective_from <= at,
        or_(PersonName.effective_to.is_(None), PersonName.effective_to > at),
        or_(
            PersonName.family_name == probe.family_name,
            PersonName.family_name_phonetic == idn.phonetic(probe.family_name),
        ),
    )
    clauses = [Patient.id.in_(name_hits), Patient.birth_date == probe.birth_date]
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
    patients = list(
        session.execute(
            select(Patient)
            .where(Patient.tenant_id == tenant_id, Patient.status.in_(MATCHABLE), or_(*clauses))
            .limit(500)
        ).scalars()
    )
    if not patients:
        return []
    ids = [p.id for p in patients]
    names: dict[uuid.UUID, list[PersonName]] = defaultdict(list)
    for n in session.execute(
        select(PersonName).where(
            PersonName.tenant_id == tenant_id,
            PersonName.party_id.in_(ids),
            PersonName.effective_from <= at,
            or_(PersonName.effective_to.is_(None), PersonName.effective_to > at),
        )
    ).scalars():
        names[n.party_id].append(n)
    idents: dict[uuid.UUID, list[PatientIdentifier]] = defaultdict(list)
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
        )
        if best.band is not None:
            scored.append((p, best))
    scored.sort(key=lambda pm: -pm[1].score)
    return scored[:MAX_CANDIDATES]


def candidates_out(
    session: Session,
    matches: list[tuple[Patient, idn.MatchScore]],
    masks: frozenset[str],
    at: datetime,
) -> list[CandidateOut]:
    return [views.candidate(session, p, m.score, m.reasons, masks=masks, at=at) for p, m in matches]


def open_review(
    u: Unit,
    a: uuid.UUID,
    b: uuid.UUID,
    match: idn.MatchScore,
    *,
    origin: str,
    note: str | None,
) -> DuplicateCandidate:
    """Raise a review task for a pair; a new record has no earlier pair."""
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
        note=note,
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


def guard_registration(
    u: Unit, cmd: RegisterPatient, decision: Decision
) -> list[tuple[Patient, idn.MatchScore]]:
    """UG02: show possible duplicates before a patient is created. Returns the
    matches that become review tasks once the new record exists."""
    matches = [
        (p, m)
        for p, m in find_matches(u.session, u.ctx.tenant_id, probe_from(cmd), u.ctx.now)
        # The same active identifier is refused by the unique binding itself.
        if "identifier" not in m.reasons
    ]
    likely = [p.id for p, m in matches if m.band is idn.MatchBand.LIKELY]
    if likely and (not cmd.distinct_reason or not set(likely) <= set(cmd.acknowledged_candidates)):
        raise Conflict(
            "this person may already be registered: review the candidates, then "
            "acknowledge them with a reason if this is a different person",
            code="possible_duplicate",
            details={
                "candidates": [
                    c.model_dump(mode="json")
                    for c in candidates_out(u.session, matches, decision.masks, u.ctx.now)
                ]
            },
        )
    return matches


# --- queries ---------------------------------------------------------------------


class StewardshipQueries:
    def __init__(self, factory: sessionmaker[Session], policy: PolicyEngine) -> None:
        self.factory = factory
        self.policy = policy

    def match(self, ctx: RequestContext, query: MatchQuery) -> MatchOut:
        probe = probe_from(query)

        def read(session: Session, decision: Decision) -> MatchOut:
            matches = find_matches(session, ctx.tenant_id, probe, ctx.now)
            return MatchOut(candidates=candidates_out(session, matches, decision.masks, ctx.now))

        return read_path(
            self.factory,
            self.policy,
            ctx,
            capability="patient:search",
            action="patient.search",
            resource_type="patient",
            patient_id=None,
            reader=read,
        )

    def review_tasks(
        self, ctx: RequestContext, *, resolved: bool, limit: int
    ) -> list[ReviewTaskOut]:
        def read(session: Session, decision: Decision) -> list[ReviewTaskOut]:
            tasks = session.execute(
                select(DuplicateCandidate)
                .where(
                    DuplicateCandidate.tenant_id == ctx.tenant_id,
                    DuplicateCandidate.resolved == resolved,
                )
                .order_by(DuplicateCandidate.weighting.desc(), DuplicateCandidate.recorded_at)
                .limit(limit)
            ).scalars()
            return [views.review_task(session, t, masks=decision.masks, at=ctx.now) for t in tasks]

        return read_path(
            self.factory,
            self.policy,
            ctx,
            capability="identity:review",
            action="identity_review.list",
            resource_type="duplicate_candidate",
            patient_id=None,
            reader=read,
        )


# --- commands --------------------------------------------------------------------


def _transaction(u: Unit, patient_id: uuid.UUID, delta: dict[str, Any], reason: str) -> None:
    u.session.add(
        DemographicTransaction(
            tenant_id=u.ctx.tenant_id,
            id=new_id(),
            patient_id=patient_id,
            transaction_source="api",
            transaction_at=u.ctx.now,
            delta=delta,
            change_reason=reason,
            source_validation_level="identity_steward",
            country_of_transaction="NG",
            transaction_user=u.ctx.principal.subject,
            correlation_id=u.ctx.correlation_id,
        )
    )


def _lock_pair(u: Unit, a: uuid.UUID, b: uuid.UUID) -> dict[uuid.UUID, Patient]:
    """Lock both records in id order, so two stewards never deadlock."""
    return {pid: u.get(Patient, pid, lock=True) for pid in sorted({a, b})}


class StewardshipCommands:
    def __init__(self, write_path: WritePath) -> None:
        self.wp = write_path

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
            decision = u.authorize("identity:review")
            task.resolved = True
            task.resolution = cmd.resolution
            task.resolved_at = u.ctx.now
            task.resolved_by_id = u.ctx.principal.practitioner_id
            task.note = f"{task.note} | steward: {cmd.reason}"[:500] if task.note else cmd.reason
            task.version += 1
            event = u.emit(
                EventType.IDENTITY_REVIEW_RESOLVED,
                "duplicate_candidate",
                task.id,
                task.version,
                u.ctx.now,
                {"task_id": str(task.id), "resolution": cmd.resolution},
            )
            u.audit(
                decision,
                "identity_review.resolve",
                "duplicate_candidate",
                task.id,
                patient_id=task.record1_id,
                event_id=event,
            )
            u.session.flush()
            body = views.review_task(u.session, task, masks=decision.masks, at=u.ctx.now)
            return CommandResult(200, body.model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="identity_review.resolve",
            capability="identity:review",
            idempotency_key=key,
            payload={"task_id": str(task_id), **cmd.model_dump(mode="json")},
            handler=handle,
        )

    def merge(
        self,
        ctx: RequestContext,
        key: str | None,
        prior_id: uuid.UUID,
        expected: int | None,
        cmd: MergePatient,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            reviewer = u.ctx.principal.practitioner_id
            if reviewer is None:
                u.deny("no_practitioner")
            assert reviewer is not None
            pair = _lock_pair(u, prior_id, cmd.survivor_id)
            prior, survivor = pair[prior_id], pair[cmd.survivor_id]
            u.check_version(prior.version, expected)
            _domain(lambda: idn.check_merge(prior.id, prior.status, survivor.id, survivor.status))
            decision = u.authorize("identity:merge")
            moved = self._move_identifiers(u, prior, survivor)
            aliases = self._add_aliases(u, prior, survivor)
            lineage = {
                "prior_status": prior.status,
                "identifiers": moved,
                "aliases": [str(a) for a in aliases],
            }
            prior.status = idn.PatientStatus.MERGED.value
            prior.version += 1
            survivor.version += 1
            link = MergeLink(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                version=1,
                recorded_at=u.ctx.now,
                effective_at=u.ctx.now,
                author_id=reviewer,
                author_role="identity_steward",
                prior_id=prior.id,
                survivor_id=survivor.id,
                action=idn.MergeAction.MERGE.value,
                reviewer_id=reviewer,
                reason=cmd.reason,
                reversible=cmd.reversible,
                reconciliation_status="pending",
                lineage=lineage,
            )
            u.session.add(link)
            record1, record2 = sorted((prior.id, survivor.id))
            for task in u.session.execute(
                select(DuplicateCandidate).where(
                    DuplicateCandidate.tenant_id == u.ctx.tenant_id,
                    DuplicateCandidate.record1_id == record1,
                    DuplicateCandidate.record2_id == record2,
                    DuplicateCandidate.resolved.is_(False),
                )
            ).scalars():
                task.resolved, task.resolution = True, "merged"
                task.resolved_at, task.resolved_by_id = u.ctx.now, reviewer
                task.version += 1
            _transaction(u, prior.id, {"merged_into": str(survivor.id), **lineage}, "merge")
            _transaction(u, survivor.id, {"merged_from": str(prior.id)}, "merge")
            u.session.flush()
            event = u.emit(
                EventType.PATIENT_MERGED,
                "patient",
                prior.id,
                prior.version,
                u.ctx.now,
                {
                    "merge_link_id": str(link.id),
                    "prior_id": str(prior.id),
                    "survivor_id": str(survivor.id),
                    "reversible": link.reversible,
                },
            )
            for pid in (prior.id, survivor.id):
                u.audit(
                    decision, "patient.merge", "merge_link", link.id, patient_id=pid, event_id=event
                )
            body = views.merge_link(u.session, link, masks=decision.masks, at=u.ctx.now)
            return CommandResult(200, body.model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="patient.merge",
            capability="identity:merge",
            idempotency_key=key,
            payload={"prior_id": str(prior_id), **cmd.model_dump(mode="json")},
            handler=handle,
        )

    @staticmethod
    def _move_identifiers(u: Unit, prior: Patient, survivor: Patient) -> list[list[str]]:
        """Each active identifier of the prior record is closed there and
        copied to the survivor with its type, source and original author. A
        second number from the same issuer is kept on the survivor as a previous
        identifier; two different verified numbers need investigating first."""
        held = {
            i.issuer: i
            for i in u.session.execute(
                select(PatientIdentifier).where(
                    PatientIdentifier.tenant_id == u.ctx.tenant_id,
                    PatientIdentifier.patient_id == survivor.id,
                    PatientIdentifier.active_marker == 1,
                )
            ).scalars()
        }
        originals = list(
            u.session.execute(
                select(PatientIdentifier).where(
                    PatientIdentifier.tenant_id == u.ctx.tenant_id,
                    PatientIdentifier.patient_id == prior.id,
                    PatientIdentifier.active_marker == 1,
                )
            ).scalars()
        )
        verified = idn.VerificationStatus.VERIFIED.value
        for orig in originals:
            other = held.get(orig.issuer)
            if (
                other is not None
                and other.value != orig.value
                and verified == other.verification_status == orig.verification_status
            ):
                raise Conflict(
                    f"both records hold a different verified {orig.issuer} number; "
                    "confirm the person's identity before merging",
                    code="conflicting_identifiers",
                )
        for orig in originals:
            orig.active_marker = None
            orig.valid_to = u.ctx.now
            orig.version += 1
        u.session.flush()  # free the unique binding before the copy takes it
        pairs = []
        for orig in originals:
            other = held.get(orig.issuer)
            keep_active = other is None
            copy = PatientIdentifier(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                version=1,
                recorded_at=u.ctx.now,
                effective_at=orig.effective_at,
                author_id=orig.author_id,
                author_role=orig.author_role,
                source_system=orig.source_system,
                source_id=orig.source_id,
                source_status=orig.source_status,
                sensitivity=orig.sensitivity,
                patient_id=survivor.id,
                issuer=orig.issuer,
                value=orig.value,
                identifier_type=(
                    orig.identifier_type if keep_active else idn.IdentifierType.PREVIOUS.value
                ),
                verification_status=orig.verification_status,
                valid_from=u.ctx.now,
                active_marker=1 if keep_active else None,
            )
            u.session.add(copy)
            pairs.append([str(orig.id), str(copy.id)])
        u.session.flush()
        return pairs

    @staticmethod
    def _add_aliases(u: Unit, prior: Patient, survivor: Patient) -> list[uuid.UUID]:
        """The prior record's names stay findable on the survivor as aliases."""
        mine = {
            (n.family_name.casefold(), n.given_name.casefold())
            for n in views.current_names(u.session, survivor, u.ctx.now)
        }
        number = (
            u.session.execute(
                select(func.max(PersonName.name_number)).where(
                    PersonName.tenant_id == u.ctx.tenant_id,
                    PersonName.party_id == survivor.id,
                    PersonName.name_type == idn.NameType.ALIAS.value,
                )
            ).scalar_one()
            or 0
        )
        added = []
        for n in views.current_names(u.session, prior, u.ctx.now):
            if (n.family_name.casefold(), n.given_name.casefold()) in mine:
                continue
            mine.add((n.family_name.casefold(), n.given_name.casefold()))
            number += 1
            alias = PersonName(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                version=1,
                recorded_at=u.ctx.now,
                author_id=n.author_id,
                author_role=n.author_role,
                source_system=n.source_system,
                source_id=str(n.id),
                party_id=survivor.id,
                name_type=idn.NameType.ALIAS.value,
                name_number=number,
                title=n.title,
                family_name=n.family_name,
                given_name=n.given_name,
                other_given_name=n.other_given_name,
                suffix=n.suffix,
                family_name_phonetic=idn.phonetic(n.family_name),
                given_name_phonetic=idn.phonetic(n.given_name),
                effective_from=u.ctx.now,
            )
            u.session.add(alias)
            added.append(alias.id)
        return added

    def unmerge(
        self,
        ctx: RequestContext,
        key: str | None,
        link_id: uuid.UUID,
        expected: int | None,
        cmd: UnmergePatient,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            link = u.get(MergeLink, link_id, lock=True)
            u.check_version(link.version, expected)
            _domain(lambda: idn.check_unmerge(link.action, link.reversible))
            pair = _lock_pair(u, link.prior_id, link.survivor_id)
            prior, survivor = pair[link.prior_id], pair[link.survivor_id]
            if survivor.status == idn.PatientStatus.MERGED:
                raise Conflict(
                    "the surviving record has since been merged again; unmerge that first",
                    code="survivor_since_merged",
                )
            decision = u.authorize("identity:unmerge")
            lineage = link.lineage or {}
            for _orig, copy_id in lineage.get("identifiers", []):
                copy = u.get(PatientIdentifier, uuid.UUID(copy_id), lock=True)
                copy.active_marker, copy.valid_to = None, u.ctx.now
                copy.version += 1
            u.session.flush()
            for orig_id, _ in lineage.get("identifiers", []):
                orig = u.get(PatientIdentifier, uuid.UUID(orig_id), lock=True)
                orig.active_marker, orig.valid_to = 1, None
                orig.version += 1
            for alias_id in lineage.get("aliases", []):
                alias = u.get(PersonName, uuid.UUID(alias_id), lock=True)
                alias.effective_to = u.ctx.now
                alias.version += 1
            prior.status = lineage.get("prior_status", idn.PatientStatus.ACTIVE.value)
            prior.version += 1
            survivor.version += 1
            link.action = idn.MergeAction.UNMERGED.value
            link.reconciliation_status = "pending"
            link.version += 1
            _transaction(u, prior.id, {"unmerged_from": str(survivor.id)}, "unmerge")
            _transaction(
                u, survivor.id, {"unmerged": str(prior.id), "reason": cmd.reason}, "unmerge"
            )
            u.session.flush()
            event = u.emit(
                EventType.PATIENT_UNMERGED,
                "patient",
                prior.id,
                prior.version,
                u.ctx.now,
                {
                    "merge_link_id": str(link.id),
                    "prior_id": str(prior.id),
                    "survivor_id": str(survivor.id),
                },
            )
            for pid in (prior.id, survivor.id):
                u.audit(
                    decision,
                    "patient.unmerge",
                    "merge_link",
                    link.id,
                    patient_id=pid,
                    event_id=event,
                )
            body = views.merge_link(u.session, link, masks=decision.masks, at=u.ctx.now)
            return CommandResult(200, body.model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="patient.unmerge",
            capability="identity:unmerge",
            idempotency_key=key,
            payload={"link_id": str(link_id), **cmd.model_dump(mode="json")},
            handler=handle,
        )
