"""Access decisions (CEDA 7.1). The policy engine is a port; this module holds
the decision type and the pilot rule set used until the external policy
service is qualified."""

import uuid
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from astemia.adapters.db.models import (
    EmergencyGrant,
    LegitimateRelationship,
    WorkgroupTeamMembership,
)
from astemia.application.context import RequestContext
from astemia.application.views import merged_from
from astemia.domain.access import GRANT_SCOPE, is_live

# Capability grants per role. Platform and tenant administrators get no
# clinical capability: clinical access requires a separate approved grant.
ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "registrar": frozenset(
        {
            "patient:register",
            "patient:search",
            # Every patient is registered with a full address (CEDA revision 1.8).
            "address:read",
            "address:update",
            "encounter:admit",
            "catalogue:read",
            "schedule:book",
            "appointment:attend",
            "concern:raise",
            "task:assign",
            # Bed management (HS03): give an admitted patient a bed, transfer them.
            "bed:read",
            "bed:assign",
            "theatre:read",
        }
    ),
    # Schedulers (UG01) run clinic templates and bookings and triage the
    # referrals that arrive for their services. No clinical capability.
    "scheduler": frozenset(
        {
            "schedule:manage",
            "schedule:book",
            "appointment:attend",
            "referral:triage",
            # Theatre lists (HS03): book and cancel cases.
            "theatre:read",
            "theatre:book",
            "patient:search",
            "address:read",
            "catalogue:read",
            "task:assign",
        }
    ),
    "clinician": frozenset(
        {
            "encounter:admit",
            "chart:read",
            "order:create",
            "result:acknowledge",
            "identifier:read",
            "address:read",
            "patient:search",
            "catalogue:read",
            # SEC-04: may ask for time-boxed, read-only emergency access.
            "emergency:request",
            "referral:create",
            "appointment:attend",
            # Mental health safeguards (HS13): record restrictive practice and
            # legal status for patients in their care, and raise concerns.
            "safeguarding:record",
            "safeguarding:view",
            "mh_legal:manage",
            "concern:raise",
            # Clinical notes (UG02): draft, sign any note type, amend.
            "note:write",
            "note:sign",
            "note:sign_nursing",
            # Correspondence (UG04): review documents filed to them.
            "document:review",
            # Daybook (UG03).
            "task:assign",
            # Discharge (HS05, ST08): authorised sign-off.
            "discharge:sign",
            # Conditions and care plans (HS12).
            "condition:record",
            "careplan:manage",
            "careplan:deliver",
            "bed:read",
            "bed:assign",
            # Theatre (HS03, WF05): book, run the checklist, operate, hand over.
            "theatre:read",
            "theatre:book",
            "theatre:checklist",
            "theatre:perform",
        }
    ),
    # Patient index stewardship (ICRS 3.2.11-3.2.21): merge, unmerge and closure.
    "identity_steward": frozenset(
        {
            "patient:search",
            "patient:merge",
            "patient:close",
            "identifier:read",
            "address:read",
            "address:update",
        }
    ),
    "nurse": frozenset(
        {
            "chart:read",
            "address:read",
            "catalogue:read",
            "safeguarding:record",
            "safeguarding:view",
            "concern:raise",
            # Nurses draft any note but sign only nursing notes (ST04).
            "note:write",
            "note:sign_nursing",
            "task:assign",
            # Nurses deliver plan sessions such as dialysis (HS12).
            "careplan:deliver",
            # The ward team moves patients between beds (HS03) and theatre
            # nurses record the safety checklist (WF05).
            "bed:read",
            "bed:assign",
            "theatre:read",
            "theatre:checklist",
        }
    ),
    "lab_scientist": frozenset({"result:release", "catalogue:read"}),
    # Tenant administrators configure the catalogue but hold no clinical capability.
    # They also set up wards and beds, and open and close them (HS03).
    "tenant_admin": frozenset(
        {
            "catalogue:read",
            "catalogue:manage",
            "bed:read",
            "bed:manage",
            "theatre:read",
            "theatre:manage",
        }
    ),
    # Records clerks (UG04) index inbound correspondence and link it to the
    # right patient. They open quarantined files but hold no chart access.
    "records_clerk": frozenset(
        {"document:index", "patient:search", "address:read", "catalogue:read", "task:assign"}
    ),
    # Team supervisors (UG03) see every task, reassign and receive escalations.
    "team_supervisor": frozenset({"task:assign", "task:supervise"}),
    # Safeguarding leads review every restrictive intervention and concern, see
    # who accessed a patient's records, and appoint advocates. No chart access.
    "safeguarding_lead": frozenset(
        {
            "safeguarding:review",
            "concern:raise",
            "patient:search",
            "identifier:read",
            "address:read",
        }
    ),
    # An independent advocate appointed to a patient sees that patient's
    # safeguarding log, legal status and access report, and raises concerns.
    "patient_advocate": frozenset({"safeguarding:view", "access_report:read", "concern:raise"}),
    # Privacy officers review every emergency access grant (SEC-04) and hold
    # no clinical capability themselves.
    "privacy_officer": frozenset({"emergency:review"}),
    "sensitive_reader": frozenset({"sensitive:mental_health", "sensitive:sexual_health"}),
}

# Capabilities that need a legitimate care relationship with the patient.
RELATIONSHIP_BOUND = frozenset(
    {
        "chart:read",
        "order:create",
        "referral:create",
        "safeguarding:record",
        "safeguarding:view",
        "mh_legal:manage",
        "access_report:read",
        "note:write",
        "note:sign",
        "note:sign_nursing",
        "document:review",
        "discharge:sign",
        "condition:record",
        "careplan:manage",
        "careplan:deliver",
    }
)


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


def capabilities_for(roles: frozenset[str]) -> frozenset[str]:
    caps: set[str] = set()
    for role in roles:
        caps |= ROLE_CAPABILITIES.get(role, frozenset())
    return frozenset(caps)


class PilotPolicy:
    """Role capabilities plus an active care relationship for chart access."""

    def __init__(self, version: str) -> None:
        self.version = version

    def capabilities(self, ctx: RequestContext) -> frozenset[str]:
        return capabilities_for(ctx.principal.roles)

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
        reason, masks = "permit", set[str]()
        if capability in RELATIONSHIP_BOUND:
            if patient_id is None or ctx.principal.practitioner_id is None:
                return Decision(False, did, self.version, "no_practitioner", conceal=True)
            if not self._has_relationship(session, ctx, patient_id):
                if capability != GRANT_SCOPE or not self._has_grant(session, ctx, patient_id):
                    return Decision(False, did, self.version, "no_care_relationship", conceal=True)
                # Emergency access: read-only, and only what care needs now.
                reason = "emergency_grant"
                masks.add("identifier.value")
                masks.add("address")
        if "identifier:read" not in caps:
            masks.add("identifier.value")
        if "address:read" not in caps:
            masks.add("address")
        for category in (
            "mental_health",
            "sexual_health",
            "safeguarding",
            "genetics",
            "restricted",
        ):
            if f"sensitive:{category}" not in caps:
                masks.add(f"sensitivity:{category}")
        return Decision(True, did, self.version, reason, masks=frozenset(masks))

    @staticmethod
    def _has_grant(session: Session, ctx: RequestContext, patient_id: uuid.UUID) -> bool:
        """A live emergency grant for this patient (or a record merged into it),
        checked at every read so an expired grant denies the next one."""
        grants = session.execute(
            select(EmergencyGrant.starts_at, EmergencyGrant.expires_at).where(
                EmergencyGrant.tenant_id == ctx.tenant_id,
                EmergencyGrant.practitioner_id == ctx.principal.practitioner_id,
                EmergencyGrant.patient_id.in_(
                    [patient_id, *merged_from(session, ctx.tenant_id, patient_id)]
                ),
                EmergencyGrant.scope == GRANT_SCOPE,
                EmergencyGrant.expires_at > ctx.now,
            )
        ).all()
        return any(is_live(start, end, ctx.now) for start, end in grants)

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
                # A clinician caring for a record merged into this one keeps access.
                lr.patient_id.in_([patient_id, *merged_from(session, ctx.tenant_id, patient_id)]),
                or_(
                    lr.practitioner_id == ctx.principal.practitioner_id, lr.workgroup_id.in_(teams)
                ),
                lr.start_at <= now,
                or_(lr.end_at.is_(None), lr.end_at > now),
            )
            .limit(1)
        ).first()
        return row is not None
