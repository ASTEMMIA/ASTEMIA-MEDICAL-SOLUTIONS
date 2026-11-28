"""Radiology and imaging (CEDA HS07, WF05 step 1; UAT WF05).

A clinician in the patient's care requests an examination: an order with a
radiology workflow. A radiologist vets it (accepted with a protocol, or
rejected with a reason, which revokes the order and tells the requester). A
radiographer schedules it, which gives it its accession number, and records
the study when it arrives from the modality or PACS. The study joins the order
only if the accession number finds it and the patient identity the study
carries agrees with the order's patient; otherwise it waits, off the chart, in
the reconciliation list until a radiographer links it with a reason. A
radiologist signs the report, which opens the result review for the order's
result owner; an addendum is a further signed report that keeps the earlier
ones and, when it needs review, reopens it. The PACS viewer opens a linked
study only with a short-lived token bound to that patient and that study.
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import (
    DiagnosticReport,
    ImagingRequest,
    ImagingStudy,
    Patient,
    PatientIdentifier,
    ServiceRequest,
)
from astemia.adapters.pacs import ViewerClaims, ViewerTokenError, ViewerTokens
from astemia.application import views
from astemia.application.commands import create_order, open_review
from astemia.application.context import RequestContext
from astemia.application.daybook import open_task
from astemia.application.errors import AccessDenied, Conflict, NotFound, Unprocessable
from astemia.application.policy import Decision, PolicyEngine, capabilities_for
from astemia.application.schemas import (
    AddendumIn,
    ImagingRequestOut,
    ImagingStudyOut,
    LinkStudy,
    PacsCheck,
    PacsCheckOut,
    PlaceOrder,
    ReceiveStudy,
    ReportImaging,
    RequestImaging,
    ScheduleImaging,
    VetImaging,
    ViewerAccessOut,
)
from astemia.application.write_path import CommandResult, Unit, WritePath, read_path
from astemia.domain import diagnostics as dx
from astemia.domain import radiology as rd
from astemia.domain.common import DomainError, EffectivePrecision, Sensitivity, new_id
from astemia.domain.events import EventType
from astemia.domain.tasks import TaskType
from astemia.domain.theatre import Laterality

FOLLOW_UP = timedelta(days=1)
# A study may join a request once the examination is booked, and later
# studies (further series) may join one already performed or reported.
TAKES_STUDIES = frozenset(
    {rd.ImagingState.SCHEDULED, rd.ImagingState.PERFORMED, rd.ImagingState.REPORTED}
)


def _domain(fn: Any) -> Any:
    try:
        return fn()
    except DomainError as exc:
        raise Unprocessable(str(exc), code=exc.code) from None


def study_out(row: ImagingStudy, *, with_identity: bool = False) -> ImagingStudyOut:
    return ImagingStudyOut(
        id=row.id,
        version=row.version,
        study_instance_uid=row.study_instance_uid,
        accession_number=row.accession_number,
        modality=rd.ImagingModality(row.modality),
        performed_at=row.performed_at,
        status=rd.StudyStatus(row.status),
        conflicts=row.conflicts,
        imaging_request_id=row.imaging_request_id,
        patient_id=row.patient_id,
        linked_by_id=row.linked_by_id,
        linked_at=row.linked_at,
        link_reason=row.link_reason,
        received_issuer=row.received_issuer if with_identity else None,
        received_identifier=row.received_identifier if with_identity else None,
        received_birth_date=row.received_birth_date if with_identity else None,
    )


def request_out(session: Session, row: ImagingRequest, masks: frozenset[str]) -> ImagingRequestOut:
    order = session.execute(
        select(ServiceRequest).where(
            ServiceRequest.tenant_id == row.tenant_id, ServiceRequest.id == row.service_request_id
        )
    ).scalar_one()
    studies = session.execute(
        select(ImagingStudy)
        .where(ImagingStudy.tenant_id == row.tenant_id, ImagingStudy.imaging_request_id == row.id)
        .order_by(ImagingStudy.performed_at, ImagingStudy.id)
    ).scalars()
    reports = session.execute(
        select(DiagnosticReport)
        .where(
            DiagnosticReport.tenant_id == row.tenant_id,
            DiagnosticReport.service_request_id == order.id,
        )
        .order_by(DiagnosticReport.released_at, DiagnosticReport.id)
    ).scalars()
    return ImagingRequestOut(
        id=row.id,
        version=row.version,
        service_request_id=order.id,
        patient_id=row.patient_id,
        encounter_id=order.encounter_id,
        code=order.code,
        display=order.display,
        priority=dx.OrderPriority(order.priority),
        clinical_note=order.clinical_note,
        modality=rd.ImagingModality(row.modality),
        body_site=row.body_site,
        laterality=Laterality(row.laterality),
        state=rd.ImagingState(row.state),
        protocol=row.protocol,
        vetting_note=row.vetting_note,
        vetted_by_id=row.vetted_by_id,
        scheduled_at=row.scheduled_at,
        accession_number=row.accession_number,
        studies=[study_out(s) for s in studies],
        reports=views.reports(session, list(reports), masks=masks),
    )


def _withheld(sensitivity: str, masks: frozenset[str]) -> bool:
    return sensitivity != Sensitivity.NORMAL and f"sensitivity:{sensitivity}" in masks


class Radiology:
    def __init__(
        self,
        write_path: WritePath,
        factory: sessionmaker[Session],
        policy: PolicyEngine,
        tokens: ViewerTokens,
    ) -> None:
        self.wp = write_path
        self.factory = factory
        self.policy = policy
        self.tokens = tokens

    def _patient_of(self, ctx: RequestContext, request_id: uuid.UUID) -> uuid.UUID | None:
        with self.factory() as session:
            return session.execute(
                select(ImagingRequest.patient_id).where(
                    ImagingRequest.tenant_id == ctx.tenant_id, ImagingRequest.id == request_id
                )
            ).scalar_one_or_none()

    def _reply(self, u: Unit, row: ImagingRequest, status: int = 200) -> CommandResult:
        return CommandResult(
            status, request_out(u.session, row, frozenset()).model_dump(mode="json")
        )

    # -- request and vetting ----------------------------------------------------

    def request(self, ctx: RequestContext, key: str | None, cmd: RequestImaging) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            order = create_order(
                u,
                PlaceOrder(
                    patient_id=cmd.patient_id,
                    encounter_id=cmd.encounter_id,
                    code_system=cmd.code_system,
                    code=cmd.code,
                    display=cmd.display,
                    priority=cmd.priority,
                    result_owner_id=cmd.result_owner_id,
                    clinical_note=cmd.clinical_note,
                ),
            )
            row = ImagingRequest(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                recorded_at=u.ctx.now,
                author_id=u.ctx.principal.practitioner_id,
                sensitivity=order.sensitivity,
                service_request_id=order.id,
                patient_id=order.patient_id,
                modality=cmd.modality.value,
                body_site=cmd.body_site,
                laterality=cmd.laterality.value,
                state=rd.ImagingState.REQUESTED.value,
            )
            u.session.add(row)
            u.session.flush()
            decision = u.authorize("order:create", patient_id=cmd.patient_id)
            event = u.emit(
                EventType.ORDER_PLACED,
                "service_request",
                order.id,
                1,
                u.ctx.now,
                {
                    "order_id": str(order.id),
                    "patient_id": str(order.patient_id),
                    "encounter_id": str(order.encounter_id),
                    "placer_id": order.placer_id,
                    "code_system": order.code_system,
                    "code": order.code,
                    "priority": order.priority,
                    "imaging_request_id": str(row.id),
                    "modality": row.modality,
                },
            )
            u.audit(
                decision,
                "imaging_request.create",
                "imaging_request",
                row.id,
                patient_id=row.patient_id,
                event_id=event,
            )
            return self._reply(u, row, 201)

        return self.wp.run(
            ctx,
            operation="imaging_request.create",
            capability="order:create",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json"),
            handler=handle,
            patient_id=cmd.patient_id,
        )

    def _act(
        self,
        ctx: RequestContext,
        key: str | None,
        request_id: uuid.UUID,
        expected: int | None,
        cmd: Any,
        *,
        operation: str,
        capability: str,
        apply: Any,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            row = u.get(ImagingRequest, request_id, lock=True)
            u.check_version(row.version, expected)
            order = u.get(ServiceRequest, row.service_request_id, lock=True)
            status, event = apply(u, row, order)
            row.version += 1
            u.session.flush()
            decision = u.authorize(capability)
            u.audit(
                decision,
                operation,
                "imaging_request",
                row.id,
                patient_id=row.patient_id,
                event_id=event,
            )
            return self._reply(u, row, status)

        return self.wp.run(
            ctx,
            operation=operation,
            capability=capability,
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"request_id": str(request_id), "v": expected},
            handler=handle,
            resource=("imaging_request", request_id),
        )

    def vet(
        self,
        ctx: RequestContext,
        key: str | None,
        request_id: uuid.UUID,
        expected: int | None,
        cmd: VetImaging,
    ) -> CommandResult:
        def apply(u: Unit, row: ImagingRequest, order: ServiceRequest) -> tuple[int, None]:
            _domain(lambda: rd.check_vetting(cmd.decision, cmd.protocol, cmd.reason))
            accepted = cmd.decision is rd.VetDecision.ACCEPTED
            target = rd.ImagingState.VETTED if accepted else rd.ImagingState.REJECTED
            row.state = _domain(lambda: rd.move(rd.ImagingState(row.state), target)).value
            row.protocol, row.vetting_note = cmd.protocol, cmd.reason
            row.vetted_by_id, row.vetted_at = u.ctx.principal.practitioner_id, u.ctx.now
            if not accepted:
                order.status = dx.move_order(
                    dx.ServiceRequestStatus(order.status), dx.ServiceRequestStatus.REVOKED
                ).value
                order.version += 1
                open_task(
                    u,
                    subject="An imaging request was not accepted: see the radiologist's reason",
                    task_type=TaskType.GENERAL,
                    due_at=u.ctx.now + FOLLOW_UP,
                    assignee=order.requester_id,
                    patient_id=row.patient_id,
                    source=("imaging_request", row.id),
                )
            return 200, None

        return self._act(
            ctx,
            key,
            request_id,
            expected,
            cmd,
            operation="imaging_request.vet",
            capability="imaging:vet",
            apply=apply,
        )

    def schedule(
        self,
        ctx: RequestContext,
        key: str | None,
        request_id: uuid.UUID,
        expected: int | None,
        cmd: ScheduleImaging,
    ) -> CommandResult:
        def apply(u: Unit, row: ImagingRequest, order: ServiceRequest) -> tuple[int, None]:
            row.state = _domain(
                lambda: rd.move(rd.ImagingState(row.state), rd.ImagingState.SCHEDULED)
            ).value
            row.scheduled_at = cmd.scheduled_at
            # The accession number the modality worklist and PACS will carry.
            row.accession_number = f"ACC{uuid.uuid7().hex[-10:].upper()}"
            order.filler_authority, order.filler_id = "RIS", row.accession_number
            order.version += 1
            return 200, None

        return self._act(
            ctx,
            key,
            request_id,
            expected,
            cmd,
            operation="imaging_request.schedule",
            capability="imaging:schedule",
            apply=apply,
        )

    # -- studies ------------------------------------------------------------------

    def _identity_conflicts(self, u: Unit, row: ImagingRequest, cmd: ReceiveStudy) -> list[str]:
        patient = u.get(Patient, row.patient_id)
        held = {
            (i, v)
            for i, v in u.session.execute(
                select(PatientIdentifier.issuer, PatientIdentifier.value).where(
                    PatientIdentifier.tenant_id == u.ctx.tenant_id,
                    PatientIdentifier.patient_id == patient.id,
                    PatientIdentifier.active_marker == 1,
                )
            ).all()
        }
        sent = (
            cmd.patient_identifier.issuer,
            cmd.patient_identifier.value.replace(" ", "").upper(),
        )
        return rd.identity_conflicts(held, patient.birth_date, sent, cmd.birth_date)

    def _attach(self, u: Unit, study: ImagingStudy, row: ImagingRequest) -> None:
        study.status = rd.StudyStatus.LINKED.value
        study.imaging_request_id, study.patient_id = row.id, row.patient_id
        study.sensitivity = row.sensitivity
        if rd.ImagingState(row.state) is rd.ImagingState.SCHEDULED:
            row.state = rd.move(rd.ImagingState.SCHEDULED, rd.ImagingState.PERFORMED).value
            row.version += 1

    def receive_study(
        self, ctx: RequestContext, key: str | None, cmd: ReceiveStudy
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            row = u.session.execute(
                select(ImagingRequest)
                .where(
                    ImagingRequest.tenant_id == u.ctx.tenant_id,
                    ImagingRequest.accession_number == cmd.accession_number,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if row is None:
                conflicts = ["accession_number"]
            elif rd.ImagingState(row.state) not in TAKES_STUDIES:
                conflicts = ["request_state"]
            else:
                conflicts = self._identity_conflicts(u, row, cmd)
            study = ImagingStudy(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                recorded_at=u.ctx.now,
                author_id=u.ctx.principal.practitioner_id,
                study_instance_uid=cmd.study_instance_uid,
                accession_number=cmd.accession_number,
                modality=cmd.modality.value,
                performed_at=cmd.performed_at,
                pacs_reference=cmd.pacs_reference,
                received_issuer=cmd.patient_identifier.issuer,
                received_identifier=cmd.patient_identifier.value,
                received_birth_date=cmd.birth_date,
                conflicts=conflicts,
                status=(
                    rd.StudyStatus.UNMATCHED.value
                    if row is None or "request_state" in conflicts
                    else rd.StudyStatus.IDENTITY_CONFLICT.value
                ),
            )
            if not conflicts:
                assert row is not None
                self._attach(u, study, row)
            u.session.add(study)
            u.session.flush()
            decision = u.authorize("imaging:perform")
            event = None
            if study.patient_id is not None:
                event = u.emit(
                    EventType.IMAGING_STUDY_LINKED,
                    "imaging_study",
                    study.id,
                    study.version,
                    cmd.performed_at,
                    {
                        "imaging_study_id": str(study.id),
                        "patient_id": str(study.patient_id),
                        "imaging_request_id": str(study.imaging_request_id),
                    },
                )
            u.audit(
                decision,
                "imaging_study.receive",
                "imaging_study",
                study.id,
                patient_id=study.patient_id,
                event_id=event,
            )
            return CommandResult(201, study_out(study).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="imaging_study.receive",
            capability="imaging:perform",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json"),
            handler=handle,
        )

    def link(
        self,
        ctx: RequestContext,
        key: str | None,
        study_id: uuid.UUID,
        expected: int | None,
        cmd: LinkStudy,
    ) -> CommandResult:
        """A radiographer who has checked a study against the patient links it
        to the right request, with a reason (CEDA command POST .../link)."""

        def handle(u: Unit) -> CommandResult:
            study = u.get(ImagingStudy, study_id, lock=True)
            u.check_version(study.version, expected)
            if study.status == rd.StudyStatus.LINKED:
                raise Conflict("that study is already on the chart", code="already_linked")
            row = u.get(ImagingRequest, cmd.imaging_request_id, lock=True)
            if rd.ImagingState(row.state) not in TAKES_STUDIES:
                raise Unprocessable(
                    "only a scheduled or performed request takes a study", code="request_state"
                )
            self._attach(u, study, row)
            study.linked_by_id, study.linked_at = u.ctx.principal.practitioner_id, u.ctx.now
            study.link_reason = cmd.reason
            study.version += 1
            u.session.flush()
            decision = u.authorize("imaging:reconcile")
            event = u.emit(
                EventType.IMAGING_STUDY_LINKED,
                "imaging_study",
                study.id,
                study.version,
                u.ctx.now,
                {
                    "imaging_study_id": str(study.id),
                    "patient_id": str(study.patient_id),
                    "imaging_request_id": str(row.id),
                    "reconciled": True,
                },
            )
            u.audit(
                decision,
                "imaging_study.link",
                "imaging_study",
                study.id,
                patient_id=study.patient_id,
                event_id=event,
            )
            return CommandResult(200, study_out(study).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="imaging_study.link",
            capability="imaging:reconcile",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"study_id": str(study_id), "v": expected},
            handler=handle,
            resource=("imaging_study", study_id),
        )

    def unlinked(self, ctx: RequestContext) -> list[ImagingStudyOut]:
        """The reconciliation list: studies kept off the chart, with the identity
        they arrived with."""

        def read(session: Session, decision: Decision) -> list[ImagingStudyOut]:
            rows = session.execute(
                select(ImagingStudy)
                .where(
                    ImagingStudy.tenant_id == ctx.tenant_id,
                    ImagingStudy.status != rd.StudyStatus.LINKED.value,
                )
                .order_by(ImagingStudy.recorded_at, ImagingStudy.id)
            ).scalars()
            return [study_out(r, with_identity=True) for r in rows]

        return read_path(
            self.factory,
            self.policy,
            ctx,
            capability="imaging:reconcile",
            action="imaging_study.unlinked",
            resource_type="imaging_study",
            patient_id=None,
            reader=read,
        )

    # -- reports ------------------------------------------------------------------

    def _new_report(
        self, u: Unit, order: ServiceRequest, text: str, conclusion: str | None, prior: Any
    ) -> DiagnosticReport:
        radiologist = u.ctx.principal.practitioner_id
        if radiologist is None:
            u.deny("no_practitioner")
        assert radiologist is not None
        report = DiagnosticReport(
            tenant_id=u.ctx.tenant_id,
            id=new_id(),
            recorded_at=u.ctx.now,
            effective_at=u.ctx.now,
            effective_precision=EffectivePrecision.SECOND.value,
            author_id=radiologist,
            author_role="radiologist",
            sensitivity=order.sensitivity,
            service_request_id=order.id,
            patient_id=order.patient_id,
            status=(dx.ReportStatus.AMENDED if prior else dx.ReportStatus.FINAL).value,
            released_by_id=radiologist,
            released_at=u.ctx.now,
            portal_release="withheld",
            prior_report_id=prior.id if prior else None,
            conclusion=conclusion,
            presented_form=text,
        )
        u.session.add(report)
        u.session.flush()
        return report

    def report(
        self,
        ctx: RequestContext,
        key: str | None,
        request_id: uuid.UUID,
        expected: int | None,
        cmd: ReportImaging,
    ) -> CommandResult:
        def apply(u: Unit, row: ImagingRequest, order: ServiceRequest) -> tuple[int, uuid.UUID]:
            if row.state == rd.ImagingState.REPORTED:
                raise Conflict("already reported; add an addendum", code="already_reported")
            row.state = _domain(
                lambda: rd.move(rd.ImagingState(row.state), rd.ImagingState.REPORTED)
            ).value
            report = self._new_report(u, order, cmd.findings, cmd.conclusion, None)
            order.status = dx.move_order(
                dx.ServiceRequestStatus(order.status), dx.ServiceRequestStatus.COMPLETED
            ).value
            order.version += 1
            review = open_review(u, order, report)
            event = u.emit(
                EventType.RESULT_RELEASED,
                "diagnostic_report",
                report.id,
                1,
                u.ctx.now,
                {
                    "report_id": str(report.id),
                    "order_id": str(order.id),
                    "patient_id": str(order.patient_id),
                    "status": report.status,
                    "prior_report_id": None,
                    "review_id": str(review.id),
                },
            )
            return 201, event

        return self._act(
            ctx,
            key,
            request_id,
            expected,
            cmd,
            operation="imaging_request.report",
            capability="imaging:report",
            apply=apply,
        )

    def addendum(
        self,
        ctx: RequestContext,
        key: str | None,
        request_id: uuid.UUID,
        expected: int | None,
        cmd: AddendumIn,
    ) -> CommandResult:
        def apply(u: Unit, row: ImagingRequest, order: ServiceRequest) -> tuple[int, uuid.UUID]:
            if row.state != rd.ImagingState.REPORTED:
                raise Conflict("add to a signed report only", code="not_reported")
            prior = u.session.execute(
                select(DiagnosticReport)
                .where(
                    DiagnosticReport.tenant_id == u.ctx.tenant_id,
                    DiagnosticReport.service_request_id == order.id,
                )
                .order_by(DiagnosticReport.released_at.desc(), DiagnosticReport.id.desc())
                .limit(1)
                .with_for_update()
            ).scalar_one()
            report = self._new_report(u, order, cmd.text, prior.conclusion, prior)
            review_id = open_review(u, order, report).id if cmd.needs_review else None
            event = u.emit(
                EventType.RESULT_AMENDED,
                "diagnostic_report",
                report.id,
                1,
                u.ctx.now,
                {
                    "report_id": str(report.id),
                    "order_id": str(order.id),
                    "patient_id": str(order.patient_id),
                    "status": report.status,
                    "prior_report_id": str(prior.id),
                    "review_id": str(review_id) if review_id else None,
                },
            )
            return 201, event

        return self._act(
            ctx,
            key,
            request_id,
            expected,
            cmd,
            operation="imaging_request.addendum",
            capability="imaging:report",
            apply=apply,
        )

    # -- reads --------------------------------------------------------------------

    def get(self, ctx: RequestContext, request_id: uuid.UUID) -> ImagingRequestOut:
        """For the radiology department, or for the patient's care team."""
        patient_id = self._patient_of(ctx, request_id)
        if patient_id is None:
            raise NotFound("not found")
        department = "imaging:read" in capabilities_for(ctx.principal.roles)

        def read(session: Session, decision: Decision) -> ImagingRequestOut:
            row = session.execute(
                select(ImagingRequest).where(
                    ImagingRequest.tenant_id == ctx.tenant_id, ImagingRequest.id == request_id
                )
            ).scalar_one()
            if _withheld(row.sensitivity, decision.masks):
                raise NotFound("not found")  # withheld, as in the chart
            return request_out(session, row, decision.masks)

        return read_path(
            self.factory,
            self.policy,
            ctx,
            capability="imaging:read" if department else "chart:read",
            action="imaging_request.read",
            resource_type="imaging_request",
            patient_id=patient_id,
            reader=read,
        )

    def worklist(self, ctx: RequestContext, state: rd.ImagingState) -> list[ImagingRequestOut]:
        def read(session: Session, decision: Decision) -> list[ImagingRequestOut]:
            rows = session.execute(
                select(ImagingRequest)
                .where(
                    ImagingRequest.tenant_id == ctx.tenant_id, ImagingRequest.state == state.value
                )
                .order_by(ImagingRequest.recorded_at, ImagingRequest.id)
            ).scalars()
            return [request_out(session, r, decision.masks) for r in rows]

        return read_path(
            self.factory,
            self.policy,
            ctx,
            capability="imaging:read",
            action="imaging_request.worklist",
            resource_type="imaging_request",
            patient_id=None,
            reader=read,
        )

    # -- the PACS viewer ----------------------------------------------------------

    def viewer(self, ctx: RequestContext, study_id: uuid.UUID) -> ViewerAccessOut:
        """Short-lived access to one linked study, for someone who may read the
        patient's chart. A study kept off the chart has no viewer."""
        with self.factory() as session:
            found = session.execute(
                select(ImagingStudy.patient_id, ImagingStudy.study_instance_uid).where(
                    ImagingStudy.tenant_id == ctx.tenant_id,
                    ImagingStudy.id == study_id,
                    ImagingStudy.status == rd.StudyStatus.LINKED.value,
                )
            ).one_or_none()
        if found is None:
            raise NotFound("not found")
        patient_id, uid = found
        assert patient_id is not None

        def read(session: Session, decision: Decision) -> ViewerAccessOut:
            sensitivity = session.execute(
                select(ImagingStudy.sensitivity).where(
                    ImagingStudy.tenant_id == ctx.tenant_id, ImagingStudy.id == study_id
                )
            ).scalar_one()
            if _withheld(sensitivity, decision.masks):
                raise NotFound("not found")
            practitioner = ctx.principal.practitioner_id
            assert practitioner is not None  # chart:read needs one
            token, url, expires = self.tokens.issue(
                ViewerClaims(ctx.tenant_id, patient_id, practitioner, uid), ctx.now
            )
            return ViewerAccessOut(study_instance_uid=uid, url=url, token=token, expires_at=expires)

        return read_path(
            self.factory,
            self.policy,
            ctx,
            capability="chart:read",
            action="imaging_study.view",
            resource_type="imaging_study",
            patient_id=patient_id,
            reader=read,
        )

    def pacs_check(self, cmd: PacsCheck) -> PacsCheckOut:
        """Called by the PACS before it shows a study: the token must be ours,
        current, for this study, and the study must still be that patient's."""
        try:
            claims = self.tokens.check(cmd.token, cmd.study_instance_uid)
        except ViewerTokenError:
            raise AccessDenied("viewer access refused", code="viewer_refused") from None
        with self.factory() as session:
            still = session.execute(
                select(ImagingStudy.id).where(
                    ImagingStudy.tenant_id == claims.tenant_id,
                    ImagingStudy.study_instance_uid == claims.study_instance_uid,
                    ImagingStudy.patient_id == claims.patient_id,
                    ImagingStudy.status == rd.StudyStatus.LINKED.value,
                )
            ).first()
        if still is None:
            raise AccessDenied("viewer access refused", code="viewer_refused")
        return PacsCheckOut(
            study_instance_uid=claims.study_instance_uid,
            patient_id=claims.patient_id,
            practitioner_id=claims.practitioner_id,
        )
