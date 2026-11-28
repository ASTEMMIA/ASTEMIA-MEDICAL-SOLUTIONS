"""FastAPI application: versioned under /v1 (CEDA 10.1)."""

import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.session import default_session_factory
from astemia.adapters.identity.tokens import TokenVerifier
from astemia.application.catalogue import Catalogue
from astemia.application.commands import Commands
from astemia.application.context import RequestContext
from astemia.application.daybook import Daybook
from astemia.application.discharge import Discharges
from astemia.application.documents import Documents
from astemia.application.emergency_access import EmergencyAccess
from astemia.application.errors import AccessDenied, ApplicationError
from astemia.application.identity_review import IdentityReview
from astemia.application.notes import Notes
from astemia.application.patient_index import PatientIndex
from astemia.application.policy import PilotPolicy
from astemia.application.queries import Queries
from astemia.application.safeguards import Safeguards
from astemia.application.scheduling import Scheduling
from astemia.application.schemas import (
    AccessReportOut,
    Acknowledge,
    ActivateService,
    AdmitEncounter,
    AmendEntry,
    AppointAdvocate,
    BookAppointment,
    CancelAppointment,
    CancelTask,
    ChartOut,
    CloseBatch,
    CloseConcern,
    ClosePatient,
    CompleteTask,
    ConcernOut,
    CreateEntry,
    CreateSlots,
    CreateTask,
    DecideReferral,
    Discharge,
    DocumentOut,
    DraftDischarge,
    DuplicateGroup,
    EmergencyGrantOut,
    EndIntervention,
    EntryOut,
    FileDocument,
    InterventionOut,
    LegalStatusOut,
    MatchOut,
    MatchQuery,
    MergePatient,
    PatientOut,
    PlaceOrder,
    ProvisionCatalogue,
    RaiseConcern,
    ReassignTask,
    ReceiveDocument,
    RecordAttendance,
    RecordIntervention,
    ReferralOut,
    ReferralRecordsOut,
    RegisterPatient,
    ReindexDocument,
    ReleaseReport,
    RequestEmergencyAccess,
    RescheduleAppointment,
    ResolveReview,
    RetireService,
    ReviewDocument,
    ReviewEmergencyAccess,
    ReviewIntervention,
    ReviewTaskOut,
    ServiceOut,
    SetLegalStatus,
    SlotOut,
    SubmitReferral,
    TaskOut,
    UnmergePatient,
    UpdateDraft,
)
from astemia.application.write_path import CommandResult, WritePath
from astemia.config import Settings, get_settings
from astemia.domain.documents import DocumentStatus
from astemia.domain.safeguards import ConcernStatus
from astemia.domain.scheduling import ReferralStatus, SlotType

log = logging.getLogger("astemia.api")
_CORRELATION = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def create_app(
    settings: Settings | None = None, factory: sessionmaker[Session] | None = None
) -> FastAPI:
    settings = settings or get_settings()
    factory = factory or default_session_factory()
    policy = PilotPolicy(settings.policy_version)
    write_path = WritePath(factory, policy)
    commands = Commands(write_path)
    catalogue = Catalogue(write_path, factory, policy)
    queries = Queries(factory, policy)
    index = PatientIndex(write_path, factory, policy)
    review = IdentityReview(write_path, factory, policy)
    emergency = EmergencyAccess(write_path, factory, policy)
    scheduling = Scheduling(write_path, factory, policy)
    safeguards = Safeguards(write_path, factory, policy)
    notes = Notes(write_path, factory, policy)
    documents = Documents(write_path, factory, policy)
    daybook = Daybook(write_path, factory, policy)
    discharges = Discharges(write_path, factory, policy)
    verifier = TokenVerifier(settings, factory)

    app = FastAPI(title="ASTEMIA Intelligence Health Platform API", version="0.1.0")

    @app.middleware("http")
    async def correlation(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("X-Correlation-ID", "")
        cid = incoming if _CORRELATION.match(incoming) else uuid.uuid4().hex
        request.state.correlation_id = cid
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = cid
        return response

    def error(request: Request, status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "correlation_id": request.state.correlation_id,
                }
            },
            # Set here as well as in the middleware: unexpected exceptions are
            # handled outside it, and their responses must carry the ID too.
            headers={"X-Correlation-ID": request.state.correlation_id},
        )

    @app.exception_handler(ApplicationError)
    async def app_error(request: Request, exc: ApplicationError) -> JSONResponse:
        if isinstance(exc, AccessDenied) and exc.conceal:
            # Same body as a genuine miss, so existence is not disclosed.
            return error(request, 404, "not_found", "not found")
        return error(request, exc.status, exc.code, str(exc))

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [".".join(str(p) for p in e["loc"]) for e in exc.errors()]
        return error(request, 422, "invalid_input", "invalid fields: " + ", ".join(fields))

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", extra={"correlation_id": request.state.correlation_id})
        return error(request, 500, "internal_error", "internal error")

    def context(
        request: Request, authorization: Annotated[str | None, Header()] = None
    ) -> RequestContext:
        principal = verifier.principal(authorization)
        return RequestContext(principal=principal, correlation_id=request.state.correlation_id)

    Ctx = Annotated[RequestContext, Depends(context)]
    IdemKey = Annotated[str | None, Header(alias="Idempotency-Key", max_length=128)]

    def respond(result: CommandResult, response: Response) -> dict[str, Any]:
        response.status_code = result.status_code
        if "version" in result.body:
            response.headers["ETag"] = f'"{result.body["version"]}"'
        if result.replayed:
            response.headers["Idempotent-Replay"] = "true"
        return result.body

    def version_of(if_match: str | None) -> int | None:
        tag = (if_match or "").removeprefix("W/").strip('"')
        return int(tag) if tag.isdigit() else None

    @app.get("/health/live", include_in_schema=False)
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", include_in_schema=False)
    def ready(response: Response) -> dict[str, str]:
        try:
            with factory() as s:
                s.execute(text("SELECT 1"))
        except SQLAlchemyError:
            log.warning("readiness check: database unavailable")
            response.status_code = 503
            return {"status": "unavailable"}
        return {"status": "ready"}

    @app.post("/v1/patients", status_code=201)
    def register_patient(
        body: RegisterPatient, ctx: Ctx, response: Response, key: IdemKey = None
    ) -> dict[str, Any]:
        return respond(commands.register_patient(ctx, key, body), response)

    @app.post("/v1/encounters", status_code=201)
    def admit(
        body: AdmitEncounter, ctx: Ctx, response: Response, key: IdemKey = None
    ) -> dict[str, Any]:
        return respond(commands.admit(ctx, key, body), response)

    @app.get("/v1/patients/{patient_id}/chart", response_model=ChartOut)
    def chart(patient_id: uuid.UUID, ctx: Ctx) -> ChartOut:
        return queries.chart(ctx, patient_id)

    # --- scheduling and referral (UG01, HS04, HS05) ---------------------------

    @app.post("/v1/slots", status_code=201)
    def create_slots(
        body: CreateSlots, ctx: Ctx, response: Response, key: IdemKey = None
    ) -> dict[str, Any]:
        return respond(scheduling.create_slots(ctx, key, body), response)

    @app.get("/v1/slots", response_model=list[SlotOut])
    def search_slots(
        ctx: Ctx,
        facility_id: uuid.UUID | None = None,
        service: Annotated[str | None, Query(max_length=64)] = None,
        practitioner_id: uuid.UUID | None = None,
        slot_type: SlotType | None = None,
        start: Annotated[AwareDatetime | None, Query(alias="from")] = None,
        end: Annotated[AwareDatetime | None, Query(alias="to")] = None,
        available_only: bool = False,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> list[SlotOut]:
        return scheduling.search(
            ctx,
            facility_id=facility_id,
            service=service,
            practitioner_id=practitioner_id,
            slot_type=slot_type,
            start=start,
            end=end,
            available_only=available_only,
            limit=limit,
        )

    @app.post("/v1/slots/{slot_id}/hold", status_code=201)
    def hold_slot(
        slot_id: uuid.UUID, ctx: Ctx, response: Response, key: IdemKey = None
    ) -> dict[str, Any]:
        return respond(scheduling.hold(ctx, key, slot_id), response)

    @app.post("/v1/appointments", status_code=201)
    def book_appointment(
        body: BookAppointment, ctx: Ctx, response: Response, key: IdemKey = None
    ) -> dict[str, Any]:
        return respond(scheduling.book(ctx, key, body), response)

    @app.post("/v1/appointments/{appointment_id}/reschedule")
    def reschedule_appointment(
        appointment_id: uuid.UUID,
        body: RescheduleAppointment,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        result = scheduling.reschedule(ctx, key, appointment_id, version_of(if_match), body)
        return respond(result, response)

    @app.post("/v1/appointments/{appointment_id}/cancel")
    def cancel_appointment(
        appointment_id: uuid.UUID,
        body: CancelAppointment,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        result = scheduling.cancel(ctx, key, appointment_id, version_of(if_match), body)
        return respond(result, response)

    @app.post("/v1/appointments/{appointment_id}/attendance")
    def record_attendance(
        appointment_id: uuid.UUID,
        body: RecordAttendance,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        result = scheduling.attendance(ctx, key, appointment_id, version_of(if_match), body)
        return respond(result, response)

    @app.post("/v1/referrals", status_code=201)
    def submit_referral(
        body: SubmitReferral, ctx: Ctx, response: Response, key: IdemKey = None
    ) -> dict[str, Any]:
        return respond(scheduling.refer(ctx, key, body), response)

    @app.get("/v1/referrals", response_model=list[ReferralOut])
    def referral_worklist(
        ctx: Ctx,
        receiving_service: Annotated[str | None, Query(max_length=64)] = None,
        status: ReferralStatus = ReferralStatus.SUBMITTED,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> list[ReferralOut]:
        return scheduling.referrals(
            ctx, receiving_service=receiving_service, status=status, limit=limit
        )

    @app.get("/v1/referrals/{referral_id}/records", response_model=ReferralRecordsOut)
    def referral_records(referral_id: uuid.UUID, ctx: Ctx) -> ReferralRecordsOut:
        return scheduling.records(ctx, referral_id)

    @app.post("/v1/referrals/{referral_id}/decision")
    def decide_referral(
        referral_id: uuid.UUID,
        body: DecideReferral,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        result = scheduling.decide(ctx, key, referral_id, version_of(if_match), body)
        return respond(result, response)

    # --- clinical notes (SA-07; UG02, WF01 step 3) ----------------------------

    @app.post("/v1/encounters/{encounter_id}/entries", status_code=201)
    def create_entry(
        encounter_id: uuid.UUID,
        body: CreateEntry,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
    ) -> dict[str, Any]:
        return respond(notes.create(ctx, key, encounter_id, body), response)

    @app.get("/v1/entries/{entry_id}", response_model=EntryOut)
    def read_entry(entry_id: uuid.UUID, ctx: Ctx) -> EntryOut:
        return notes.get(ctx, entry_id)

    @app.post("/v1/entries/{entry_id}/draft")
    def edit_draft(
        entry_id: uuid.UUID,
        body: UpdateDraft,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        result = notes.update_draft(ctx, key, entry_id, version_of(if_match), body)
        return respond(result, response)

    @app.post("/v1/entries/{entry_id}/sign")
    def sign_entry(
        entry_id: uuid.UUID,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        return respond(notes.sign(ctx, key, entry_id, version_of(if_match)), response)

    @app.post("/v1/entries/{entry_id}/amendments")
    def amend_entry(
        entry_id: uuid.UUID,
        body: AmendEntry,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        result = notes.amend(ctx, key, entry_id, version_of(if_match), body)
        return respond(result, response)

    # --- clinical correspondence (SA-12; UG04) --------------------------------

    @app.post("/v1/documents", status_code=201)
    def receive_document(
        body: ReceiveDocument, ctx: Ctx, response: Response, key: IdemKey = None
    ) -> dict[str, Any]:
        return respond(documents.receive(ctx, key, body), response)

    @app.get("/v1/documents", response_model=list[DocumentOut])
    def document_worklist(
        ctx: Ctx,
        status: DocumentStatus = DocumentStatus.QUARANTINED,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> list[DocumentOut]:
        return documents.worklist(ctx, status=status, limit=limit)

    @app.get("/v1/documents/{document_id}", response_model=DocumentOut)
    def read_document(document_id: uuid.UUID, ctx: Ctx) -> DocumentOut:
        return documents.get(ctx, document_id)

    @app.get("/v1/documents/{document_id}/content")
    def document_content(document_id: uuid.UUID, ctx: Ctx) -> Response:
        media_type, content = documents.content(ctx, document_id)
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{document_id}"',
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
        )

    @app.post("/v1/documents/{document_id}/file")
    def file_document(
        document_id: uuid.UUID,
        body: FileDocument,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        result = documents.file(ctx, key, document_id, version_of(if_match), body)
        return respond(result, response)

    @app.post("/v1/documents/{document_id}/reindex")
    def reindex_document(
        document_id: uuid.UUID,
        body: ReindexDocument,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        result = documents.reindex(ctx, key, document_id, version_of(if_match), body)
        return respond(result, response)

    @app.post("/v1/documents/{document_id}/review")
    def review_document(
        document_id: uuid.UUID,
        body: ReviewDocument,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        result = documents.review(ctx, key, document_id, version_of(if_match), body)
        return respond(result, response)

    # --- discharge (HS05, WF06 step 3, ST08) -----------------------------------

    @app.post("/v1/encounters/{encounter_id}/discharge-summary")
    def draft_discharge(
        encounter_id: uuid.UUID,
        body: DraftDischarge,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        result = discharges.draft(ctx, key, encounter_id, version_of(if_match), body)
        return respond(result, response)

    @app.post("/v1/encounters/{encounter_id}/discharge")
    def discharge_encounter(
        encounter_id: uuid.UUID,
        body: Discharge,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        result = discharges.discharge(ctx, key, encounter_id, version_of(if_match), body)
        return respond(result, response)

    # --- Daybook tasks (UG03) ----------------------------------------------------

    @app.post("/v1/tasks", status_code=201)
    def create_task(
        body: CreateTask, ctx: Ctx, response: Response, key: IdemKey = None
    ) -> dict[str, Any]:
        return respond(daybook.create(ctx, key, body), response)

    @app.get("/v1/tasks", response_model=list[TaskOut])
    def task_worklist(
        ctx: Ctx,
        view: Annotated[str, Query(pattern="^(mine|all)$")] = "mine",
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> list[TaskOut]:
        return daybook.worklist(ctx, view=view, limit=limit)

    @app.post("/v1/tasks/{task_id}/acknowledge")
    def acknowledge_task(
        task_id: uuid.UUID,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        return respond(daybook.acknowledge(ctx, key, task_id, version_of(if_match)), response)

    @app.post("/v1/tasks/{task_id}/complete")
    def complete_task(
        task_id: uuid.UUID,
        body: CompleteTask,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        return respond(daybook.complete(ctx, key, task_id, version_of(if_match), body), response)

    @app.post("/v1/tasks/{task_id}/cancel")
    def cancel_task(
        task_id: uuid.UUID,
        body: CancelTask,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        return respond(daybook.cancel(ctx, key, task_id, version_of(if_match), body), response)

    @app.post("/v1/tasks/{task_id}/reassign")
    def reassign_task(
        task_id: uuid.UUID,
        body: ReassignTask,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        return respond(daybook.reassign(ctx, key, task_id, version_of(if_match), body), response)

    # --- mental health safeguards (HS13, B11; ICRS 5.5.9) ----------------------

    @app.post("/v1/restrictive-interventions", status_code=201)
    def record_intervention(
        body: RecordIntervention, ctx: Ctx, response: Response, key: IdemKey = None
    ) -> dict[str, Any]:
        return respond(safeguards.record_intervention(ctx, key, body), response)

    @app.post("/v1/restrictive-interventions/{intervention_id}/end")
    def end_intervention(
        intervention_id: uuid.UUID,
        body: EndIntervention,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        result = safeguards.end_intervention(ctx, key, intervention_id, version_of(if_match), body)
        return respond(result, response)

    @app.post("/v1/restrictive-interventions/{intervention_id}/review")
    def review_intervention(
        intervention_id: uuid.UUID,
        body: ReviewIntervention,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        result = safeguards.review_intervention(
            ctx, key, intervention_id, version_of(if_match), body
        )
        return respond(result, response)

    @app.get("/v1/restrictive-interventions", response_model=list[InterventionOut])
    def intervention_review_queue(
        ctx: Ctx, reviewed: bool = False, limit: Annotated[int, Query(ge=1, le=200)] = 50
    ) -> list[InterventionOut]:
        return safeguards.review_queue(ctx, reviewed=reviewed, limit=limit)

    @app.get(
        "/v1/patients/{patient_id}/restrictive-interventions",
        response_model=list[InterventionOut],
    )
    def patient_interventions(patient_id: uuid.UUID, ctx: Ctx) -> list[InterventionOut]:
        return safeguards.interventions(ctx, patient_id)

    @app.post("/v1/patients/{patient_id}/legal-status", status_code=201)
    def set_legal_status(
        patient_id: uuid.UUID,
        body: SetLegalStatus,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
    ) -> dict[str, Any]:
        return respond(safeguards.set_legal_status(ctx, key, patient_id, body), response)

    @app.get("/v1/patients/{patient_id}/legal-status", response_model=list[LegalStatusOut])
    def legal_status_history(patient_id: uuid.UUID, ctx: Ctx) -> list[LegalStatusOut]:
        return safeguards.legal_history(ctx, patient_id)

    @app.get("/v1/legal-status/expiring", response_model=list[LegalStatusOut])
    def legal_status_expiring(ctx: Ctx) -> list[LegalStatusOut]:
        return safeguards.expiring(ctx)

    @app.post("/v1/safeguarding-concerns", status_code=201)
    def raise_concern(
        body: RaiseConcern, ctx: Ctx, response: Response, key: IdemKey = None
    ) -> dict[str, Any]:
        return respond(safeguards.raise_concern(ctx, key, body), response)

    @app.get("/v1/safeguarding-concerns", response_model=list[ConcernOut])
    def concern_worklist(
        ctx: Ctx,
        status: ConcernStatus = ConcernStatus.OPEN,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> list[ConcernOut]:
        return safeguards.concerns(ctx, status=status, limit=limit)

    @app.post("/v1/safeguarding-concerns/{concern_id}/outcome")
    def close_concern(
        concern_id: uuid.UUID,
        body: CloseConcern,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        result = safeguards.close_concern(ctx, key, concern_id, version_of(if_match), body)
        return respond(result, response)

    @app.post("/v1/patients/{patient_id}/advocates", status_code=201)
    def appoint_advocate(
        patient_id: uuid.UUID,
        body: AppointAdvocate,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
    ) -> dict[str, Any]:
        return respond(safeguards.appoint_advocate(ctx, key, patient_id, body), response)

    @app.get("/v1/patients/{patient_id}/access-report", response_model=AccessReportOut)
    def access_report(
        patient_id: uuid.UUID,
        ctx: Ctx,
        start: Annotated[AwareDatetime | None, Query(alias="from")] = None,
        end: Annotated[AwareDatetime | None, Query(alias="to")] = None,
    ) -> AccessReportOut:
        return safeguards.access_report(ctx, patient_id, start=start, end=end)

    # --- emergency access (SEC-04, WF02 step 4) -------------------------------

    @app.post("/v1/emergency-grants", status_code=201)
    def request_emergency_access(
        body: RequestEmergencyAccess, ctx: Ctx, response: Response, key: IdemKey = None
    ) -> dict[str, Any]:
        return respond(emergency.request(ctx, key, body), response)

    @app.get("/v1/emergency-grants", response_model=list[EmergencyGrantOut])
    def emergency_grants(
        ctx: Ctx, reviewed: bool = False, limit: Annotated[int, Query(ge=1, le=200)] = 50
    ) -> list[EmergencyGrantOut]:
        return emergency.grants(ctx, reviewed=reviewed, limit=limit)

    @app.post("/v1/emergency-grants/{grant_id}/review")
    def review_emergency_access(
        grant_id: uuid.UUID,
        body: ReviewEmergencyAccess,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        tag = (if_match or "").removeprefix("W/").strip('"')
        expected = int(tag) if tag.isdigit() else None
        return respond(emergency.review(ctx, key, grant_id, expected, body), response)

    @app.post("/v1/orders", status_code=201)
    def place_order(
        body: PlaceOrder, ctx: Ctx, response: Response, key: IdemKey = None
    ) -> dict[str, Any]:
        return respond(commands.place_order(ctx, key, body), response)

    @app.post("/v1/diagnostic-reports", status_code=201)
    def release(
        body: ReleaseReport, ctx: Ctx, response: Response, key: IdemKey = None
    ) -> dict[str, Any]:
        return respond(commands.release_report(ctx, key, body), response)

    @app.post("/v1/result-reviews/{review_id}/acknowledge")
    def acknowledge(
        review_id: uuid.UUID,
        body: Acknowledge,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> dict[str, Any]:
        expected = (
            int(if_match.strip('W/"')) if if_match and if_match.strip('W/"').isdigit() else None
        )
        return respond(commands.acknowledge(ctx, key, review_id, expected, body), response)

    def expected_version(if_match: str | None) -> int | None:
        tag = (if_match or "").removeprefix("W/").strip('"')
        return int(tag) if tag.isdigit() else None

    IfMatch = Annotated[str | None, Header(alias="If-Match")]

    # --- patient index (ICRS module 102, section 3.2) ----------------------

    @app.get("/v1/patient-index", response_model=list[PatientOut])
    def search_patients(
        ctx: Ctx,
        nin: Annotated[str | None, Query(max_length=32)] = None,
        family_name: Annotated[str | None, Query(min_length=2, max_length=100)] = None,
        given_name: Annotated[str | None, Query(max_length=100)] = None,
        birth_date: date | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
    ) -> list[PatientOut]:
        return index.search(
            ctx,
            nin=nin,
            family_name=family_name,
            given_name=given_name,
            birth_date=birth_date,
            limit=limit,
        )

    @app.get("/v1/patient-index/duplicates", response_model=list[DuplicateGroup])
    def duplicate_patients(ctx: Ctx) -> list[DuplicateGroup]:
        return index.duplicates(ctx)

    # Identity review (UG02, WF01 steps 1 and 4).

    @app.post("/v1/patient-index/match", response_model=MatchOut)
    def match_patients(body: MatchQuery, ctx: Ctx) -> MatchOut:
        return review.match(ctx, body)

    @app.get("/v1/identity-review-tasks", response_model=list[ReviewTaskOut])
    def review_tasks(
        ctx: Ctx, resolved: bool = False, limit: Annotated[int, Query(ge=1, le=200)] = 50
    ) -> list[ReviewTaskOut]:
        return review.tasks(ctx, resolved=resolved, limit=limit)

    @app.post("/v1/identity-review-tasks/{task_id}/resolve")
    def resolve_review(
        task_id: uuid.UUID,
        body: ResolveReview,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: IfMatch = None,
    ) -> dict[str, Any]:
        return respond(
            review.resolve(ctx, key, task_id, expected_version(if_match), body), response
        )

    @app.post("/v1/patients/{patient_id}/merge")
    def merge_patient(
        patient_id: uuid.UUID,
        body: MergePatient,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: IfMatch = None,
    ) -> dict[str, Any]:
        return respond(
            index.merge(ctx, key, patient_id, expected_version(if_match), body), response
        )

    @app.post("/v1/merge-links/{link_id}/unmerge")
    def unmerge_patient(
        link_id: uuid.UUID, body: UnmergePatient, ctx: Ctx, response: Response, key: IdemKey = None
    ) -> dict[str, Any]:
        return respond(index.unmerge(ctx, key, link_id, body), response)

    @app.post("/v1/patients/{patient_id}/close")
    def close_patient(
        patient_id: uuid.UUID,
        body: ClosePatient,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: IfMatch = None,
    ) -> dict[str, Any]:
        return respond(
            index.close(ctx, key, patient_id, expected_version(if_match), body), response
        )

    @app.post("/v1/patient-index/closures")
    def close_patients(
        body: CloseBatch, ctx: Ctx, response: Response, key: IdemKey = None
    ) -> dict[str, Any]:
        return respond(index.close_batch(ctx, key, body), response)

    # --- service catalogue (Annex A16) -------------------------------------

    @app.post("/v1/control/catalogue/provision", status_code=201)
    def provision(
        body: ProvisionCatalogue, ctx: Ctx, response: Response, key: IdemKey = None
    ) -> dict[str, Any]:
        return respond(catalogue.provision(ctx, key, body), response)

    @app.post("/v1/control/services/{service_id}/activate")
    def activate_service(
        service_id: uuid.UUID,
        body: ActivateService,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: IfMatch = None,
    ) -> dict[str, Any]:
        return respond(
            catalogue.activate(ctx, key, service_id, expected_version(if_match), body), response
        )

    @app.post("/v1/control/services/{service_id}/retire")
    def retire_service(
        service_id: uuid.UUID,
        body: RetireService,
        ctx: Ctx,
        response: Response,
        key: IdemKey = None,
        if_match: IfMatch = None,
    ) -> dict[str, Any]:
        return respond(
            catalogue.retire(ctx, key, service_id, expected_version(if_match), body), response
        )

    @app.get("/v1/services", response_model=list[ServiceOut])
    def search_services(
        ctx: Ctx,
        q: Annotated[str | None, Query(max_length=100)] = None,
        facility_id: uuid.UUID | None = None,
        age: Annotated[str | None, Query(pattern="^(adult|paediatric)$")] = None,
        care_setting: Annotated[str | None, Query(max_length=16)] = None,
        include_drafts: bool = False,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> list[ServiceOut]:
        return catalogue.search(
            ctx,
            q=q,
            facility_id=facility_id,
            age=age,
            care_setting=care_setting,
            include_drafts=include_drafts,
            limit=limit,
        )

    return app
