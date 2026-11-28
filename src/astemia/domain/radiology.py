"""Radiology and imaging (CEDA HS07, WF05 step 1). Pure rules.

An imaging request is an order with a radiology workflow: requested, then
vetted (or rejected) by a radiologist, scheduled, performed when its study
arrives, and reported. A study joins the order only when its accession number
finds the order and the patient identity it carries agrees with the order's
patient; otherwise it stays off the chart until someone reconciles it.
Addenda are new signed reports that keep the earlier ones.
"""

from datetime import date
from enum import StrEnum

from astemia.domain.common import InvariantViolation, transition


class ImagingState(StrEnum):
    REQUESTED = "requested"
    VETTED = "vetted"
    REJECTED = "rejected"
    SCHEDULED = "scheduled"
    PERFORMED = "performed"
    REPORTED = "reported"


class ImagingModality(StrEnum):
    """DICOM modality codes (PS3.3 C.7.3.1.1.1) in common use."""

    CR = "CR"  # computed radiography
    DX = "DX"  # digital radiography
    CT = "CT"
    MR = "MR"
    US = "US"
    NM = "NM"
    PT = "PT"
    MG = "MG"  # mammography
    XA = "XA"  # angiography
    RF = "RF"  # fluoroscopy


class StudyStatus(StrEnum):
    LINKED = "linked"  # on the chart, with its order
    UNMATCHED = "unmatched"  # no order has that accession number
    IDENTITY_CONFLICT = "identity_conflict"  # the order's patient does not agree


class VetDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


_ALLOWED: dict[ImagingState, frozenset[ImagingState]] = {
    ImagingState.REQUESTED: frozenset({ImagingState.VETTED, ImagingState.REJECTED}),
    ImagingState.VETTED: frozenset({ImagingState.SCHEDULED}),
    ImagingState.SCHEDULED: frozenset({ImagingState.PERFORMED}),
    ImagingState.PERFORMED: frozenset({ImagingState.REPORTED}),
}


def move(current: ImagingState, target: ImagingState) -> ImagingState:
    return transition(current, target, _ALLOWED, "imaging request")


def check_vetting(decision: VetDecision, protocol: str | None, reason: str | None) -> None:
    if decision is VetDecision.ACCEPTED and not protocol:
        raise InvariantViolation("an accepted request needs a protocol", code="protocol_required")
    if decision is VetDecision.REJECTED and not reason:
        raise InvariantViolation("say why the request is rejected", code="reason_required")


def identity_conflicts(
    patient_identifiers: set[tuple[str, str]],
    patient_birth_date: date,
    study_identifier: tuple[str, str],
    study_birth_date: date,
) -> list[str]:
    """Where the study's patient and the order's patient disagree. The study
    must carry one of the patient's active identifiers and the same birth date."""
    conflicts = []
    if study_identifier not in patient_identifiers:
        conflicts.append("identifier")
    if study_birth_date != patient_birth_date:
        conflicts.append("birth_date")
    return conflicts
