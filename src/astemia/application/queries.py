"""Scoped queries. GET /v1/patients/{id}/chart (API-03)."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import (
    DiagnosticReport,
    Encounter,
    MergeLink,
    Patient,
    ResultReview,
    ServiceRequest,
)
from astemia.application import views
from astemia.application.context import RequestContext
from astemia.application.errors import AccessDenied, Conflict
from astemia.application.lineage import merged_family
from astemia.application.policy import Decision, PolicyEngine
from astemia.application.schemas import ChartOut
from astemia.application.write_path import read_path
from astemia.domain.common import Sensitivity
from astemia.domain.diagnostics import ReviewState
from astemia.domain.identity import MergeAction, PatientStatus


class Queries:
    def __init__(self, factory: sessionmaker[Session], policy: PolicyEngine) -> None:
        self.factory = factory
        self.policy = policy

    def chart(self, ctx: RequestContext, patient_id: uuid.UUID) -> ChartOut:
        def read(session: Session, decision: Decision) -> ChartOut:
            tid = ctx.tenant_id
            patient = session.execute(
                select(Patient).where(Patient.tenant_id == tid, Patient.id == patient_id)
            ).scalar_one_or_none()
            if patient is None:  # pragma: no cover - the relationship check implies the patient
                raise AccessDenied("not found", code="not_found", conceal=True)
            if patient.status == PatientStatus.MERGED:
                survivor = session.execute(
                    select(MergeLink.survivor_id).where(
                        MergeLink.tenant_id == tid,
                        MergeLink.prior_id == patient_id,
                        MergeLink.action == MergeAction.MERGE.value,
                    )
                ).scalar_one()
                raise Conflict(
                    "this record was merged; read the surviving record",
                    code="patient_merged",
                    details={"survivor_id": str(survivor)},
                )
            family = merged_family(session, tid, patient_id)
            masks = decision.masks
            withheld = 0

            def visible(sensitivity: str) -> bool:
                nonlocal withheld
                if sensitivity == Sensitivity.NORMAL or f"sensitivity:{sensitivity}" not in masks:
                    return True
                withheld += 1
                return False

            encounters = [
                e
                for e in session.execute(
                    select(Encounter)
                    .where(Encounter.tenant_id == tid, Encounter.patient_id.in_(family))
                    .order_by(Encounter.period_start.desc())
                ).scalars()
                if visible(e.sensitivity)
            ]
            orders = [
                o
                for o in session.execute(
                    select(ServiceRequest)
                    .where(ServiceRequest.tenant_id == tid, ServiceRequest.patient_id.in_(family))
                    .order_by(ServiceRequest.recorded_at.desc())
                ).scalars()
                if visible(o.sensitivity)
            ]
            reports = [
                r
                for r in session.execute(
                    select(DiagnosticReport)
                    .where(
                        DiagnosticReport.tenant_id == tid, DiagnosticReport.patient_id.in_(family)
                    )
                    .order_by(DiagnosticReport.released_at.desc())
                ).scalars()
                if visible(r.sensitivity)
            ]
            reviews = session.execute(
                select(ResultReview).where(
                    ResultReview.tenant_id == tid,
                    ResultReview.patient_id.in_(family),
                    ResultReview.state.in_([ReviewState.OPEN.value, ReviewState.ESCALATED.value]),
                )
            ).scalars()
            return ChartOut(
                patient=views.patient(session, patient, masks=masks, at=ctx.now),
                encounters=[views.encounter(session, e) for e in encounters],
                orders=[views.order(o) for o in orders],
                reports=[views.report(session, r, masks=masks) for r in reports],
                open_reviews=[views.review(r) for r in reviews if visible(r.sensitivity)],
                masked_fields=sorted(m for m in masks if not m.startswith("sensitivity:")),
                withheld_records=withheld,
                merged_records=family[1:],
            )

        return read_path(
            self.factory,
            self.policy,
            ctx,
            capability="chart:read",
            action="chart.read",
            resource_type="patient",
            patient_id=patient_id,
            reader=read,
        )
