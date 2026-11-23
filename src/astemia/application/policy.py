"""Access decisions (CEDA 7.1). The policy engine is a port; this module holds
the decision type and the pilot rule set used until the external policy
service is qualified."""

import uuid
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from astemia.adapters.db.models import LegitimateRelationship, WorkgroupTeamMembership
from astemia.application.context import RequestContext

# Capability grants per role. Platform and tenant administrators get no
# clinical capability: clinical access requires a separate approved grant.
ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "registrar": frozenset({"patient:register", "encounter:admit", "catalogue:read"}),
    "clinician": frozenset(
        {
            "encounter:admit",
            "chart:read",
            "order:create",
            "result:acknowledge",
            "identifier:read",
            "catalogue:read",
        }
    ),
    "nurse": frozenset({"chart:read", "catalogue:read"}),
    "lab_scientist": frozenset({"result:release", "catalogue:read"}),
    # Tenant administrators configure the catalogue but hold no clinical capability.
    "tenant_admin": frozenset({"catalogue:read", "catalogue:manage"}),
    "sensitive_reader": frozenset({"sensitive:mental_health", "sensitive:sexual_health"}),
}

# Capabilities that need a legitimate care relationship with the patient.
RELATIONSHIP_BOUND = frozenset({"chart:read", "order:create"})


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    decision_id: uuid.UUID
    policy_version: str
    reason: str
    conceal: bool = False
    masks: frozenset[str] = field(default_factory=frozenset)


class PolicyEngine(Protocol):
    version: str

    def decide(
        self,
        session: Session,
        ctx: RequestContext,
        capability: str,
        *,
        patient_id: uuid.UUID | None = None,
    ) -> Decision: ...


class PilotPolicy:
    """Role capabilities plus an active care relationship for chart access."""

    def __init__(self, version: str) -> None:
        self.version = version

    def capabilities(self, ctx: RequestContext) -> frozenset[str]:
        caps: set[str] = set()
        for role in ctx.principal.roles:
            caps |= ROLE_CAPABILITIES.get(role, frozenset())
        return frozenset(caps)

    def decide(
        self,
        session: Session,
        ctx: RequestContext,
        capability: str,
        *,
        patient_id: uuid.UUID | None = None,
    ) -> Decision:
        caps = self.capabilities(ctx)
        did = uuid.uuid7()
        if capability not in caps:
            # Without the capability the caller learns nothing about the patient.
            return Decision(
                False, did, self.version, "missing_capability", conceal=patient_id is not None
            )
        if capability in RELATIONSHIP_BOUND:
            if patient_id is None or ctx.principal.practitioner_id is None:
                return Decision(False, did, self.version, "no_practitioner", conceal=True)
            if not self._has_relationship(session, ctx, patient_id):
                return Decision(False, did, self.version, "no_care_relationship", conceal=True)
        masks: set[str] = set()
        if "identifier:read" not in caps:
            masks.add("identifier.value")
        for category in (
            "mental_health",
            "sexual_health",
            "safeguarding",
            "genetics",
            "restricted",
        ):
            if f"sensitive:{category}" not in caps:
                masks.add(f"sensitivity:{category}")
        return Decision(True, did, self.version, "permit", masks=frozenset(masks))

    @staticmethod
    def _has_relationship(session: Session, ctx: RequestContext, patient_id: uuid.UUID) -> bool:
        """An active legitimate relationship, held directly or through a
        workgroup team the practitioner currently belongs to."""
        lr = LegitimateRelationship
        now = ctx.now
        teams = select(WorkgroupTeamMembership.workgroup_id).where(
            WorkgroupTeamMembership.tenant_id == ctx.tenant_id,
            WorkgroupTeamMembership.practitioner_id == ctx.principal.practitioner_id,
            WorkgroupTeamMembership.effective_from <= now,
            or_(
                WorkgroupTeamMembership.effective_to.is_(None),
                WorkgroupTeamMembership.effective_to > now,
            ),
        )
        row = session.execute(
            select(lr.id)
            .where(
                lr.tenant_id == ctx.tenant_id,
                lr.patient_id == patient_id,
                or_(
                    lr.practitioner_id == ctx.principal.practitioner_id, lr.workgroup_id.in_(teams)
                ),
                lr.start_at <= now,
                or_(lr.end_at.is_(None), lr.end_at > now),
            )
            .limit(1)
        ).first()
        return row is not None
