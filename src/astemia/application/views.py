"""Read models: canonical rows to API resources, applying policy masks."""

import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from astemia.adapters.db.models import (
    AeAttendance,
    DiagnosticReport,
    DuplicateCandidate,
    Encounter,
    MentalHealthLegalStatus,
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
    LegalStatusOut,
    NameOut,
    ObservationOut,
    OrderOut,
    PatientOut,
    ReportOut,
    ReviewOut,
    ReviewTaskOut,
)
from astemia.domain import identity as idn
from astemia.domain import safeguards as sg


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


# A merge link in force: a merge that has not been reversed by an unmerge.
MERGE, UNMERGE, REVERSED = "merge", "unmerge", "reversed"


def merged_into(session: Session, row: Patient) -> uuid.UUID | None:
    return session.execute(
        select(MergeLink.survivor_id)
        .where(
            MergeLink.tenant_id == row.tenant_id,
            MergeLink.prior_id == row.id,
            MergeLink.action == MERGE,
            MergeLink.reconciliation_status != REVERSED,
        )
        .order_by(MergeLink.recorded_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def merged_from(session: Session, tenant_id: uuid.UUID, survivor_id: uuid.UUID) -> list[uuid.UUID]:
    """Every record merged into the survivor, directly or through a chain."""
    found: list[uuid.UUID] = []
    frontier = [survivor_id]
    while frontier:
        priors = list(
            session.execute(
                select(MergeLink.prior_id).where(
                    MergeLink.tenant_id == tenant_id,
                    MergeLink.survivor_id.in_(frontier),
                    MergeLink.action == MERGE,
                    MergeLink.reconciliation_status != REVERSED,
                )
            ).scalars()
        )
        frontier = [p for p in priors if p not in found and p != survivor_id]
        found += frontier
    return found


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
        date_of_exit=row.date_of_exit,
        merged_into=merged_into(session, row),
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


# --- identity review --------------------------------------------------------------


def candidate(
    session: Session,
    row: Patient,
    match: idn.MatchScore,
    *,
    masks: frozenset[str],
    at: datetime,
) -> CandidateOut:
    """Enough to tell two people apart, and no more (WF01 step 1)."""
    full = patient(session, row, masks=masks, at=at)
    return CandidateOut(
        id=row.id,
        version=row.version,
        status=row.status,
        score=match.score,
        band=match.band.value if match.band else None,
        reasons=list(match.reasons),
        family_name=full.family_name,
        given_initial=full.given_names[:1],
        birth_year=row.birth_date.year,
        administrative_sex=row.administrative_sex,
        identifiers=full.identifiers,
    )


def review_task(
    session: Session, row: DuplicateCandidate, *, masks: frozenset[str], at: datetime
) -> ReviewTaskOut:
    match = idn.MatchScore(int(row.weighting), tuple(row.reasons or ()))
    records = session.execute(
        select(Patient)
        .where(
            Patient.tenant_id == row.tenant_id,
            Patient.id.in_([row.record1_id, row.record2_id]),
        )
        .order_by(Patient.id)
    ).scalars()
    return ReviewTaskOut(
        id=row.id,
        version=row.version,
        score=match.score,
        reasons=list(match.reasons),
        origin=row.origin,
        note=row.note,
        resolved=row.resolved,
        resolution=row.resolution,
        resolved_at=row.resolved_at,
        resolved_by_id=row.resolved_by_id,
        records=[candidate(session, p, match, masks=masks, at=at) for p in records],
    )


# --- mental health legal status (ICRS 5.5.9, 5.5.15) --------------------------------


def legal_status(row: MentalHealthLegalStatus, at: datetime) -> LegalStatusOut:
    status = sg.LegalStatus(row.status)
    current = row.current_marker == 1
    return LegalStatusOut(
        id=row.id,
        version=row.version,
        patient_id=row.patient_id,
        status=row.status,
        legal_basis=row.legal_basis,
        valid_from=row.valid_from,
        valid_until=row.valid_until,
        authorised_by_id=row.authorised_by_id,
        reason=row.reason,
        ended_at=row.ended_at,
        current=current,
        lapsed=current and sg.lapsed(status, row.valid_until, at),
        expiring=current and sg.expiring(row.valid_until, at),
    )


def current_legal_status(
    session: Session, tenant_id: uuid.UUID, patient_id: uuid.UUID
) -> MentalHealthLegalStatus | None:
    return session.execute(
        select(MentalHealthLegalStatus).where(
            MentalHealthLegalStatus.tenant_id == tenant_id,
            MentalHealthLegalStatus.patient_id == patient_id,
            MentalHealthLegalStatus.current_marker == 1,
        )
    ).scalar_one_or_none()
