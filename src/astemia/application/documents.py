"""Clinical correspondence (CEDA SA-12 Document and DocumentVersion; UG04).

A records clerk receives a document. Its bytes are checked and stored once,
fixed by their SHA-256 digest; a file that fails the checks is kept but never
opened or routed. The document stays quarantined until the clerk files it to a
patient, which needs a recorded adjudication when more than one patient could
match. Filing publishes it to the chart and routes it to one reviewer.
Correcting the indexing adds a version that keeps the original digest.
"""

import base64
import binascii
import uuid
from dataclasses import replace
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import (
    Document,
    DocumentObject,
    DocumentVersion,
    Encounter,
    Patient,
    Practitioner,
)
from astemia.application import views
from astemia.application.context import RequestContext
from astemia.application.daybook import close_source_tasks, open_task
from astemia.application.errors import AccessDenied, Conflict, NotFound, Unprocessable
from astemia.application.identity_review import find_matches
from astemia.application.policy import Decision, PolicyEngine
from astemia.application.schemas import (
    DocumentOut,
    DocumentSummary,
    DocumentVersionOut,
    FileDocument,
    ReceiveDocument,
    ReindexDocument,
    ReviewDocument,
)
from astemia.application.write_path import CommandResult, Unit, WritePath, audit_row
from astemia.domain import documents as dc
from astemia.domain import identity as idn
from astemia.domain.common import DomainError, EffectivePrecision, Sensitivity, new_id
from astemia.domain.events import EventType
from astemia.domain.tasks import TaskStatus, TaskType

REVIEW_WINDOW = timedelta(days=3)


def _domain(fn: Any) -> Any:
    try:
        return fn()
    except DomainError as exc:
        raise Unprocessable(str(exc), code=exc.code) from None


def _versions(session: Session, doc: Document) -> list[DocumentVersion]:
    return list(
        session.execute(
            select(DocumentVersion)
            .where(
                DocumentVersion.tenant_id == doc.tenant_id,
                DocumentVersion.document_id == doc.id,
            )
            .order_by(DocumentVersion.version_number)
        ).scalars()
    )


def document_out(
    session: Session, doc: Document, *, masks: frozenset[str], at: Any, with_candidates: bool
) -> DocumentOut:
    candidates = []
    if with_candidates and doc.candidates:
        found = {c["id"]: c for c in doc.candidates}
        rows = session.execute(
            select(Patient).where(
                Patient.tenant_id == doc.tenant_id,
                Patient.id.in_([uuid.UUID(c) for c in found]),
            )
        ).scalars()
        candidates = sorted(
            (
                views.candidate(
                    session,
                    p,
                    idn.MatchScore(found[str(p.id)]["score"], tuple(found[str(p.id)]["reasons"])),
                    masks=masks,
                    at=at,
                )
                for p in rows
            ),
            key=lambda c: -c.score,
        )
    return DocumentOut(
        id=doc.id,
        version=doc.version,
        sender=doc.sender,
        received_at=doc.received_at,
        document_type=doc.document_type,
        title=doc.title,
        media_type=doc.media_type,
        digest=doc.digest,
        scan=doc.scan,
        scan_reason=doc.scan_reason,
        status=doc.status,
        patient_id=doc.patient_id,
        encounter_id=doc.encounter_id,
        reviewer_id=doc.reviewer_id,
        reviewed_at=doc.reviewed_at,
        review_note=doc.review_note,
        adjudication=doc.adjudication,
        candidates=candidates,
        versions=[
            DocumentVersionOut(
                version_number=v.version_number,
                digest=v.digest,
                patient_id=v.patient_id,
                encounter_id=v.encounter_id,
                title=v.title,
                document_type=v.document_type,
                reason=v.reason,
                recorded_at=v.recorded_at,
                author_id=v.author_id,
            )
            for v in _versions(session, doc)
        ],
    )


def filed_documents(
    session: Session, tenant_id: uuid.UUID, patient_ids: list[uuid.UUID], visible: Any
) -> list[DocumentSummary]:
    """The chart's correspondence: filed or reviewed, newest first."""
    rows = session.execute(
        select(Document)
        .where(
            Document.tenant_id == tenant_id,
            Document.patient_id.in_(patient_ids),
            Document.status.in_([dc.DocumentStatus.FILED.value, dc.DocumentStatus.REVIEWED.value]),
        )
        .order_by(Document.received_at.desc(), Document.id)
    ).scalars()
    return [
        DocumentSummary(
            id=d.id,
            sender=d.sender,
            received_at=d.received_at,
            document_type=d.document_type,
            title=d.title,
            status=d.status,
            encounter_id=d.encounter_id,
            reviewed=d.status == dc.DocumentStatus.REVIEWED,
        )
        for d in rows
        if visible(d.sensitivity)
    ]


def _link(u: Unit, patient_id: uuid.UUID, encounter_id: uuid.UUID | None) -> Patient:
    patient = u.get(Patient, patient_id)
    if patient.status == idn.PatientStatus.MERGED:
        raise Conflict("file to the surviving record", code="patient_merged")
    if encounter_id is not None and u.get(Encounter, encounter_id).patient_id != patient.id:
        raise Unprocessable(
            "encounter does not belong to this patient", code="encounter_patient_mismatch"
        )
    return patient


def _version(u: Unit, doc: Document, reason: str) -> DocumentVersion:
    doc.current_version += 1
    row = DocumentVersion(
        tenant_id=u.ctx.tenant_id,
        id=new_id(),
        version=1,
        recorded_at=u.ctx.now,
        author_id=u.ctx.principal.practitioner_id,
        author_role="records_clerk",
        document_id=doc.id,
        version_number=doc.current_version,
        digest=doc.digest,
        patient_id=doc.patient_id,
        encounter_id=doc.encounter_id,
        title=doc.title,
        document_type=doc.document_type,
        reason=reason,
    )
    u.session.add(row)
    return row


class Documents:
    def __init__(
        self, write_path: WritePath, factory: sessionmaker[Session], policy: PolicyEngine
    ) -> None:
        self.wp = write_path
        self.factory = factory
        self.policy = policy

    # -- receive, file, reindex, review ---------------------------------------------

    def receive(self, ctx: RequestContext, key: str | None, cmd: ReceiveDocument) -> CommandResult:
        try:
            content = base64.b64decode(cmd.content_base64, validate=True)
        except binascii.Error, ValueError:
            raise Unprocessable("content is not valid base64", code="bad_content") from None
        scan, reason = _domain(lambda: dc.check_content(cmd.media_type, content))
        fingerprint = dc.digest(content)
        hint = cmd.patient_hint
        probe = None
        if hint is not None:
            nin = _domain(lambda: idn.validate_identifier("NG-NIN", hint.nin)) if hint.nin else None
            probe = idn.Demographics(
                family_name=hint.family_name,
                given_name=hint.given_names.split()[0],
                birth_date=hint.birth_date,
                birth_date_precision=EffectivePrecision.DAY,
                administrative_sex=hint.administrative_sex.value,
                identifiers=frozenset({("NG-NIN", nin)}) if nin else frozenset(),
            )

        def handle(u: Unit) -> CommandResult:
            if u.session.get(DocumentObject, (u.ctx.tenant_id, fingerprint)) is None:
                u.session.add(
                    DocumentObject(
                        tenant_id=u.ctx.tenant_id,
                        digest=fingerprint,
                        media_type=cmd.media_type,
                        size_bytes=len(content),
                        content=content,
                        stored_at=u.ctx.now,
                    )
                )
            matches = find_matches(u.session, u.ctx.tenant_id, probe, u.ctx.now) if probe else []
            doc = Document(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                version=1,
                recorded_at=u.ctx.now,
                effective_at=cmd.received_at,
                author_id=u.ctx.principal.practitioner_id,
                author_role="records_clerk",
                sender=cmd.sender,
                received_at=cmd.received_at,
                document_type=cmd.document_type,
                title=cmd.title,
                media_type=cmd.media_type,
                digest=fingerprint,
                scan=scan.value,
                scan_reason=reason,
                status=(
                    dc.DocumentStatus.QUARANTINED
                    if scan is dc.Scan.CLEAN
                    else dc.DocumentStatus.REJECTED
                ).value,
                candidates=[
                    {"id": str(p.id), "score": m.score, "reasons": list(m.reasons)}
                    for p, m in matches
                ],
                current_version=0,
            )
            u.session.add(doc)
            u.session.flush()
            _version(u, doc, "received")
            u.session.flush()
            decision = u.authorize("document:index")
            event = u.emit(
                EventType.DOCUMENT_RECEIVED,
                "document",
                doc.id,
                1,
                cmd.received_at,
                {"document_id": str(doc.id), "digest": fingerprint, "scan": doc.scan},
            )
            u.audit(decision, "document.receive", "document", doc.id, event_id=event)
            body = document_out(
                u.session, doc, masks=decision.masks, at=u.ctx.now, with_candidates=True
            )
            return CommandResult(201, body.model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="document.receive",
            capability="document:index",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json", exclude={"content_base64"})
            | {"digest": fingerprint},
            handler=handle,
        )

    def file(
        self,
        ctx: RequestContext,
        key: str | None,
        document_id: uuid.UUID,
        expected: int | None,
        cmd: FileDocument,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            doc = u.get(Document, document_id, lock=True)
            u.check_version(doc.version, expected)
            _domain(lambda: dc.check_openable(dc.Scan(doc.scan)))
            _domain(lambda: dc.check_adjudicated(len(doc.candidates), cmd.adjudication))
            doc.status = _domain(
                lambda: dc.move(dc.DocumentStatus(doc.status), dc.DocumentStatus.FILED)
            ).value
            patient = _link(u, cmd.patient_id, cmd.encounter_id)
            u.get(Practitioner, cmd.reviewer_id)
            doc.patient_id, doc.encounter_id = patient.id, cmd.encounter_id
            doc.reviewer_id, doc.adjudication = cmd.reviewer_id, cmd.adjudication
            doc.title = cmd.title or doc.title
            doc.version += 1
            _version(u, doc, "filed")
            u.session.flush()
            # UG04: the intended reviewer receives one task.
            open_task(
                u,
                subject=f"Review {doc.document_type.replace('_', ' ')} from {doc.sender}"[:200],
                task_type=TaskType.DOCUMENT_REVIEW,
                due_at=u.ctx.now + REVIEW_WINDOW,
                assignee=cmd.reviewer_id,
                patient_id=patient.id,
                source=("document", doc.id),
            )
            decision = u.authorize("document:index")
            event = u.emit(
                EventType.DOCUMENT_FILED,
                "document",
                doc.id,
                doc.version,
                u.ctx.now,
                {
                    "document_id": str(doc.id),
                    "patient_id": str(patient.id),
                    "reviewer_id": str(cmd.reviewer_id),
                    "digest": doc.digest,
                },
            )
            u.audit(
                decision,
                "document.file",
                "document",
                doc.id,
                patient_id=patient.id,
                event_id=event,
            )
            body = document_out(
                u.session, doc, masks=decision.masks, at=u.ctx.now, with_candidates=False
            )
            return CommandResult(200, body.model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="document.file",
            capability="document:index",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"document_id": str(document_id), "v": expected},
            handler=handle,
            resource=("document", document_id),
        )

    def reindex(
        self,
        ctx: RequestContext,
        key: str | None,
        document_id: uuid.UUID,
        expected: int | None,
        cmd: ReindexDocument,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            doc = u.get(Document, document_id, lock=True)
            u.check_version(doc.version, expected)
            if doc.status not in (dc.DocumentStatus.FILED, dc.DocumentStatus.REVIEWED):
                raise Conflict("only a filed document is re-indexed", code="not_filed")
            patient = _link(u, cmd.patient_id, cmd.encounter_id)
            if patient.id != doc.patient_id:
                # Filed to the wrong person: the review starts again, on the right chart.
                doc.status, doc.reviewed_at, doc.review_note = (
                    dc.DocumentStatus.FILED.value,
                    None,
                    None,
                )
                close_source_tasks(u, ("document", doc.id), TaskStatus.CANCELLED, "re-filed")
                assert doc.reviewer_id is not None  # set when the document was filed
                open_task(
                    u,
                    subject=f"Review re-filed {cmd.document_type.replace('_', ' ')}"[:200],
                    task_type=TaskType.DOCUMENT_REVIEW,
                    due_at=u.ctx.now + REVIEW_WINDOW,
                    assignee=doc.reviewer_id,
                    patient_id=patient.id,
                    source=("document", doc.id),
                )
            doc.patient_id, doc.encounter_id = patient.id, cmd.encounter_id
            doc.title, doc.document_type = cmd.title, cmd.document_type
            doc.version += 1
            _version(u, doc, cmd.reason)
            u.session.flush()
            decision = u.authorize("document:index")
            event = u.emit(
                EventType.DOCUMENT_REINDEXED,
                "document",
                doc.id,
                doc.version,
                u.ctx.now,
                {"document_id": str(doc.id), "patient_id": str(patient.id), "digest": doc.digest},
            )
            u.audit(
                decision,
                "document.reindex",
                "document",
                doc.id,
                patient_id=patient.id,
                event_id=event,
            )
            body = document_out(
                u.session, doc, masks=decision.masks, at=u.ctx.now, with_candidates=False
            )
            return CommandResult(200, body.model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="document.reindex",
            capability="document:index",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"document_id": str(document_id), "v": expected},
            handler=handle,
            resource=("document", document_id),
        )

    def review(
        self,
        ctx: RequestContext,
        key: str | None,
        document_id: uuid.UUID,
        expected: int | None,
        cmd: ReviewDocument,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            doc = u.get(Document, document_id, lock=True)
            u.check_version(doc.version, expected)
            if doc.reviewer_id != u.ctx.principal.practitioner_id:
                u.deny("not_reviewer", patient_id=doc.patient_id)
            doc.status = _domain(
                lambda: dc.move(dc.DocumentStatus(doc.status), dc.DocumentStatus.REVIEWED)
            ).value
            doc.reviewed_at, doc.review_note = u.ctx.now, cmd.note
            doc.version += 1
            close_source_tasks(u, ("document", doc.id), TaskStatus.COMPLETED, "reviewed")
            decision = u.authorize("document:review", patient_id=doc.patient_id)
            event = u.emit(
                EventType.DOCUMENT_REVIEWED,
                "document",
                doc.id,
                doc.version,
                u.ctx.now,
                {"document_id": str(doc.id), "patient_id": str(doc.patient_id)},
            )
            u.audit(
                decision,
                "document.review",
                "document",
                doc.id,
                patient_id=doc.patient_id,
                event_id=event,
            )
            body = document_out(
                u.session, doc, masks=decision.masks, at=u.ctx.now, with_candidates=False
            )
            return CommandResult(200, body.model_dump(mode="json"))

        with self.factory() as session:
            patient_id = session.execute(
                select(Document.patient_id).where(
                    Document.tenant_id == ctx.tenant_id, Document.id == document_id
                )
            ).scalar_one_or_none()
        return self.wp.run(
            ctx,
            operation="document.review",
            capability="document:review",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"document_id": str(document_id), "v": expected},
            handler=handle,
            patient_id=patient_id,
            resource=("document", document_id),
        )

    # -- reads -------------------------------------------------------------------------

    def _open(
        self, session: Session, ctx: RequestContext, document_id: uuid.UUID, action: str
    ) -> tuple[Document, Decision]:
        """A records clerk opens a document in intake; once filed, only those who
        may read the patient's chart, subject to its sensitivity. Decided and
        audited before return."""
        doc = session.execute(
            select(Document).where(Document.tenant_id == ctx.tenant_id, Document.id == document_id)
        ).scalar_one_or_none()
        if doc is None:
            raise NotFound("not found")
        filed = doc.status in (dc.DocumentStatus.FILED, dc.DocumentStatus.REVIEWED)
        if not filed:
            # Intake: the records clerk's work, before the document is on a chart.
            decision = self.policy.decide(session, ctx, "document:index")
        else:
            # Once filed it is part of the patient's record: only the care team
            # opens it, and a sensitive one stays withheld as in the chart
            # (security review, 28 November 2026).
            decision = self.policy.decide(session, ctx, "chart:read", patient_id=doc.patient_id)
            if (
                decision.allowed
                and doc.sensitivity != Sensitivity.NORMAL
                and f"sensitivity:{doc.sensitivity}" in decision.masks
            ):
                decision = replace(decision, allowed=False, reason="not_found", conceal=True)
        outcome = "success" if decision.allowed else "denied"
        session.add(audit_row(ctx, decision, action, "document", doc.id, doc.patient_id, outcome))
        session.commit()
        if not decision.allowed:
            raise AccessDenied(decision.reason, code=decision.reason, conceal=True)
        return doc, decision

    def get(self, ctx: RequestContext, document_id: uuid.UUID) -> DocumentOut:
        with self.factory() as session:
            doc, decision = self._open(session, ctx, document_id, "document.read")
            return document_out(
                session,
                doc,
                masks=decision.masks,
                at=ctx.now,
                with_candidates=doc.status == dc.DocumentStatus.QUARANTINED,
            )

    def content(self, ctx: RequestContext, document_id: uuid.UUID) -> tuple[str, bytes]:
        """The original bytes, never for a file that failed its checks."""
        with self.factory() as session:
            doc, _ = self._open(session, ctx, document_id, "document.open")
            _domain(lambda: dc.check_openable(dc.Scan(doc.scan)))
            blob = session.get(DocumentObject, (ctx.tenant_id, doc.digest))
            assert blob is not None  # stored in the same transaction as the document
            return doc.media_type, blob.content

    def worklist(
        self, ctx: RequestContext, *, status: dc.DocumentStatus, limit: int
    ) -> list[DocumentOut]:
        with self.factory() as session:
            decision = self.policy.decide(session, ctx, "document:index")
            session.add(
                audit_row(
                    ctx,
                    decision,
                    "document.worklist",
                    "document",
                    None,
                    None,
                    "success" if decision.allowed else "denied",
                )
            )
            session.commit()
            if not decision.allowed:
                raise AccessDenied(decision.reason, code=decision.reason)
            rows = session.execute(
                select(Document)
                .where(Document.tenant_id == ctx.tenant_id, Document.status == status.value)
                .order_by(Document.received_at, Document.id)
                .limit(limit)
            ).scalars()
            out = [
                document_out(
                    session,
                    d,
                    masks=decision.masks,
                    at=ctx.now,
                    with_candidates=status is dc.DocumentStatus.QUARANTINED,
                )
                for d in rows
            ]
            # Indexing details only: the reviewer's clinical note is for the
            # care team, not intake (security review, 28 November 2026).
            return [o.model_copy(update={"review_note": None}) for o in out]
