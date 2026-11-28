"""Clinical notes (CEDA SA-07 ClinicalEntry and EntryRevision; UG02, WF01 step
3, ST04).

A clinician or nurse in the patient's care drafts a note on an encounter; only
the draft's author edits it. Signing needs the right permission for the note
type and an identified patient, and freezes the revision: there is no way to
change a signed revision. A correction is a new revision that references the
one it replaces and is signed in turn; the original keeps its text and author.
The note text never goes into events.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import ClinicalEntry, Encounter, EntryRevision, Patient
from astemia.application.context import RequestContext
from astemia.application.errors import Conflict, NotFound, Unprocessable
from astemia.application.policy import Decision, PolicyEngine
from astemia.application.schemas import (
    AmendEntry,
    CreateEntry,
    EntryOut,
    EntrySummary,
    RevisionOut,
    UpdateDraft,
)
from astemia.application.write_path import CommandResult, Unit, WritePath, read_path
from astemia.domain import notes as nt
from astemia.domain.common import DomainError, Sensitivity, new_id
from astemia.domain.events import EventType


def _domain(fn: Any) -> Any:
    try:
        return fn()
    except DomainError as exc:
        raise Unprocessable(str(exc), code=exc.code) from None


def revision_out(row: EntryRevision) -> RevisionOut:
    return RevisionOut(
        id=row.id,
        revision_number=row.revision_number,
        status=row.status,
        body=row.body,
        author_id=row.author_id,
        recorded_at=row.recorded_at,
        signed_at=row.signed_at,
        signed_by_id=row.signed_by_id,
        supersedes_id=row.supersedes_id,
        amendment_reason=row.amendment_reason,
    )


def _revisions(session: Session, entry: ClinicalEntry) -> list[EntryRevision]:
    return list(
        session.execute(
            select(EntryRevision)
            .where(
                EntryRevision.tenant_id == entry.tenant_id,
                EntryRevision.entry_id == entry.id,
            )
            .order_by(EntryRevision.revision_number)
        ).scalars()
    )


def entry_out(session: Session, entry: ClinicalEntry, viewer: uuid.UUID | None) -> EntryOut:
    """Signed revisions for everyone allowed to read the chart; a draft only
    for its author."""
    return EntryOut(
        id=entry.id,
        version=entry.version,
        patient_id=entry.patient_id,
        encounter_id=entry.encounter_id,
        note_type=entry.note_type,
        title=entry.title,
        status=entry.status,
        sensitivity=entry.sensitivity,
        author_id=entry.author_id,
        revisions=[
            revision_out(r)
            for r in _revisions(session, entry)
            if r.status == nt.RevisionStatus.SIGNED or r.author_id == viewer
        ],
    )


def signed_entries(
    session: Session,
    tenant_id: uuid.UUID,
    patient_ids: list[uuid.UUID],
    visible: Any,
) -> list[EntrySummary]:
    """The chart's notes: the latest signed revision of each entry, newest first,
    with sensitive entries withheld through `visible`."""
    latest = (
        select(EntryRevision.entry_id, func.max(EntryRevision.revision_number).label("n"))
        .where(
            EntryRevision.tenant_id == tenant_id,
            EntryRevision.status == nt.RevisionStatus.SIGNED.value,
        )
        .group_by(EntryRevision.entry_id)
        .subquery()
    )
    rows = session.execute(
        select(ClinicalEntry, EntryRevision)
        .join(latest, latest.c.entry_id == ClinicalEntry.id)
        .join(
            EntryRevision,
            (EntryRevision.tenant_id == ClinicalEntry.tenant_id)
            & (EntryRevision.entry_id == ClinicalEntry.id)
            & (EntryRevision.revision_number == latest.c.n),
        )
        .where(ClinicalEntry.tenant_id == tenant_id, ClinicalEntry.patient_id.in_(patient_ids))
        .order_by(EntryRevision.signed_at.desc(), ClinicalEntry.id)
    ).all()
    out = []
    for entry, rev in rows:
        if not visible(entry.sensitivity):
            continue
        assert rev.signed_at is not None and rev.signed_by_id is not None
        out.append(
            EntrySummary(
                id=entry.id,
                encounter_id=entry.encounter_id,
                note_type=entry.note_type,
                title=entry.title,
                status=entry.status,
                revision_number=rev.revision_number,
                body=rev.body,
                signed_at=rev.signed_at,
                signed_by_id=rev.signed_by_id,
            )
        )
    return out


def _draft(u: Unit, entry: ClinicalEntry) -> EntryRevision | None:
    return u.session.execute(
        select(EntryRevision)
        .where(
            EntryRevision.tenant_id == u.ctx.tenant_id,
            EntryRevision.entry_id == entry.id,
            EntryRevision.draft_marker == 1,
        )
        .with_for_update()
    ).scalar_one_or_none()


class Notes:
    def __init__(
        self, write_path: WritePath, factory: sessionmaker[Session], policy: PolicyEngine
    ) -> None:
        self.wp = write_path
        self.factory = factory
        self.policy = policy

    def _patient_of(self, ctx: RequestContext, model: Any, id_: uuid.UUID) -> uuid.UUID | None:
        """Notes are bound to a care relationship with the patient, so the write
        path needs the patient before it starts. An unknown record gives none,
        which the policy refuses as not found."""
        with self.factory() as session:
            return session.execute(
                select(model.patient_id).where(model.tenant_id == ctx.tenant_id, model.id == id_)
            ).scalar_one_or_none()

    def _new_revision(
        self,
        u: Unit,
        entry: ClinicalEntry,
        number: int,
        body: str,
        *,
        supersedes: uuid.UUID | None = None,
        reason: str | None = None,
    ) -> EntryRevision:
        rev = EntryRevision(
            tenant_id=u.ctx.tenant_id,
            id=new_id(),
            version=1,
            recorded_at=u.ctx.now,
            author_id=u.ctx.principal.practitioner_id,
            sensitivity=entry.sensitivity,
            entry_id=entry.id,
            revision_number=number,
            status=nt.RevisionStatus.DRAFT.value,
            body=body,
            supersedes_id=supersedes,
            amendment_reason=reason,
            draft_marker=1,
        )
        u.session.add(rev)
        return rev

    def create(
        self, ctx: RequestContext, key: str | None, encounter_id: uuid.UUID, cmd: CreateEntry
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            encounter = u.get(Encounter, encounter_id)
            _domain(lambda: nt.check_writable(encounter.state))
            entry = ClinicalEntry(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                version=1,
                recorded_at=u.ctx.now,
                effective_at=u.ctx.now,
                author_id=u.ctx.principal.practitioner_id,
                sensitivity=cmd.sensitivity.value,
                patient_id=encounter.patient_id,
                encounter_id=encounter.id,
                note_type=cmd.note_type.value,
                title=cmd.title,
                status=nt.EntryStatus.DRAFT.value,
            )
            u.session.add(entry)
            u.session.flush()
            self._new_revision(u, entry, 1, cmd.body)
            u.session.flush()
            decision = u.authorize("note:write", patient_id=entry.patient_id)
            u.audit(
                decision,
                "clinical_entry.create",
                "clinical_entry",
                entry.id,
                patient_id=entry.patient_id,
            )
            body = entry_out(u.session, entry, u.ctx.principal.practitioner_id)
            return CommandResult(201, body.model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="clinical_entry.create",
            capability="note:write",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"encounter_id": str(encounter_id)},
            handler=handle,
            patient_id=self._patient_of(ctx, Encounter, encounter_id),
        )

    def update_draft(
        self,
        ctx: RequestContext,
        key: str | None,
        entry_id: uuid.UUID,
        expected: int | None,
        cmd: UpdateDraft,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            entry = u.get(ClinicalEntry, entry_id, lock=True)
            u.check_version(entry.version, expected)
            draft = _draft(u, entry)
            if draft is None:
                raise Conflict("there is no draft to edit; amend the note", code="no_draft")
            if draft.author_id != u.ctx.principal.practitioner_id:
                u.deny("not_draft_author", patient_id=entry.patient_id)
            draft.body, draft.version = cmd.body, draft.version + 1
            entry.version += 1
            decision = u.authorize("note:write", patient_id=entry.patient_id)
            u.audit(
                decision,
                "clinical_entry.edit_draft",
                "clinical_entry",
                entry.id,
                patient_id=entry.patient_id,
            )
            body = entry_out(u.session, entry, u.ctx.principal.practitioner_id)
            return CommandResult(200, body.model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="clinical_entry.edit_draft",
            capability="note:write",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"entry_id": str(entry_id), "v": expected},
            handler=handle,
            patient_id=self._patient_of(ctx, ClinicalEntry, entry_id),
            resource=("clinical_entry", entry_id),
        )

    def sign(
        self, ctx: RequestContext, key: str | None, entry_id: uuid.UUID, expected: int | None
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            entry = u.get(ClinicalEntry, entry_id, lock=True)
            u.check_version(entry.version, expected)
            capability = nt.SIGN_CAPABILITY[nt.NoteType(entry.note_type)]
            decision = u.policy.decide(u.session, u.ctx, capability, patient_id=entry.patient_id)
            if not decision.allowed:
                u.deny("no_signing_permission", patient_id=entry.patient_id)
            patient = u.get(Patient, entry.patient_id)
            _domain(lambda: nt.check_identified(patient.status))
            draft = _draft(u, entry)
            if draft is None:
                raise Conflict("there is nothing to sign", code="no_draft")
            if draft.author_id != u.ctx.principal.practitioner_id:
                # The author signs their own words; a co-signature is a later slice.
                u.deny("not_draft_author", patient_id=entry.patient_id)
            entry.status = _domain(
                lambda: nt.after_signing(nt.EntryStatus(entry.status), draft.revision_number == 1)
            ).value
            draft.status, draft.draft_marker = nt.RevisionStatus.SIGNED.value, None
            draft.signed_at, draft.signed_by_id = u.ctx.now, u.ctx.principal.practitioner_id
            draft.version += 1
            entry.version += 1
            u.session.flush()
            event = u.emit(
                EventType.ENTRY_SIGNED,
                "clinical_entry",
                entry.id,
                entry.version,
                u.ctx.now,
                {
                    "entry_id": str(entry.id),
                    "revision": draft.revision_number,
                    "patient_id": str(entry.patient_id),
                    "encounter_id": str(entry.encounter_id),
                    "note_type": entry.note_type,
                    "amendment": draft.revision_number > 1,
                },
            )
            u.audit(
                decision,
                "clinical_entry.sign",
                "clinical_entry",
                entry.id,
                patient_id=entry.patient_id,
                event_id=event,
            )
            body = entry_out(u.session, entry, u.ctx.principal.practitioner_id)
            return CommandResult(200, body.model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="clinical_entry.sign",
            capability="note:write",
            idempotency_key=key,
            payload={"entry_id": str(entry_id), "v": expected},
            handler=handle,
            patient_id=self._patient_of(ctx, ClinicalEntry, entry_id),
            resource=("clinical_entry", entry_id),
        )

    def amend(
        self,
        ctx: RequestContext,
        key: str | None,
        entry_id: uuid.UUID,
        expected: int | None,
        cmd: AmendEntry,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            entry = u.get(ClinicalEntry, entry_id, lock=True)
            u.check_version(entry.version, expected)
            if entry.status == nt.EntryStatus.DRAFT:
                raise Conflict("this note is not signed yet; edit the draft", code="not_signed")
            if _draft(u, entry) is not None:
                raise Conflict("an amendment is already in draft", code="draft_exists")
            revisions = _revisions(u.session, entry)
            self._new_revision(
                u,
                entry,
                revisions[-1].revision_number + 1,
                cmd.body,
                supersedes=revisions[-1].id,
                reason=cmd.reason,
            )
            entry.version += 1
            u.session.flush()
            decision = u.authorize("note:write", patient_id=entry.patient_id)
            u.audit(
                decision,
                "clinical_entry.amend",
                "clinical_entry",
                entry.id,
                patient_id=entry.patient_id,
            )
            body = entry_out(u.session, entry, u.ctx.principal.practitioner_id)
            return CommandResult(200, body.model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="clinical_entry.amend",
            capability="note:write",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"entry_id": str(entry_id), "v": expected},
            handler=handle,
            patient_id=self._patient_of(ctx, ClinicalEntry, entry_id),
            resource=("clinical_entry", entry_id),
        )

    def get(self, ctx: RequestContext, entry_id: uuid.UUID) -> EntryOut:
        patient_id = self._patient_of(ctx, ClinicalEntry, entry_id)
        if patient_id is None:
            raise NotFound("not found")

        def read(session: Session, decision: Decision) -> EntryOut:
            entry = session.execute(
                select(ClinicalEntry).where(
                    ClinicalEntry.tenant_id == ctx.tenant_id, ClinicalEntry.id == entry_id
                )
            ).scalar_one()
            if (
                entry.sensitivity != Sensitivity.NORMAL
                and f"sensitivity:{entry.sensitivity}" in decision.masks
            ):
                raise NotFound("not found")  # withheld, as in the chart
            return entry_out(session, entry, ctx.principal.practitioner_id)

        return read_path(
            self.factory,
            self.policy,
            ctx,
            capability="chart:read",
            action="clinical_entry.read",
            resource_type="clinical_entry",
            patient_id=patient_id,
            reader=read,
        )
