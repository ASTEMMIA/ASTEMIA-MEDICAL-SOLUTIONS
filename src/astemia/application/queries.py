"""Scoped queries. GET /v1/patients/{id}/chart (API-03)."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import (
    DiagnosticReport,
    Encounter,
    Patient,
    ResultReview,
    ServiceRequest,
)
from astemia.application import views
from astemia.application.context import RequestContext
from astemia.application.errors import AccessDenied
from astemia.application.policy import Decision, PolicyEngine
from astemia.application.schemas import ChartOut
from astemia.application.write_path import read_path
from astemia.domain.common import Sensitivity
from astemia.domain.diagnostics import ReviewState


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
            masks = decision.masks
            withheld = 0
            # ICRS 3.2.12: the survivor's chart includes records merged into it.
            merged = views.merged_from(session, tid, patient_id)
            ids = [patient_id, *merged]

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
                    .where(Encounter.tenant_id == tid, Encounter.patient_id.in_(ids))
                    .order_by(Encounter.period_start.desc())
                ).scalars()
                if visible(e.sensitivity)
            ]
            orders = [
                o
                for o in session.execute(
                    select(ServiceRequest)
                    .where(ServiceRequest.tenant_id == tid, ServiceRequest.patient_id.in_(ids))
                    .order_by(ServiceRequest.recorded_at.desc())
                ).scalars()
                if visible(o.sensitivity)
            ]
            reports = [
                r
                for r in session.execute(
                    select(DiagnosticReport)
                    .where(DiagnosticReport.tenant_id == tid, DiagnosticReport.patient_id.in_(ids))
                    .order_by(DiagnosticReport.released_at.desc())
                ).scalars()
                if visible(r.sensitivity)
            ]
            reviews = session.execute(
                select(ResultReview).where(
                    ResultReview.tenant_id == tid,
                    ResultReview.patient_id.in_(ids),
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
                merged_from=merged,
                legal_status=(
                    views.legal_status(legal, ctx.now)
                    if (legal := views.current_legal_status(session, tid, patient_id))
                    else None
                ),
                access_basis=(
                    "emergency_grant"
                    if decision.reason == "emergency_grant"
                    else "care_relationship"
                ),
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
