"""Read models: canonical rows to API resources, applying policy masks."""

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from astemia.adapters.db.models import (
    AeAttendance,
    DiagnosticReport,
    DuplicateCandidate,
    Encounter,
    MergeLink,
    Observation,
    ObservationRevision,
    Patient,
    PatientIdentifier,
    PersonName,
    ResultReview,
    ServiceRequest,
)
from astemia.application.schemas import (
    AeAttendanceOut,
    CandidateOut,
    EncounterOut,
    IdentifierOut,
    MergeOut,
    NameOut,
    ObservationOut,
    OrderOut,
    PatientOut,
    ReportOut,
    ReviewOut,
    ReviewTaskOut,
)
from astemia.domain import identity as idn


def _mask(value: str) -> str:
    return "*" * max(len(value) - 4, 0) + value[-4:]


def current_names(session: Session, patient: Patient, at: datetime) -> list[PersonName]:
    return list(
        session.execute(
            select(PersonName)
            .where(
                PersonName.tenant_id == patient.tenant_id,
                PersonName.party_id == patient.id,
                PersonName.effective_from <= at,
                or_(PersonName.effective_to.is_(None), PersonName.effective_to > at),
            )
            .order_by(PersonName.name_type, PersonName.name_number)
        ).scalars()
    )


def patient(session: Session, row: Patient, *, masks: frozenset[str], at: datetime) -> PatientOut:
    identifiers = session.execute(
        select(PatientIdentifier).where(
            PatientIdentifier.tenant_id == row.tenant_id,
            PatientIdentifier.patient_id == row.id,
            PatientIdentifier.active_marker == 1,
        )
    ).scalars()
    names = current_names(session, row, at)
    usual = next((n for n in names if n.name_type == "usual"), names[0] if names else None)
    return PatientOut(
        id=row.id,
        version=row.version,
        family_name=usual.family_name if usual else "",
        given_names=" ".join(p for p in (usual.given_name, usual.other_given_name) if p)
        if usual
        else "",
        names=[
            NameOut(
                name_type=n.name_type,
                title=n.title,
                family_name=n.family_name,
                given_name=n.given_name,
                other_given_name=n.other_given_name,
                suffix=n.suffix,
            )
            for n in names
        ],
        birth_date=row.birth_date,
        birth_date_precision=row.birth_date_precision,
        administrative_sex=row.administrative_sex,
        status=row.status,
        identifiers=[
            IdentifierOut(
                issuer=i.issuer,
                value=_mask(i.value) if "identifier.value" in masks else i.value,
                identifier_type=i.identifier_type,
                verification_status=i.verification_status,
            )
            for i in identifiers
        ],
    )


def encounter(session: Session, row: Encounter) -> EncounterOut:
    out = EncounterOut.model_validate(row, from_attributes=True)
    ae = session.execute(
        select(AeAttendance).where(
            AeAttendance.tenant_id == row.tenant_id, AeAttendance.encounter_id == row.id
        )
    ).scalar_one_or_none()
    if ae is not None:
        out.ae = AeAttendanceOut.model_validate(ae, from_attributes=True)
    return out


def order(row: ServiceRequest) -> OrderOut:
    return OrderOut.model_validate(row, from_attributes=True)


def review(row: ResultReview) -> ReviewOut:
    return ReviewOut.model_validate(row, from_attributes=True)


def report(session: Session, row: DiagnosticReport, *, masks: frozenset[str]) -> ReportOut:
    rows = session.execute(
        select(Observation, ObservationRevision)
        .join(
            ObservationRevision,
            (ObservationRevision.tenant_id == Observation.tenant_id)
            & (ObservationRevision.observation_id == Observation.id),
        )
        .where(Observation.tenant_id == row.tenant_id, ObservationRevision.report_id == row.id)
        .order_by(Observation.code_system, Observation.code)
    ).all()
    out = ReportOut.model_validate(row, from_attributes=True)
    out.observations = [
        ObservationOut(
            observation_id=o.id,
            revision_id=r.id,
            revision=r.revision,
            code_system=o.code_system,
            code=o.code,
            display=o.display,
            status=r.status,
            value_type=r.value_type,
            quantity=r.value_quantity,
            unit=r.value_unit,
            text=r.value_text,
            value_code=r.value_code,
            ref_low=r.ref_low,
            ref_high=r.ref_high,
            flag=r.flag,
        )
        for o, r in rows
    ]
    return out


# --- identity stewardship ---------------------------------------------------------


def candidate(
    session: Session,
    row: Patient,
    score: int,
    reasons: tuple[str, ...] | list[str],
    *,
    masks: frozenset[str],
    at: datetime,
) -> CandidateOut:
    """Enough to tell two people apart, and no more (WF01 step 1)."""
    full = patient(session, row, masks=masks, at=at)
    band = idn.MatchScore(score, ()).band
    return CandidateOut(
        id=row.id,
        status=row.status,
        score=score,
        band=band.value if band else None,
        reasons=list(reasons),
        family_name=full.family_name,
        given_initial=full.given_names[:1],
        birth_year=row.birth_date.year,
        administrative_sex=row.administrative_sex,
        identifiers=full.identifiers,
    )


def review_task(
    session: Session, row: DuplicateCandidate, *, masks: frozenset[str], at: datetime
) -> ReviewTaskOut:
    score = int(row.weighting)
    reasons = row.reasons or []
    records = [
        candidate(session, p, score, reasons, masks=masks, at=at)
        for p in session.execute(
            select(Patient)
            .where(
                Patient.tenant_id == row.tenant_id,
                Patient.id.in_([row.record1_id, row.record2_id]),
            )
            .order_by(Patient.id)
        ).scalars()
    ]
    return ReviewTaskOut(
        id=row.id,
        version=row.version,
        score=score,
        reasons=reasons,
        origin=row.origin,
        note=row.note,
        resolved=row.resolved,
        resolution=row.resolution,
        resolved_at=row.resolved_at,
        resolved_by_id=row.resolved_by_id,
        records=records,
    )


def merge_link(
    session: Session, row: MergeLink, *, masks: frozenset[str], at: datetime
) -> MergeOut:
    def load(pid: object) -> Patient:
        return session.execute(
            select(Patient).where(Patient.tenant_id == row.tenant_id, Patient.id == pid)
        ).scalar_one()

    return MergeOut(
        id=row.id,
        version=row.version,
        prior_id=row.prior_id,
        survivor_id=row.survivor_id,
        action=row.action,
        reviewer_id=row.reviewer_id,
        reason=row.reason,
        reversible=row.reversible,
        reconciliation_status=row.reconciliation_status,
        recorded_at=row.recorded_at,
        prior=patient(session, load(row.prior_id), masks=masks, at=at),
        survivor=patient(session, load(row.survivor_id), masks=masks, at=at),
    )
