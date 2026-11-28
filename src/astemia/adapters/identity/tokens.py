"""Bearer-token verification and membership binding (API-01).

The token proves who the caller is and which tenant they are acting in. Roles
come from the tenant's own membership table, never from the token or request.
"""

import uuid
from datetime import UTC, datetime

import jwt
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import Membership
from astemia.application.context import Principal
from astemia.application.errors import Unauthenticated
from astemia.config import Settings


class TokenVerifier:
    def __init__(self, settings: Settings, factory: sessionmaker[Session]) -> None:
        self.settings = settings
        self.factory = factory

    def principal(self, authorization: str | None) -> Principal:
        if not authorization or not authorization.startswith("Bearer "):
            raise Unauthenticated("bearer token required")
        token = authorization.removeprefix("Bearer ").strip()
        try:
            claims = jwt.decode(
                token,
                self.settings.jwt_key.get_secret_value(),
                algorithms=[self.settings.jwt_algorithm],
                audience=self.settings.jwt_audience,
                issuer=self.settings.jwt_issuer,
                options={"require": ["exp", "iat", "sub", "tid"]},
            )
            tenant_id = uuid.UUID(str(claims["tid"]))
        except (jwt.PyJWTError, ValueError) as exc:
            raise Unauthenticated("invalid token") from exc
        subject = str(claims["sub"])
        now = datetime.now(UTC)
        with self.factory() as session:
            m = session.execute(
                select(Membership).where(
                    Membership.tenant_id == tenant_id,
                    Membership.subject == subject,
                    Membership.active.is_(True),
                    Membership.valid_from <= now,
                    or_(Membership.valid_to.is_(None), Membership.valid_to > now),
                )
            ).scalar_one_or_none()
        if m is None:
            raise Unauthenticated("no active membership for this tenant")
        return Principal(
            subject=subject,
            tenant_id=tenant_id,
            roles=frozenset(m.roles),
            practitioner_id=m.practitioner_id,
        )


def issue_dev_token(
    settings: Settings, subject: str, tenant_id: uuid.UUID, ttl_s: int = 3600
) -> str:
    """Development and test helper. Production tokens come from the identity provider."""
    if not settings.is_development:
        raise RuntimeError(f"development tokens are disabled in {settings.environment}")
    now = int(datetime.now(UTC).timestamp())
    return jwt.encode(
        {
            "sub": subject,
            "tid": str(tenant_id),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": now,
            "exp": now + ttl_s,
        },
        settings.jwt_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
