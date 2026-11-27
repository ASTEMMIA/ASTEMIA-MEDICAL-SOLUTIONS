"""The staff web app's session: who is signed in, development sign-in, and the
built app itself at /app/ (CEDA NFR-03).

Development sign-in lets someone pick a seeded account in a test or pilot
environment. It is off unless ASTEMIA_DEV_SIGN_IN is set and never available
in production, where tokens come from the identity provider.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import Membership, Practitioner, Tenant
from astemia.adapters.identity.tokens import issue_dev_token
from astemia.application.context import RequestContext
from astemia.application.errors import NotFound, Unauthenticated
from astemia.application.policy import capabilities_for
from astemia.config import Settings

TOKEN_TTL_S = 8 * 3600  # one shift

# The app is static and same-origin: nothing else may run or frame it.
APP_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; "
        "script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-cache",
}


class MeOut(BaseModel):
    subject: str
    tenant_id: uuid.UUID
    tenant_name: str
    roles: list[str]
    capabilities: list[str]
    practitioner_id: uuid.UUID | None
    display_name: str


class DevAccount(BaseModel):
    subject: str
    display_name: str
    roles: list[str]


class DevSignIn(BaseModel):
    tenant_id: uuid.UUID
    subject: Annotated[str, StringConstraints(min_length=3, max_length=255)]


class DevToken(BaseModel):
    access_token: str
    token_type: str = "Bearer"  # noqa: S105 - the OAuth token type, not a secret
    expires_in: int = Field(description="Seconds")


def _active(now: datetime) -> Any:
    return (
        Membership.active.is_(True),
        Membership.valid_from <= now,
        or_(Membership.valid_to.is_(None), Membership.valid_to > now),
    )


def mount_staff(
    app: FastAPI,
    settings: Settings,
    factory: sessionmaker[Session],
    request_context: Callable[..., RequestContext],
) -> None:
    dev_enabled = settings.dev_sign_in and settings.environment != "production"
    Ctx = Annotated[RequestContext, Depends(request_context)]

    @app.get("/v1/me", response_model=MeOut)
    def me(context: Ctx) -> MeOut:
        with factory() as session:
            tenant = session.get(Tenant, context.tenant_id)
            pid = context.principal.practitioner_id
            practitioner = session.get(Practitioner, (context.tenant_id, pid)) if pid else None
        assert tenant is not None  # the membership that authenticated names it
        roles = context.principal.roles
        return MeOut(
            subject=context.principal.subject,
            tenant_id=context.tenant_id,
            tenant_name=tenant.name,
            roles=sorted(roles),
            capabilities=sorted(capabilities_for(roles)),
            practitioner_id=pid,
            display_name=practitioner.display_name if practitioner else context.principal.subject,
        )

    @app.get("/v1/dev/accounts", response_model=list[DevAccount], include_in_schema=False)
    def dev_accounts(tenant_id: uuid.UUID) -> list[DevAccount]:
        if not dev_enabled:
            raise NotFound("not found")
        now = datetime.now(UTC)
        with factory() as session:
            rows = session.execute(
                select(Membership, Practitioner.display_name)
                .outerjoin(
                    Practitioner,
                    (Practitioner.tenant_id == Membership.tenant_id)
                    & (Practitioner.id == Membership.practitioner_id),
                )
                .where(Membership.tenant_id == tenant_id, *_active(now))
                .order_by(Membership.subject)
            ).all()
        return [
            DevAccount(subject=m.subject, display_name=name or m.subject, roles=sorted(m.roles))
            for m, name in rows
        ]

    @app.post("/v1/dev/sign-in", response_model=DevToken, include_in_schema=False)
    def dev_sign_in(body: DevSignIn) -> DevToken:
        if not dev_enabled:
            raise NotFound("not found")
        now = datetime.now(UTC)
        with factory() as session:
            found = session.execute(
                select(Membership.subject).where(
                    Membership.tenant_id == body.tenant_id,
                    Membership.subject == body.subject,
                    *_active(now),
                )
            ).first()
        if found is None:
            raise Unauthenticated("no active membership for this account")
        token = issue_dev_token(settings, body.subject, body.tenant_id, ttl_s=TOKEN_TTL_S)
        return DevToken(access_token=token, expires_in=TOKEN_TTL_S)

    if settings.web_dir is None:
        return
    root = Path(settings.web_dir).resolve()
    index = root / "index.html"

    @app.get("/app", include_in_schema=False)
    @app.get("/app/{path:path}", include_in_schema=False)
    def web_app(path: str = "") -> Response:
        """Files from the built app; any other path is a client-side route."""
        target = (root / path).resolve()
        if path and target.is_file() and target.is_relative_to(root):
            response: Response = FileResponse(target)
        else:
            response = FileResponse(index, media_type="text/html")
        response.headers.update(APP_HEADERS)
        return response
