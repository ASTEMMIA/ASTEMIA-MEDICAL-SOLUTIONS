"""Patient index (ICRS module 102, section 3.2): search, duplicate detection,
merge and unmerge, and closure.

Merge never moves clinical records. The prior record is marked merged and a
MergeLink points it at the survivor; the survivor's chart reads every record
merged into it (ICRS 3.2.12). Active identifiers move to the survivor and come
back on unmerge, and every change is a DemographicTransaction, which also
records who made it and when (ICRS 3.2.19).
"""

import uuid
from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import (
    DemographicTransaction,
    MergeLink,
    Patient,
    PatientIdentifier,
    PersonName,
)
from astemia.application import addresses, views
from astemia.application.context import RequestContext
from astemia.application.errors import AccessDenied, Conflict, NotFound, Unprocessable
from astemia.application.identity_review import resolve_on_merge
from astemia.application.policy import Decision, PolicyEngine
from astemia.application.schemas import (
    AddressHistoryOut,
    ChangeAddress,
    CloseBatch,
    ClosePatient,
    DuplicateGroup,
    MergePatient,
    PatientOut,
    UnmergePatient,
)
from astemia.application.write_path import CommandResult, Unit, WritePath, audit_row
from astemia.domain import identity as idn
from astemia.domain.common import DomainError, new_id
from astemia.domain.events import EventType

OPEN = [s.value for s in idn.OPEN_STATUSES]


def _domain(fn: Any) -> Any:
    try:
        return fn()
    except DomainError as exc:
        raise Unprocessable(str(exc), code=exc.code) from None


def _usual_names(tenant_id: uuid.UUID) -> Any:
    """Current usual names, one row per patient."""
    return (
        select(PersonName.party_id, PersonName.family_name, PersonName.given_name)
        .where(
            PersonName.tenant_id == tenant_id,
            PersonName.name_type == idn.NameType.USUAL.value,
            PersonName.effective_to.is_(None),
        )
        .subquery()
    )


def possible_duplicates(session: Session, patient: Patient, family_name: str) -> list[uuid.UUID]:
    """Open records that share family name, date of birth and sex (ICRS 3.2.8)."""
    names = _usual_names(patient.tenant_id)
    family, _, _ = idn.duplicate_key(family_name, patient.birth_date, patient.administrative_sex)
    return list(
        session.execute(
            select(Patient.id)
            .join(names, names.c.party_id == Patient.id)
            .where(
                Patient.tenant_id == patient.tenant_id,
                Patient.id != patient.id,
                Patient.birth_date == patient.birth_date,
                Patient.administrative_sex == patient.administrative_sex,
                Patient.status.in_(OPEN),
                func.lower(names.c.family_name) == family,
            )
            .order_by(Patient.id)
        ).scalars()
    )


def _active_identifiers(u: Unit, patient_id: uuid.UUID) -> list[PatientIdentifier]:
    return list(
        u.session.execute(
            select(PatientIdentifier)
            .where(
                PatientIdentifier.tenant_id == u.ctx.tenant_id,
                PatientIdentifier.patient_id == patient_id,
                PatientIdentifier.active_marker == 1,
            )
            .order_by(PatientIdentifier.id)
        ).scalars()
    )


def _transaction(u: Unit, patient_id: uuid.UUID, reason: str, delta: dict[str, Any]) -> None:
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


def _envelope(u: Unit) -> dict[str, Any]:
    return {
        "tenant_id": u.ctx.tenant_id,
        "recorded_at": u.ctx.now,
        "author_id": u.ctx.principal.practitioner_id,
        "author_role": "identity_steward",
    }


def _out(u: Unit, row: Patient) -> dict[str, Any]:
    return views.patient(u.session, row, masks=frozenset(), at=u.ctx.now).model_dump(mode="json")


def _lock_pair(u: Unit, a: uuid.UUID, b: uuid.UUID) -> tuple[Patient, Patient]:
    """Lock both records in a fixed order, so two opposite merges cannot deadlock."""
    rows = {pid: u.get(Patient, pid, lock=True) for pid in sorted((a, b))}
    return rows[a], rows[b]


def _add_aliases(u: Unit, prior: Patient, survivor: Patient) -> list[uuid.UUID]:
    """WF01 step 4: the prior record's names stay findable on the survivor as
    aliases, each pointing at the name it came from."""
    seen = {
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
        if (n.family_name.casefold(), n.given_name.casefold()) in seen:
            continue
        seen.add((n.family_name.casefold(), n.given_name.casefold()))
        number += 1
        alias = PersonName(
            tenant_id=u.ctx.tenant_id,
            id=new_id(),
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


def _reviewer(u: Unit) -> uuid.UUID:
    """Merge links name the reviewing practitioner; a service account cannot merge."""
    reviewer = u.ctx.principal.practitioner_id
    if reviewer is None:
        u.deny("no_practitioner")
    return reviewer


class PatientIndex:
    def __init__(
        self, write_path: WritePath, factory: sessionmaker[Session], policy: PolicyEngine
    ) -> None:
        self.wp = write_path
        self.factory = factory
        self.policy = policy

    # -- ICRS 3.2.12, 3.2.33: merge ---------------------------------------------

    def merge(
        self,
        ctx: RequestContext,
        key: str | None,
        prior_id: uuid.UUID,
        expected: int | None,
        cmd: MergePatient,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            reviewer = _reviewer(u)
            prior, survivor = _lock_pair(u, prior_id, cmd.survivor_id)
            u.check_version(prior.version, expected)
            _domain(lambda: idn.check_merge(prior.id, survivor.id, prior.status, survivor.status))
            moving = _active_identifiers(u, prior.id)
            held = _active_identifiers(u, survivor.id)
            _domain(
                lambda: idn.check_identifiers_compatible(
                    {i.issuer: i.value for i in moving}, {i.issuer: i.value for i in held}
                )
            )
            for i in moving:
                i.active_marker, i.valid_to, i.version = None, u.ctx.now, i.version + 1
            # Compatible records cannot share an active value (it is unique while
            # active), so every moving identifier is new to the survivor.
            u.session.flush()  # release the unique bindings before the survivor takes them
            copied = []
            for i in moving:
                # HS02: the copy keeps the original's author and source IDs.
                copy = PatientIdentifier(
                    tenant_id=u.ctx.tenant_id,
                    id=new_id(),
                    recorded_at=u.ctx.now,
                    effective_at=i.effective_at,
                    author_id=i.author_id,
                    author_role=i.author_role,
                    source_system=i.source_system,
                    source_id=i.source_id,
                    source_status=i.source_status,
                    sensitivity=i.sensitivity,
                    patient_id=survivor.id,
                    issuer=i.issuer,
                    value=i.value,
                    identifier_type=i.identifier_type,
                    verification_status=i.verification_status,
                    valid_from=u.ctx.now,
                    active_marker=1,
                )
                u.session.add(copy)
                copied.append(copy.id)
            aliases = _add_aliases(u, prior, survivor)
            reviews = resolve_on_merge(u, prior.id, survivor.id)
            prior_status = prior.status
            prior.status, prior.version = idn.PatientStatus.MERGED.value, prior.version + 1
            link = MergeLink(
                id=new_id(),
                prior_id=prior.id,
                survivor_id=survivor.id,
                action=views.MERGE,
                reviewer_id=reviewer,
                reason=cmd.reason,
                reversible=True,
                reconciliation_status="merged",
                **_envelope(u),
            )
            u.session.add(link)
            u.session.flush()
            _transaction(
                u,
                prior.id,
                "merge",
                {
                    "merge_link_id": str(link.id),
                    "merged_into": str(survivor.id),
                    "prior_status": prior_status,
                    "deactivated_identifiers": [str(i.id) for i in moving],
                    "copied_identifiers": [str(c) for c in copied],
                    "alias_names": [str(a) for a in aliases],
                    "resolved_reviews": [str(r) for r in reviews],
                },
            )
            _transaction(u, survivor.id, "merge", {"merged_from": str(prior.id)})
            decision = u.authorize("patient:merge", patient_id=prior.id)
            event = u.emit(
                EventType.PATIENT_MERGED,
                "patient",
                prior.id,
                prior.version,
                u.ctx.now,
                {"prior_id": str(prior.id), "survivor_id": str(survivor.id)},
            )
            for pid in (prior.id, survivor.id):
                u.audit(decision, "patient.merge", "patient", pid, patient_id=pid, event_id=event)
            body = {
                "merge_link_id": str(link.id),
                "prior": _out(u, prior),
                "survivor": _out(u, survivor),
            }
            return CommandResult(200, body)

        return self.wp.run(
            ctx,
            operation="patient.merge",
            capability="patient:merge",
            idempotency_key=key,
            payload={"prior_id": str(prior_id), **cmd.model_dump(mode="json")},
            handler=handle,
            patient_id=prior_id,
        )

    # -- ICRS 3.2.33: unmerge ---------------------------------------------------

    def unmerge(
        self, ctx: RequestContext, key: str | None, link_id: uuid.UUID, cmd: UnmergePatient
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            reviewer = _reviewer(u)
            link = u.get(MergeLink, link_id, lock=True)
            if (
                link.action != views.MERGE
                or link.reconciliation_status == views.REVERSED
                or not link.reversible
            ):
                raise Conflict("this merge is not in force", code="not_reversible")
            prior, survivor = _lock_pair(u, link.prior_id, link.survivor_id)
            delta = next(
                (
                    t.delta
                    for t in u.session.execute(
                        select(DemographicTransaction).where(
                            DemographicTransaction.tenant_id == u.ctx.tenant_id,
                            DemographicTransaction.patient_id == prior.id,
                            DemographicTransaction.change_reason == "merge",
                        )
                    ).scalars()
                    if t.delta.get("merge_link_id") == str(link.id)
                ),
                None,
            )
            if delta is None:
                # A merge loaded from a legacy system has no recorded identifier moves.
                raise Conflict(
                    "this merge has no recorded changes to reverse", code="not_reversible"
                )
            ids = [uuid.UUID(i) for i in delta["copied_identifiers"]]
            for copy in u.session.execute(
                select(PatientIdentifier).where(
                    PatientIdentifier.tenant_id == u.ctx.tenant_id, PatientIdentifier.id.in_(ids)
                )
            ).scalars():
                copy.active_marker, copy.valid_to, copy.version = None, u.ctx.now, copy.version + 1
            u.session.flush()  # release the survivor's copies before the prior rebinds
            ids = [uuid.UUID(i) for i in delta["deactivated_identifiers"]]
            for i in u.session.execute(
                select(PatientIdentifier).where(
                    PatientIdentifier.tenant_id == u.ctx.tenant_id, PatientIdentifier.id.in_(ids)
                )
            ).scalars():
                i.active_marker, i.valid_to, i.version = 1, None, i.version + 1
            ids = [uuid.UUID(i) for i in delta.get("alias_names", [])]
            for alias in u.session.execute(
                select(PersonName).where(
                    PersonName.tenant_id == u.ctx.tenant_id, PersonName.id.in_(ids)
                )
            ).scalars():
                alias.effective_to, alias.version = u.ctx.now, alias.version + 1
            prior.status, prior.version = delta["prior_status"], prior.version + 1
            link.reconciliation_status, link.version = views.REVERSED, link.version + 1
            reversal = MergeLink(
                id=new_id(),
                prior_id=prior.id,
                survivor_id=survivor.id,
                action=views.UNMERGE,
                reviewer_id=reviewer,
                reason=cmd.reason,
                reversible=False,
                reconciliation_status="unmerged",
                **_envelope(u),
            )
            u.session.add(reversal)
            u.session.flush()
            _transaction(
                u, prior.id, "unmerge", {"merge_link_id": str(link.id), "status": prior.status}
            )
            _transaction(u, survivor.id, "unmerge", {"unmerged": str(prior.id)})
            decision = u.authorize("patient:merge", patient_id=prior.id)
            event = u.emit(
                EventType.PATIENT_UNMERGED,
                "patient",
                prior.id,
                prior.version,
                u.ctx.now,
                {"prior_id": str(prior.id), "survivor_id": str(survivor.id)},
            )
            for pid in (prior.id, survivor.id):
                u.audit(decision, "patient.unmerge", "patient", pid, patient_id=pid, event_id=event)
            body = {
                "merge_link_id": str(reversal.id),
                "prior": _out(u, prior),
                "survivor": _out(u, survivor),
            }
            return CommandResult(200, body)

        return self.wp.run(
            ctx,
            operation="patient.unmerge",
            capability="patient:merge",
            idempotency_key=key,
            payload={"merge_link_id": str(link_id), **cmd.model_dump(mode="json")},
            handler=handle,
        )

    # -- ICRS 3.2.18-3.2.20: closure --------------------------------------------

    @staticmethod
    def _close(u: Unit, patient: Patient, reason: idn.ClosureReason, exit_date: date) -> None:
        _domain(
            lambda: idn.check_closable(
                patient.status, exit_date, patient.birth_date, u.ctx.now.date()
            )
        )
        before = patient.status
        patient.status = idn.closure_status(reason).value
        patient.date_of_exit = exit_date
        if reason is idn.ClosureReason.DEATH:
            patient.death_date, patient.death_date_precision = exit_date, "day"
            patient.death_notification_status = "notified"
        patient.version += 1
        _transaction(
            u,
            patient.id,
            f"closure:{reason.value}",
            {"status": [before, patient.status], "date_of_exit": exit_date.isoformat()},
        )
        decision = u.authorize("patient:close", patient_id=patient.id)
        event = u.emit(
            EventType.PATIENT_CLOSED,
            "patient",
            patient.id,
            patient.version,
            u.ctx.now,
            {"patient_id": str(patient.id), "reason": reason.value, "status": patient.status},
        )
        u.audit(
            decision, "patient.close", "patient", patient.id, patient_id=patient.id, event_id=event
        )

    def close(
        self,
        ctx: RequestContext,
        key: str | None,
        patient_id: uuid.UUID,
        expected: int | None,
        cmd: ClosePatient,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            patient = u.get(Patient, patient_id, lock=True)
            u.check_version(patient.version, expected)
            self._close(u, patient, cmd.reason, cmd.exit_date)
            return CommandResult(200, _out(u, patient))

        return self.wp.run(
            ctx,
            operation="patient.close",
            capability="patient:close",
            idempotency_key=key,
            payload={"patient_id": str(patient_id), **cmd.model_dump(mode="json")},
            handler=handle,
            patient_id=patient_id,
        )

    def close_batch(self, ctx: RequestContext, key: str | None, cmd: CloseBatch) -> CommandResult:
        """Each item succeeds or reports why not; one bad item does not stop the batch."""

        def handle(u: Unit) -> CommandResult:
            results = []
            for item in cmd.items:
                try:
                    patient = u.get(Patient, item.patient_id, lock=True)
                    self._close(u, patient, item.reason, item.exit_date)
                except (NotFound, Unprocessable) as exc:
                    results.append({"patient_id": str(item.patient_id), "outcome": exc.code})
                    continue
                results.append(
                    {"patient_id": str(patient.id), "outcome": "closed", "status": patient.status}
                )
            closed = sum(1 for r in results if r["outcome"] == "closed")
            return CommandResult(200, {"closed": closed, "results": results})

        return self.wp.run(
            ctx,
            operation="patient.close_batch",
            capability="patient:close",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json"),
            handler=handle,
        )

    # -- ICRS 3.2.11, CEDA revision 1.8: the home address, changed with history ------

    def change_address(
        self,
        ctx: RequestContext,
        key: str | None,
        patient_id: uuid.UUID,
        expected: int | None,
        cmd: ChangeAddress,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            patient = u.get(Patient, patient_id, lock=True)
            u.check_version(patient.version, expected)
            new = cmd.address
            _domain(
                lambda: idn.check_address(
                    temporary=False,
                    has_address=True,
                    country=new.country,
                    state=new.state,
                    lga=new.local_government_area,
                )
            )
            postcode = _domain(lambda: idn.normalise_postcode(new.country, new.postcode))
            current = addresses.current_home(u.session, u.ctx.tenant_id, patient.id, u.ctx.now)
            _domain(
                lambda: idn.check_address_change(
                    patient.status,
                    cmd.reason,
                    current is not None and addresses.same_address(current[1], new, postcode),
                )
            )
            if current is not None:
                current[0].effective_to = u.ctx.now  # kept as history, never overwritten
                current[0].version += 1
            aid = addresses.file_home(u, patient.id, new, postcode, _envelope(u))
            patient.version += 1
            _transaction(
                u,
                patient.id,
                f"address:{cmd.reason.value}",
                {
                    "address": [str(current[1].id) if current else None, str(aid)],
                    "reason": cmd.reason.value,
                },
            )
            decision = u.authorize("address:update", patient_id=patient.id)
            # The address itself stays out of events (personal data).
            event = u.emit(
                EventType.PATIENT_ADDRESS_CHANGED,
                "patient",
                patient.id,
                patient.version,
                u.ctx.now,
                {"patient_id": str(patient.id), "reason": cmd.reason.value},
            )
            u.audit(
                decision,
                "patient.address_change",
                "patient",
                patient.id,
                patient_id=patient.id,
                event_id=event,
            )
            return CommandResult(200, _out(u, patient))

        return self.wp.run(
            ctx,
            operation="patient.address_change",
            capability="address:update",
            idempotency_key=key,
            payload={"patient_id": str(patient_id), "v": expected, **cmd.model_dump(mode="json")},
            handler=handle,
            patient_id=patient_id,
        )

    def address_history(
        self, ctx: RequestContext, patient_id: uuid.UUID
    ) -> list[AddressHistoryOut]:
        with self.factory() as session:
            decision = self._decide(session, ctx, "address:read")
            if session.get(Patient, (ctx.tenant_id, patient_id)) is None:
                raise NotFound("patient not found")
            out = addresses.history(session, ctx.tenant_id, patient_id)
            session.add(
                audit_row(
                    ctx,
                    decision,
                    "patient.address_history",
                    "patient",
                    patient_id,
                    patient_id,
                    "success",
                )
            )
            session.commit()
        return out

    def get(self, ctx: RequestContext, patient_id: uuid.UUID) -> PatientOut:
        """Demographics only, for the patient index (no clinical record)."""
        with self.factory() as session:
            decision = self._decide(session, ctx, "patient:search")
            row = session.get(Patient, (ctx.tenant_id, patient_id))
            if row is None:
                raise NotFound("patient not found")
            out = views.patient(session, row, masks=decision.masks, at=ctx.now)
            session.add(
                audit_row(
                    ctx,
                    decision,
                    "patient_index.read",
                    "patient",
                    patient_id,
                    patient_id,
                    "success",
                )
            )
            session.commit()
        return out

    # -- ICRS 3.2.3, 3.2.34: search; 3.2.11: duplicate housekeeping ----------------

    def _decide(self, session: Session, ctx: RequestContext, capability: str) -> Decision:
        decision = self.policy.decide(session, ctx, capability)
        if not decision.allowed:
            session.add(audit_row(ctx, decision, capability, "patient_index", None, None, "denied"))
            session.commit()
            raise AccessDenied(decision.reason, code=decision.reason)
        return decision

    def search(
        self,
        ctx: RequestContext,
        *,
        nin: str | None,
        family_name: str | None,
        given_name: str | None,
        birth_date: date | None,
        limit: int,
    ) -> list[PatientOut]:
        if not nin and not family_name:
            raise Unprocessable(
                "search by NIN, or by family name with optional given name and date of birth",
                code="search_criteria_required",
            )
        with self.factory() as session:
            decision = self._decide(session, ctx, "patient:search")
            tid = ctx.tenant_id
            stmt = select(Patient).where(Patient.tenant_id == tid)
            if nin:
                value = _domain(lambda: idn.validate_identifier("NG-NIN", nin))
                holders = select(PatientIdentifier.patient_id).where(
                    PatientIdentifier.tenant_id == tid,
                    PatientIdentifier.issuer == "NG-NIN",
                    PatientIdentifier.value == value,
                )
                stmt = stmt.where(Patient.id.in_(holders))
            if family_name:
                names = select(PersonName.party_id).where(
                    PersonName.tenant_id == tid,
                    PersonName.effective_to.is_(None),
                    PersonName.family_name.startswith(family_name.strip(), autoescape=True),
                )
                if given_name:
                    names = names.where(
                        PersonName.given_name.startswith(given_name.strip(), autoescape=True)
                    )
                stmt = stmt.where(Patient.id.in_(names))
            if birth_date:
                stmt = stmt.where(Patient.birth_date == birth_date)
            rows = session.execute(stmt.order_by(Patient.id).limit(limit)).scalars()
            found = [views.patient(session, r, masks=decision.masks, at=ctx.now) for r in rows]
            session.add(
                audit_row(
                    ctx, decision, "patient_index.search", "patient_index", None, None, "success"
                )
            )
            session.commit()
        return found

    def duplicates(self, ctx: RequestContext) -> list[DuplicateGroup]:
        with self.factory() as session:
            decision = self._decide(session, ctx, "patient:merge")
            names = _usual_names(ctx.tenant_id)
            rows = session.execute(
                select(
                    Patient.id, names.c.family_name, Patient.birth_date, Patient.administrative_sex
                )
                .join(names, names.c.party_id == Patient.id)
                .where(Patient.tenant_id == ctx.tenant_id, Patient.status.in_(OPEN))
                .order_by(Patient.id)
            ).all()
            groups: dict[tuple[str, date, str], list[uuid.UUID]] = defaultdict(list)
            for pid, family, born, sex in rows:
                groups[idn.duplicate_key(family, born, sex)].append(pid)
            session.add(
                audit_row(
                    ctx,
                    decision,
                    "patient_index.duplicates",
                    "patient_index",
                    None,
                    None,
                    "success",
                )
            )
            session.commit()
        return [
            DuplicateGroup(
                family_name=family, birth_date=born, administrative_sex=sex, patient_ids=ids
            )
            for (family, born, sex), ids in groups.items()
            if len(ids) > 1
        ]
