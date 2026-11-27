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
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.session import default_session_factory
from astemia.adapters.identity.tokens import TokenVerifier
from astemia.application.catalogue import Catalogue
from astemia.application.commands import Commands
from astemia.application.context import RequestContext
from astemia.application.errors import AccessDenied, ApplicationError
from astemia.application.patient_index import PatientIndex
from astemia.application.policy import PilotPolicy
from astemia.application.queries import Queries
from astemia.application.schemas import (
    Acknowledge,
    ActivateService,
    AdmitEncounter,
    ChartOut,
    CloseBatch,
    ClosePatient,
    DuplicateGroup,
    MergePatient,
    PatientOut,
    PlaceOrder,
    ProvisionCatalogue,
    RegisterPatient,
    ReleaseReport,
    RetireService,
    ServiceOut,
    UnmergePatient,
)
from astemia.application.write_path import CommandResult, WritePath
from astemia.config import Settings, get_settings

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
