"""Who is acting, for which tenant and why. Built only from verified identity."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    tenant_id: uuid.UUID
    roles: frozenset[str]
    practitioner_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class RequestContext:
    principal: Principal
    correlation_id: str
    purpose: str = "treatment"
    now: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def tenant_id(self) -> uuid.UUID:
        return self.principal.tenant_id
