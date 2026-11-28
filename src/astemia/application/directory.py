"""Staff and site directory, and the laboratory's list of orders still waiting
for a result. The directory holds no patient data and is open to every member
of the tenant; the laboratory worklist needs result:release and is audited."""

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import (
    Organisation,
    OrganisationSite,
    Patient,
    Practitioner,
    ServiceRequest,
)
from astemia.application import views
from astemia.application.context import RequestContext
from astemia.application.errors import AccessDenied
from astemia.application.policy import PolicyEngine
from astemia.application.schemas import FacilityOut, LabOrderOut, PractitionerOut
from astemia.application.write_path import audit_row
from astemia.domain.diagnostics import ServiceRequestStatus


class Directory:
    def __init__(self, factory: sessionmaker[Session], policy: PolicyEngine) -> None:
        self.factory = factory
        self.policy = policy

    def practitioners(self, ctx: RequestContext) -> list[PractitionerOut]:
        with self.factory() as session:
            rows = session.execute(
                select(Practitioner)
                .where(
                    Practitioner.tenant_id == ctx.tenant_id,
                    Practitioner.authorisation_status == "active",
                )
                .order_by(Practitioner.display_name, Practitioner.id)
            ).scalars()
            return [PractitionerOut.model_validate(p, from_attributes=True) for p in rows]

    def facilities(self, ctx: RequestContext) -> list[FacilityOut]:
        with self.factory() as session:
            rows = session.execute(
                select(OrganisationSite, Organisation.organisation_name)
                .join(
                    Organisation,
                    (Organisation.tenant_id == OrganisationSite.tenant_id)
                    & (Organisation.id == OrganisationSite.organisation_id),
                )
                .where(OrganisationSite.tenant_id == ctx.tenant_id)
                .order_by(Organisation.organisation_name, OrganisationSite.site_name)
            ).all()
            return [
                FacilityOut(
                    id=site.id,
                    site_identifier=site.site_identifier,
                    site_name=site.site_name,
                    organisation_id=site.organisation_id,
                    organisation_name=name,
                )
                for site, name in rows
            ]

    def lab_worklist(self, ctx: RequestContext, *, limit: int) -> list[LabOrderOut]:
        """Active orders, urgent first and then oldest first."""
        with self.factory() as session:
            decision = self.policy.decide(session, ctx, "result:release")
            session.add(
                audit_row(
                    ctx,
                    decision,
                    "order.worklist",
                    "service_request",
                    None,
                    None,
                    "success" if decision.allowed else "denied",
                )
            )
            session.commit()
            if not decision.allowed:
                raise AccessDenied(decision.reason, code=decision.reason)
            rows = session.execute(
                select(ServiceRequest, Patient)
                .join(
                    Patient,
                    (Patient.tenant_id == ServiceRequest.tenant_id)
                    & (Patient.id == ServiceRequest.patient_id),
                )
                .where(
                    ServiceRequest.tenant_id == ctx.tenant_id,
                    ServiceRequest.status == ServiceRequestStatus.ACTIVE.value,
                )
                .order_by(
                    (ServiceRequest.priority == "routine").asc(),
                    ServiceRequest.recorded_at,
                    ServiceRequest.id,
                )
                .limit(limit)
            ).all()
            return [
                LabOrderOut(
                    order=views.order(o),
                    patient=views.patient(session, p, masks=decision.masks, at=ctx.now),
                    ordered_at=o.recorded_at,
                )
                for o, p in rows
            ]
