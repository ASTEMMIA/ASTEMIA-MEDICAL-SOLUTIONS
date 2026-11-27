"""Service catalogue commands and search (AMS-002 Annex A16, CAT-01..05)."""

import re
import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import (
    ClinicalService,
    FacilityService,
    OrganisationSite,
    OrgUnit,
    Practitioner,
    ServiceAlias,
    ServiceChange,
    ServiceDirectoryListing,
    ServiceTemplate,
    ServiceTemplateGroup,
    WorkQueue,
)
from astemia.application.context import RequestContext
from astemia.application.errors import AccessDenied, Unprocessable
from astemia.application.policy import PolicyEngine
from astemia.application.schemas import (
    ActivateService,
    ProvisionCatalogue,
    ProvisionOut,
    RetireService,
    ServiceOut,
)
from astemia.application.write_path import CommandResult, Unit, WritePath, audit_row
from astemia.catalogue import load_catalogue
from astemia.domain import catalogue as cat
from astemia.domain.common import DomainError, new_id
from astemia.domain.events import EventType


def _slug(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", text.upper()).strip("-")[:28]


def _domain(fn: Any) -> Any:
    try:
        return fn()
    except DomainError as exc:
        raise Unprocessable(str(exc), code=exc.code) from None


class Catalogue:
    def __init__(self, write_path: WritePath, factory: sessionmaker[Session], policy: PolicyEngine):
        self.wp = write_path
        self.factory = factory
        self.policy = policy

    # -- CAT-01: instantiate the standard catalogue as drafts --------------------

    def provision(
        self, ctx: RequestContext, key: str | None, cmd: ProvisionCatalogue
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            u.get(OrganisationSite, cmd.facility_id)
            tid, now = u.ctx.tenant_id, u.ctx.now
            env = {
                "tenant_id": tid,
                "recorded_at": now,
                "author_id": u.ctx.principal.practitioner_id,
            }
            q = select(ServiceTemplateGroup)
            if cmd.group_codes:
                q = q.where(ServiceTemplateGroup.code.in_(cmd.group_codes))
            groups = u.session.execute(q.order_by(ServiceTemplateGroup.code)).scalars().all()
            if cmd.group_codes and len(groups) != len(set(cmd.group_codes)):
                raise Unprocessable("unknown department group code", code="unknown_group")
            units = {
                o.code: o
                for o in u.session.execute(
                    select(OrgUnit).where(OrgUnit.tenant_id == tid)
                ).scalars()
            }
            existing = set(
                u.session.execute(
                    select(ClinicalService.code).where(ClinicalService.tenant_id == tid)
                ).scalars()
            )

            def unit(code: str, name: str, kind: str, parent: OrgUnit | None) -> OrgUnit:
                if code not in units:
                    units[code] = OrgUnit(
                        id=new_id(),
                        code=code,
                        name=name,
                        unit_type=kind,
                        parent_id=parent.id if parent else None,
                        effective_from=now,
                        **env,
                    )
                    u.session.add(units[code])
                    u.session.flush()
                return units[code]

            listings: dict[str, set[str]] = {}
            for code, listing in u.session.execute(
                select(ServiceDirectoryListing.service_code, ServiceDirectoryListing.listing)
            ):
                listings.setdefault(code, set()).add(listing)
            created = skipped = 0
            for g in groups:
                division = unit(f"DIV-{_slug(g.division)}", g.division, "division", None)
                department = unit(g.code, g.name, "department", division)
                templates = u.session.execute(
                    select(ServiceTemplate)
                    .where(ServiceTemplate.group_code == g.code)
                    .order_by(ServiceTemplate.code)
                ).scalars()
                for t in templates:
                    if t.code in existing:
                        skipped += 1
                        continue
                    svc = ClinicalService(
                        id=new_id(),
                        code=t.code,
                        name=t.name,
                        department_id=department.id,
                        template_code=t.code,
                        age_policy=t.age_policy,
                        care_settings=t.care_settings,
                        status=cat.ServiceStatus.DRAFT.value,
                        effective_from=now,
                        **env,
                    )
                    u.session.add(svc)
                    u.session.flush()
                    aliases = {g.name} | set(listings.get(t.code, ()))
                    aliases.discard(t.name)
                    for alias in sorted(aliases):
                        u.session.add(
                            ServiceAlias(id=new_id(), service_id=svc.id, alias=alias, **env)
                        )
                    u.session.add(
                        FacilityService(
                            id=new_id(),
                            service_id=svc.id,
                            facility_id=cmd.facility_id,
                            care_settings=t.care_settings,
                            enabled=False,
                            effective_from=now,
                            **env,
                        )
                    )
                    created += 1
            version = load_catalogue()["version"]
            u.session.add(
                ServiceChange(
                    tenant_id=tid,
                    id=new_id(),
                    change_type="provision",
                    requester=u.ctx.principal.subject,
                    reason=f"provision {len(groups)} groups from catalogue {version}",
                    new_status=cat.ServiceStatus.DRAFT.value,
                    catalogue_version=version,
                    recorded_at=now,
                    correlation_id=u.ctx.correlation_id,
                )
            )
            u.session.flush()
            decision = u.authorize("catalogue:manage")
            event = u.emit(
                EventType.SERVICE_CATALOGUE_CHANGED,
                "catalogue",
                tid,
                1,
                now,
                {
                    "change": "provision",
                    "facility_id": str(cmd.facility_id),
                    "services_created": created,
                },
            )
            u.audit(decision, "catalogue.provision", "catalogue", None, event_id=event)
            out = ProvisionOut(
                facility_id=cmd.facility_id,
                groups=len(groups),
                services_created=created,
                services_existing=skipped,
            )
            return CommandResult(201, out.model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="catalogue.provision",
            capability="catalogue:manage",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json"),
            handler=handle,
        )

    # -- CAT-01/CAT-05: activation needs owner, facility, approval and a queue ---

    def activate(
        self,
        ctx: RequestContext,
        key: str | None,
        service_id: uuid.UUID,
        expected: int | None,
        cmd: ActivateService,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            svc = u.get(ClinicalService, service_id, lock=True)
            u.check_version(svc.version, expected)
            owner = u.session.get(Practitioner, (u.ctx.tenant_id, cmd.owner_id))
            fs = u.session.execute(
                select(FacilityService)
                .where(
                    FacilityService.tenant_id == u.ctx.tenant_id,
                    FacilityService.service_id == svc.id,
                    FacilityService.facility_id == cmd.facility_id,
                )
                .with_for_update()
            ).scalar_one_or_none()
            _domain(
                lambda: cat.check_activation(
                    owner is not None, fs is not None, cmd.approval_reference
                )
            )
            assert fs is not None
            previous = svc.status
            svc.status = _domain(
                lambda: cat.move(cat.ServiceStatus(svc.status), cat.ServiceStatus.ACTIVE)
            ).value
            svc.owner_id = cmd.owner_id
            svc.version += 1
            fs.enabled = True
            fs.version += 1
            queue_code = f"{svc.code}-{cmd.facility_id.hex[:8]}"
            if (
                u.session.execute(
                    select(WorkQueue.id).where(
                        WorkQueue.tenant_id == u.ctx.tenant_id, WorkQueue.code == queue_code
                    )
                ).first()
                is None
            ):
                u.session.add(
                    WorkQueue(
                        tenant_id=u.ctx.tenant_id,
                        id=new_id(),
                        recorded_at=u.ctx.now,
                        service_id=svc.id,
                        facility_id=cmd.facility_id,
                        code=queue_code,
                        name=f"{svc.name} worklist",
                        eligible_roles=cmd.queue_roles,
                    )
                )
            self._change(u, "activate", svc, previous, cmd.approval_reference)
            u.session.flush()
            decision = u.authorize("catalogue:manage")
            event = u.emit(
                EventType.SERVICE_CATALOGUE_CHANGED,
                "clinical_service",
                svc.id,
                svc.version,
                u.ctx.now,
                {
                    "change": "activate",
                    "service_code": svc.code,
                    "facility_id": str(cmd.facility_id),
                },
            )
            u.audit(decision, "catalogue.activate", "clinical_service", svc.id, event_id=event)
            return CommandResult(200, self._out(u.session, svc).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="catalogue.activate",
            capability="catalogue:manage",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"service_id": str(service_id), "v": expected},
            handler=handle,
            resource=("clinical_service", service_id),
        )

    # -- CAT-03: retirement blocks new work and keeps history --------------------

    def retire(
        self,
        ctx: RequestContext,
        key: str | None,
        service_id: uuid.UUID,
        expected: int | None,
        cmd: RetireService,
    ) -> CommandResult:
        def handle(u: Unit) -> CommandResult:
            svc = u.get(ClinicalService, service_id, lock=True)
            u.check_version(svc.version, expected)
            previous = svc.status
            svc.status = _domain(
                lambda: cat.move(cat.ServiceStatus(svc.status), cat.ServiceStatus.RETIRED)
            ).value
            svc.effective_to = u.ctx.now
            svc.version += 1
            for fs in u.session.execute(
                select(FacilityService).where(
                    FacilityService.tenant_id == u.ctx.tenant_id,
                    FacilityService.service_id == svc.id,
                )
            ).scalars():
                fs.enabled = False
                fs.effective_to = u.ctx.now
                fs.version += 1
            for q in u.session.execute(
                select(WorkQueue).where(
                    WorkQueue.tenant_id == u.ctx.tenant_id, WorkQueue.service_id == svc.id
                )
            ).scalars():
                q.accepting = False
                q.version += 1
            self._change(u, "retire", svc, previous, None, reason=cmd.reason)
            u.session.flush()
            decision = u.authorize("catalogue:manage")
            event = u.emit(
                EventType.SERVICE_CATALOGUE_CHANGED,
                "clinical_service",
                svc.id,
                svc.version,
                u.ctx.now,
                {"change": "retire", "service_code": svc.code},
            )
            u.audit(decision, "catalogue.retire", "clinical_service", svc.id, event_id=event)
            return CommandResult(200, self._out(u.session, svc).model_dump(mode="json"))

        return self.wp.run(
            ctx,
            operation="catalogue.retire",
            capability="catalogue:manage",
            idempotency_key=key,
            payload=cmd.model_dump(mode="json") | {"service_id": str(service_id), "v": expected},
            handler=handle,
            resource=("clinical_service", service_id),
        )

    # -- CAT-02: search by name or alias within the caller's scope ---------------

    def search(
        self,
        ctx: RequestContext,
        *,
        q: str | None,
        facility_id: uuid.UUID | None,
        age: str | None,
        care_setting: str | None,
        include_drafts: bool,
        limit: int,
    ) -> list[ServiceOut]:
        with self.factory() as session:
            decision = self.policy.decide(session, ctx, "catalogue:read")
            if not decision.allowed:
                session.add(
                    audit_row(ctx, decision, "catalogue.search", "catalogue", None, None, "denied")
                )
                session.commit()
                raise AccessDenied(decision.reason, code=decision.reason)
            if include_drafts:
                manage = self.policy.decide(session, ctx, "catalogue:manage")
                if not manage.allowed:
                    raise AccessDenied(
                        "drafts are visible to catalogue managers", code="missing_capability"
                    )
            tid = ctx.tenant_id
            stmt = select(ClinicalService).where(ClinicalService.tenant_id == tid)
            statuses = ["active", "draft"] if include_drafts else ["active"]
            stmt = stmt.where(ClinicalService.status.in_(statuses))
            if q:
                like = f"%{q.strip()}%"
                aliased = select(ServiceAlias.service_id).where(
                    ServiceAlias.tenant_id == tid,
                    ServiceAlias.active.is_(True),
                    ServiceAlias.alias.like(like),
                )
                stmt = stmt.where(
                    or_(ClinicalService.name.like(like), ClinicalService.id.in_(aliased))
                )
            if age in ("adult", "paediatric"):
                stmt = stmt.where(ClinicalService.age_policy.in_([age, "all"]))
            if facility_id:
                offered = select(FacilityService.service_id).where(
                    FacilityService.tenant_id == tid,
                    FacilityService.facility_id == facility_id,
                )
                if not include_drafts:
                    offered = offered.where(FacilityService.enabled.is_(True))
                stmt = stmt.where(ClinicalService.id.in_(offered))
            rows = session.execute(stmt.order_by(ClinicalService.code).limit(limit)).scalars().all()
            out = [self._out(session, r) for r in rows]
            if care_setting:
                out = [s for s in out if care_setting in s.care_settings]
            return out

    @staticmethod
    def _change(
        u: Unit,
        kind: str,
        svc: ClinicalService,
        previous: str,
        approval: str | None,
        reason: str | None = None,
    ) -> None:
        u.session.add(
            ServiceChange(
                tenant_id=u.ctx.tenant_id,
                id=new_id(),
                change_type=kind,
                service_id=svc.id,
                requester=u.ctx.principal.subject,
                approver=approval,
                reason=reason or f"{kind} {svc.code}",
                previous_status=previous,
                new_status=svc.status,
                catalogue_version=load_catalogue()["version"],
                recorded_at=u.ctx.now,
                correlation_id=u.ctx.correlation_id,
            )
        )

    @staticmethod
    def _out(session: Session, svc: ClinicalService) -> ServiceOut:
        dept = session.get(OrgUnit, (svc.tenant_id, svc.department_id))
        group = session.get(ServiceTemplateGroup, dept.code) if dept else None
        facilities = (
            session.execute(
                select(FacilityService.facility_id).where(
                    FacilityService.tenant_id == svc.tenant_id,
                    FacilityService.service_id == svc.id,
                    FacilityService.enabled.is_(True),
                )
            )
            .scalars()
            .all()
        )
        return ServiceOut(
            id=svc.id,
            version=svc.version,
            code=svc.code,
            name=svc.name,
            group_code=group.code if group else None,
            group_name=group.name if group else None,
            division=group.division if group else None,
            age_policy=svc.age_policy,
            care_settings=svc.care_settings,
            status=svc.status,
            owner_id=svc.owner_id,
            facilities=list(facilities),
        )


def resolve_service_for_admission(u: Unit, code: str, facility_id: uuid.UUID) -> uuid.UUID | None:
    """CAT-03/CAT-04: link the encounter to an active service offered at the
    facility. Once a tenant has an active catalogue, an unknown code is
    rejected rather than defaulted to a department."""
    tid = u.ctx.tenant_id
    svc = u.session.execute(
        select(ClinicalService).where(
            ClinicalService.tenant_id == tid, ClinicalService.code == code
        )
    ).scalar_one_or_none()
    if svc is None or svc.status != cat.ServiceStatus.ACTIVE:
        # A tenant whose services are all still drafts is bootstrapping. Once any
        # service has been activated (even if since retired) the catalogue is live.
        has_catalogue = u.session.execute(
            select(ClinicalService.id)
            .where(
                ClinicalService.tenant_id == tid,
                ClinicalService.status != cat.ServiceStatus.DRAFT.value,
            )
            .limit(1)
        ).first()
        if has_catalogue is None:
            return None
        code_ = (
            "service_retired" if svc is not None and svc.status == "retired" else "unknown_service"
        )
        raise Unprocessable(f"service {code!r} is not an active service", code=code_)
    offered = u.session.execute(
        select(FacilityService.id).where(
            FacilityService.tenant_id == tid,
            FacilityService.service_id == svc.id,
            FacilityService.facility_id == facility_id,
            FacilityService.enabled.is_(True),
        )
    ).first()
    if offered is None:
        raise Unprocessable(
            "service is not offered at this facility", code="service_not_offered_here"
        )
    return svc.id
