"""Command inputs and resource outputs (Pydantic for every input and output)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from astemia.domain.beds import BedStatus, EndReason
from astemia.domain.careplans import Certainty, Pathway, SessionType
from astemia.domain.common import EffectivePrecision, Sensitivity
from astemia.domain.diagnostics import OrderPriority, ReportStatus, ValueType
from astemia.domain.discharge import Disposition, OutstandingKind
from astemia.domain.encounter import EncounterClass
from astemia.domain.identity import AddressChangeReason, AdministrativeSex, ClosureReason
from astemia.domain.notes import NoteType
from astemia.domain.radiology import ImagingModality, ImagingState, StudyStatus, VetDecision
from astemia.domain.safeguards import (
    ConcernCategory,
    InterventionType,
    LegalStatus,
    RaisedBy,
    ReviewOutcome,
)
from astemia.domain.scheduling import (
    AttendanceOutcome,
    Modality,
    ReferralPriority,
    SlotType,
)
from astemia.domain.tasks import Priority as TaskPriority
from astemia.domain.tasks import TaskType
from astemia.domain.theatre import CaseStatus, ChecklistStep, Laterality, SessionStatus

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Code = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- inputs -------------------------------------------------------------------


class IdentifierIn(Strict):
    issuer: Code
    value: Code
    identifier_type: str = Field(
        default="current", pattern="^(current|temporary|old_style|previous)$"
    )
    verified: bool = False


AddressLine = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class AddressIn(Strict):
    """A full postal address (ERD ADDRESS). Lines 1 and town are required; a
    Nigerian address also needs its state and local government area."""

    line1: AddressLine = Field(description="House number or name and street.")
    line2: AddressLine | None = Field(default=None, description="Area or estate.")
    town: AddressLine = Field(description="Town or city.")
    local_government_area: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)] | None
    ) = None
    state: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)] | None
    ) = None
    postcode: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=16)]
    country: str = Field(default="NG", pattern="^[A-Z]{2}$", description="ISO 3166-1 alpha-2.")


class RegisterPatient(Strict):
    title: str | None = Field(default=None, max_length=32)
    family_name: Name
    given_names: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    mother_name: str | None = Field(default=None, max_length=200)
    father_name: str | None = Field(default=None, max_length=200)
    preferred_language: str | None = Field(default=None, max_length=8)
    state_of_origin: str | None = Field(default=None, max_length=64)
    birth_date: date
    birth_date_precision: EffectivePrecision = EffectivePrecision.DAY
    administrative_sex: AdministrativeSex
    temporary: bool = False
    identifiers: list[IdentifierIn] = Field(default_factory=list, max_length=10)
    address: AddressIn | None = Field(
        default=None,
        description="Required: full address with postcode. Only a temporary "
        "(unidentified) registration may leave it out.",
    )


class AeAttendanceIn(Strict):
    """A&E detail for an emergency admission (ERD AE_TRANSACTION)."""

    attendance_number: Code
    arrival_mode: Code
    attendance_category: Code
    patient_group: Code | None = None
    referral_source: Code | None = None
    incident_location_type: Code | None = None
    initial_assessment_at: AwareDatetime | None = None


class AdmitEncounter(Strict):
    patient_id: uuid.UUID
    facility_id: uuid.UUID
    responsible_practitioner_id: uuid.UUID
    visit_authority: Code
    visit_number: Code
    encounter_class: EncounterClass = EncounterClass.INPATIENT
    service: Code
    admission_route: Code | None = None
    admitted_at: AwareDatetime
    sensitivity: Sensitivity = Sensitivity.NORMAL
    ae: AeAttendanceIn | None = None


class PlaceOrder(Strict):
    patient_id: uuid.UUID
    encounter_id: uuid.UUID
    code_system: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    code: Code
    display: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    original_system: str | None = Field(default=None, max_length=128)
    original_code: str | None = Field(default=None, max_length=64)
    priority: OrderPriority = OrderPriority.ROUTINE
    result_owner_id: uuid.UUID | None = None
    backup_owner_id: uuid.UUID | None = None
    clinical_note: str | None = Field(default=None, max_length=1000)


class ObservationIn(Strict):
    code_system: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    code: Code
    display: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    value_type: ValueType
    quantity: Decimal | None = Field(default=None, max_digits=18, decimal_places=6)
    unit: str | None = Field(default=None, max_length=32)
    text: str | None = Field(default=None, max_length=2000)
    value_code: str | None = Field(default=None, max_length=64)
    ref_low: Decimal | None = Field(default=None, max_digits=18, decimal_places=6)
    ref_high: Decimal | None = Field(default=None, max_digits=18, decimal_places=6)
    original_value: str | None = Field(default=None, max_length=255)


class ReleaseReport(Strict):
    service_request_id: uuid.UUID
    status: ReportStatus = ReportStatus.FINAL
    filler_authority: Code | None = None
    filler_id: Code | None = None
    effective_at: AwareDatetime
    conclusion: str | None = Field(default=None, max_length=2000)
    observations: list[ObservationIn] = Field(min_length=1, max_length=200)


class Acknowledge(Strict):
    note: str | None = Field(default=None, max_length=1000)


Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)]


class MergePatient(Strict):
    """Merge this (prior) record into the survivor (ICRS 3.2.12, 3.2.33)."""

    survivor_id: uuid.UUID
    reason: Reason


class UnmergePatient(Strict):
    reason: Reason


class ClosePatient(Strict):
    """Close a record in the index (ICRS 3.2.18-3.2.19)."""

    reason: ClosureReason
    exit_date: date


class ClosureItem(ClosePatient):
    patient_id: uuid.UUID


class CloseBatch(Strict):
    """A batch of closures, for example a list of death registrations (ICRS 3.2.20)."""

    items: list[ClosureItem] = Field(min_length=1, max_length=500)


# --- outputs ------------------------------------------------------------------


class Resource(BaseModel):
    id: uuid.UUID
    version: int


class IdentifierOut(BaseModel):
    issuer: str
    value: str
    identifier_type: str
    verification_status: str


class NameOut(BaseModel):
    name_type: str
    title: str | None = None
    family_name: str
    given_name: str
    other_given_name: str | None = None
    suffix: str | None = None


class AddressOut(BaseModel):
    line1: str
    line2: str | None
    town: str
    local_government_area: str | None
    state: str | None
    postcode: str | None
    country: str


class AddressHistoryOut(AddressOut):
    address_type: str
    effective_from: datetime
    effective_to: datetime | None
    current: bool
    recorded_by_id: uuid.UUID | None


class ChangeAddress(Strict):
    """A new home address. The current one is ended and kept as history."""

    address: AddressIn
    reason: AddressChangeReason = Field(
        description="moved, correction, or identified (a temporary patient now known)."
    )


class PatientOut(Resource):
    family_name: str
    given_names: str
    birth_date: date
    birth_date_precision: str
    administrative_sex: str
    status: str
    names: list[NameOut] = []
    identifiers: list[IdentifierOut] = []
    date_of_exit: date | None = None
    merged_into: uuid.UUID | None = None
    address: AddressOut | None = Field(
        default=None,
        description="Current home address; null when none is recorded or the "
        "reader's role may not see it (then 'address' is in masked_fields).",
    )


class AeAttendanceOut(BaseModel):
    attendance_number: str
    arrival_mode: str
    attendance_category: str
    patient_group: str | None = None
    referral_source: str | None = None
    incident_location_type: str | None = None
    arrival_at: datetime
    initial_assessment_at: datetime | None = None
    seen_for_treatment_at: datetime | None = None
    conclusion_at: datetime | None = None
    departure_at: datetime | None = None
    attendance_disposal: str | None = None


class EncounterOut(Resource):
    patient_id: uuid.UUID
    facility_id: uuid.UUID
    responsible_practitioner_id: uuid.UUID
    visit_authority: str
    visit_number: str
    encounter_class: str
    service: str
    state: str
    period_start: datetime
    period_end: datetime | None = None
    clinical_service_id: uuid.UUID | None = None
    ae: AeAttendanceOut | None = None
    disposition: str | None = None


class OrderOut(Resource):
    patient_id: uuid.UUID
    encounter_id: uuid.UUID
    placer_authority: str
    placer_id: str
    code_system: str
    code: str
    display: str
    status: str
    priority: str
    requester_id: uuid.UUID
    result_owner_id: uuid.UUID


class ObservationOut(BaseModel):
    observation_id: uuid.UUID
    revision_id: uuid.UUID
    revision: int
    code_system: str
    code: str
    display: str
    status: str
    value_type: str
    quantity: Decimal | None = None
    unit: str | None = None
    text: str | None = None
    value_code: str | None = None
    ref_low: Decimal | None = None
    ref_high: Decimal | None = None
    flag: str | None = None


class ReportOut(Resource):
    service_request_id: uuid.UUID
    patient_id: uuid.UUID
    status: str
    released_at: datetime
    prior_report_id: uuid.UUID | None = None
    review_id: uuid.UUID | None = None
    conclusion: str | None = None
    presented_form: str | None = None  # the signed text of a narrative report
    observations: list[ObservationOut] = []


class ReviewOut(Resource):
    report_id: uuid.UUID
    patient_id: uuid.UUID
    assignee_id: uuid.UUID
    state: str
    acknowledged_at: datetime | None = None


class ChartOut(BaseModel):
    patient: PatientOut
    encounters: list[EncounterOut]
    orders: list[OrderOut]
    reports: list[ReportOut]
    open_reviews: list[ReviewOut]
    masked_fields: list[str]
    withheld_records: int
    merged_from: list[uuid.UUID] = []
    access_basis: str = Field(
        default="care_relationship",
        description="care_relationship, or emergency_grant for time-boxed emergency access",
    )
    legal_status: LegalStatusOut | None = Field(
        default=None, description="Mental health legal status in force (ICRS 5.5.15)."
    )
    entries: list[EntrySummary] = Field(
        default_factory=list, description="Signed clinical notes, newest first."
    )
    documents: list[DocumentSummary] = Field(
        default_factory=list, description="Filed correspondence, newest first."
    )
    discharges: list[DischargeSummaryOut] = Field(
        default_factory=list, description="Signed discharge summaries, newest first."
    )
    conditions: list[ConditionOut] = Field(
        default_factory=list, description="The problem list, refuted conditions excluded."
    )
    care_plans: list[CarePlanSummary] = Field(default_factory=list)


class PractitionerOut(BaseModel):
    """A member of staff as others see them: for names on records and pickers."""

    id: uuid.UUID
    display_name: str
    professional_register: str | None
    specialist_area: str | None


class FacilityOut(BaseModel):
    """A site where care happens (CEDA facility)."""

    id: uuid.UUID
    site_identifier: str
    site_name: str
    organisation_id: uuid.UUID
    organisation_name: str


class LabOrderOut(BaseModel):
    """An order still waiting for its result, with the patient it is for."""

    order: OrderOut
    patient: PatientOut
    ordered_at: datetime


class DuplicateGroup(BaseModel):
    """Open index records that share family name, date of birth and sex."""

    family_name: str
    birth_date: date
    administrative_sex: str
    patient_ids: list[uuid.UUID]


# --- service catalogue (Annex A16) ---------------------------------------------


class ProvisionCatalogue(Strict):
    facility_id: uuid.UUID
    group_codes: list[Annotated[str, StringConstraints(pattern=r"^D\d{2}$")]] | None = Field(
        default=None, description="Department groups to provision; all when omitted."
    )


class ActivateService(Strict):
    facility_id: uuid.UUID
    owner_id: uuid.UUID
    approval_reference: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=100)
    ]
    queue_roles: list[str] = Field(
        default_factory=lambda: ["clinician"], min_length=1, max_length=10
    )


class RetireService(Strict):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class ServiceOut(BaseModel):
    id: uuid.UUID
    version: int
    code: str
    name: str
    group_code: str | None
    group_name: str | None
    division: str | None
    age_policy: str
    care_settings: list[str]
    status: str
    owner_id: uuid.UUID | None = None
    facilities: list[uuid.UUID] = []


class ProvisionOut(BaseModel):
    facility_id: uuid.UUID
    groups: int
    services_created: int
    services_existing: int


# --- identity review (UG02, WF01 steps 1 and 4) ------------------------------------


class MatchQuery(Strict):
    """Search before registering. Demographics travel in the body, never in a URL."""

    family_name: Name
    given_names: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    birth_date: date
    birth_date_precision: EffectivePrecision = EffectivePrecision.DAY
    administrative_sex: AdministrativeSex
    mother_name: str | None = Field(default=None, max_length=200)
    identifiers: list[IdentifierIn] = Field(default_factory=list, max_length=10)


class CandidateOut(BaseModel):
    """A possible duplicate, with only enough shown to tell people apart."""

    id: uuid.UUID
    version: int = Field(description="For If-Match when this record is merged.")
    status: str
    score: int
    band: str | None
    reasons: list[str]
    family_name: str
    given_initial: str
    birth_year: int
    administrative_sex: str
    identifiers: list[IdentifierOut]


class MatchOut(BaseModel):
    candidates: list[CandidateOut]


class ResolveReview(Strict):
    resolution: Literal["distinct"] = Field(
        description="A merge (POST /v1/patients/{id}/merge) resolves the task itself."
    )
    reason: Reason


class ReviewTaskOut(BaseModel):
    id: uuid.UUID
    version: int
    score: int
    reasons: list[str]
    origin: str | None
    note: str | None
    resolved: bool
    resolution: str | None
    resolved_at: datetime | None
    resolved_by_id: uuid.UUID | None
    records: list[CandidateOut]


# --- emergency access (SEC-04, WF02 step 4) -----------------------------------------


class RequestEmergencyAccess(Strict):
    patient_id: uuid.UUID
    purpose: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=10, max_length=500)
    ] = Field(description="Why the chart is needed now; read by the privacy reviewer.")


class ReviewEmergencyAccess(Strict):
    outcome: Literal["appropriate", "inappropriate"]
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class EmergencyGrantOut(BaseModel):
    id: uuid.UUID
    version: int
    patient_id: uuid.UUID
    practitioner_id: uuid.UUID
    purpose: str
    scope: str
    starts_at: datetime
    expires_at: datetime
    live: bool
    step_up: str
    review_due_at: datetime
    review_overdue: bool
    reviewed_at: datetime | None
    reviewed_by_id: uuid.UUID | None
    review_outcome: str | None
    review_note: str | None


# --- scheduling and referral (UG01, HS04, HS05) -------------------------------------


class CreateSlots(Strict):
    """A run of consecutive slots for one clinician, service and site."""

    facility_id: uuid.UUID
    practitioner_id: uuid.UUID
    service: Code
    starts_at: AwareDatetime
    minutes: int = Field(default=15, description="Length of each slot, 5 to 240.")
    count: int = Field(default=1, description="How many consecutive slots, 1 to 50.")
    slot_type: SlotType = SlotType.NEW
    modality: Modality = Modality.IN_PERSON
    timezone: Annotated[str, StringConstraints(min_length=1, max_length=64)] = "Africa/Lagos"


class SlotOut(BaseModel):
    id: uuid.UUID
    facility_id: uuid.UUID
    practitioner_id: uuid.UUID
    service: str
    slot_type: str
    modality: str
    starts_at: datetime
    ends_at: datetime
    timezone: str
    status: str


class HoldOut(BaseModel):
    id: uuid.UUID = Field(description="The hold token: confirm the booking with it.")
    slot_id: uuid.UUID
    expires_at: datetime


class BookAppointment(Strict):
    hold_id: uuid.UUID
    patient_id: uuid.UUID
    referral_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=500)


class RescheduleAppointment(Strict):
    hold_id: uuid.UUID = Field(description="A live hold on the new slot.")


class CancelAppointment(Strict):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class RecordAttendance(Strict):
    outcome: AttendanceOutcome
    identity_verified: bool = Field(
        default=False,
        description="Required for a video or phone consultation that took place (UG02).",
    )


class AppointmentOut(BaseModel):
    id: uuid.UUID
    version: int
    patient_id: uuid.UUID
    slot_id: uuid.UUID
    status: str
    facility_id: uuid.UUID
    practitioner_id: uuid.UUID
    service: str
    modality: str
    starts_at: datetime
    ends_at: datetime
    reason: str | None
    cancel_reason: str | None
    referral_id: uuid.UUID | None
    rescheduled_from_id: uuid.UUID | None
    encounter_id: uuid.UUID | None


class ClinicAppointmentOut(BaseModel):
    """An appointment on a clinic list, with the patient it is for."""

    appointment: AppointmentOut
    patient: PatientOut


class SubmitReferral(Strict):
    patient_id: uuid.UUID
    referring_facility_id: uuid.UUID
    receiving_facility_id: uuid.UUID = Field(
        description="The general, teaching or specialist hospital (or other facility) "
        "the patient is referred to. The patient's historical records always go with it."
    )
    encounter_id: uuid.UUID | None = Field(
        default=None,
        description="The care episode whose records go with the referral; defaults to "
        "the patient's most recent one. A patient with no care records is refused.",
    )
    receiving_service: Code
    requesting_service: Code | None = None
    priority: ReferralPriority = ReferralPriority.ROUTINE
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]


class DecideReferral(Strict):
    decision: Literal["accepted", "rejected"]
    reason: str | None = Field(default=None, max_length=500)


class ReferralOut(BaseModel):
    id: uuid.UUID
    version: int
    patient_id: uuid.UUID
    referrer_id: uuid.UUID
    source_encounter_id: uuid.UUID
    requesting_service: str | None
    receiving_service: str
    priority: str
    reason: str
    status: str
    decided_by_id: uuid.UUID | None
    decided_at: datetime | None
    decision_reason: str | None
    recorded_at: datetime
    referring_facility_id: uuid.UUID | None
    receiving_facility_id: uuid.UUID | None
    referring_level: str | None
    receiving_level: str | None
    records_count: int | None


class ReferralRecordsOut(BaseModel):
    """The patient's historical records that travel with a referral, as the
    receiving team may see them: masked and with sensitive records withheld."""

    referral: ReferralOut
    patient: PatientOut
    encounters: list[EncounterOut]
    orders: list[OrderOut]
    reports: list[ReportOut]
    masked_fields: list[str]
    withheld_records: int


# --- mental health safeguards (HS13, B11; ICRS 5.5.9) ---------------------------------

LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=1000)]


class RecordIntervention(Strict):
    patient_id: uuid.UUID
    encounter_id: uuid.UUID | None = None
    intervention_type: InterventionType
    reason: LongText = Field(description="Why less restrictive options were not enough.")
    authorised_by_id: uuid.UUID
    staff_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    injury: bool = False
    injury_detail: str | None = Field(default=None, max_length=500)
    debrief_offered: bool | None = None


class EndIntervention(Strict):
    ended_at: AwareDatetime
    debrief_offered: bool
    injury: bool = False
    injury_detail: str | None = Field(default=None, max_length=500)


class ReviewIntervention(Strict):
    outcome: ReviewOutcome
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]


class InterventionOut(BaseModel):
    id: uuid.UUID
    version: int
    patient_id: uuid.UUID
    encounter_id: uuid.UUID | None
    intervention_type: str
    reason: str
    authorised_by_id: uuid.UUID
    recorded_by_id: uuid.UUID | None
    staff_ids: list[uuid.UUID]
    started_at: datetime
    ended_at: datetime | None
    duration_minutes: int | None
    injury: bool
    injury_detail: str | None
    debrief_offered: bool | None
    legal_status_id: uuid.UUID | None
    flags: list[str]
    review_due_at: datetime
    review_overdue: bool
    reviewed_at: datetime | None
    reviewed_by_id: uuid.UUID | None
    review_outcome: str | None
    review_note: str | None


class SetLegalStatus(Strict):
    status: LegalStatus
    legal_basis: str | None = Field(
        default=None, max_length=100, description="The law and power, required when detained."
    )
    valid_from: AwareDatetime
    valid_until: AwareDatetime | None = None
    authorised_by_id: uuid.UUID
    reason: LongText


class LegalStatusOut(BaseModel):
    id: uuid.UUID
    version: int
    patient_id: uuid.UUID
    status: str
    legal_basis: str | None
    valid_from: datetime
    valid_until: datetime | None
    authorised_by_id: uuid.UUID
    reason: str | None = Field(
        description="Withheld (null) from readers without the mental health grant."
    )
    ended_at: datetime | None
    current: bool
    lapsed: bool
    expiring: bool


class RaiseConcern(Strict):
    patient_id: uuid.UUID
    raised_by: RaisedBy
    raised_by_name: str | None = Field(default=None, max_length=200)
    category: ConcernCategory
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=10, max_length=2000)
    ]
    about_practitioner_id: uuid.UUID | None = Field(
        default=None, description="The member of staff the concern is about, if any."
    )


class CloseConcern(Strict):
    outcome: Literal["upheld", "not_upheld"]
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]


class ConcernOut(BaseModel):
    id: uuid.UUID
    version: int
    patient_id: uuid.UUID
    raised_by: str
    raised_by_name: str | None
    recorded_by: str | None
    category: str
    description: str
    about_practitioner_id: uuid.UUID | None
    status: str
    respond_by: datetime
    overdue: bool
    closed_at: datetime | None
    closed_by_id: uuid.UUID | None
    outcome_note: str | None
    recorded_at: datetime


class AppointAdvocate(Strict):
    practitioner_id: uuid.UUID


class AccessEntry(BaseModel):
    occurred_at: datetime
    actor_subject: str
    actor_practitioner_id: uuid.UUID | None
    action: str
    outcome: str
    reason_code: str | None
    flags: list[str]


class ActorSummary(BaseModel):
    actor_subject: str
    entries: int
    flagged: int


class AccessReportOut(BaseModel):
    patient_id: uuid.UUID
    start: datetime
    end: datetime
    entries: list[AccessEntry]
    by_actor: list[ActorSummary]
    flagged: int


# --- clinical notes (SA-07; UG02, WF01 step 3) -----------------------------------------

NoteBody = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]


class CreateEntry(Strict):
    note_type: NoteType
    title: str | None = Field(default=None, max_length=200)
    body: NoteBody
    sensitivity: Sensitivity = Sensitivity.NORMAL


class UpdateDraft(Strict):
    body: NoteBody


class AmendEntry(Strict):
    body: NoteBody
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class RevisionOut(BaseModel):
    id: uuid.UUID
    revision_number: int
    status: str
    body: str
    author_id: uuid.UUID | None
    recorded_at: datetime
    signed_at: datetime | None
    signed_by_id: uuid.UUID | None
    supersedes_id: uuid.UUID | None
    amendment_reason: str | None


class EntryOut(BaseModel):
    id: uuid.UUID
    version: int
    patient_id: uuid.UUID
    encounter_id: uuid.UUID
    note_type: str
    title: str | None
    status: str
    sensitivity: str
    author_id: uuid.UUID | None
    revisions: list[RevisionOut]


class EntrySummary(BaseModel):
    """The current signed text of an entry, as the chart shows it."""

    id: uuid.UUID
    encounter_id: uuid.UUID
    note_type: str
    title: str | None
    status: str
    revision_number: int
    body: str
    signed_at: datetime
    signed_by_id: uuid.UUID


# --- clinical correspondence (SA-12; UG04) ---------------------------------------------

DocType = Annotated[str, StringConstraints(pattern=r"^[a-z_]{3,32}$")]


class PatientHint(Strict):
    """Who the sender says the document is about, for matching."""

    family_name: Name
    given_names: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    birth_date: date
    administrative_sex: AdministrativeSex
    nin: str | None = Field(default=None, max_length=32)


class ReceiveDocument(Strict):
    sender: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]
    received_at: AwareDatetime
    document_type: DocType = Field(description="For example letter, discharge_summary, result.")
    title: str | None = Field(default=None, max_length=200)
    media_type: str = Field(max_length=64)
    content_base64: str = Field(max_length=14_000_000)
    patient_hint: PatientHint | None = None


class FileDocument(Strict):
    patient_id: uuid.UUID
    encounter_id: uuid.UUID | None = None
    reviewer_id: uuid.UUID
    title: str | None = Field(default=None, max_length=200)
    adjudication: str | None = Field(
        default=None,
        max_length=500,
        description="Required when more than one patient could match (UG04).",
    )


class ReindexDocument(Strict):
    patient_id: uuid.UUID
    encounter_id: uuid.UUID | None = None
    title: str | None = Field(default=None, max_length=200)
    document_type: DocType
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class ReviewDocument(Strict):
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)]


class DocumentVersionOut(BaseModel):
    version_number: int
    digest: str
    patient_id: uuid.UUID | None
    encounter_id: uuid.UUID | None
    title: str | None
    document_type: str
    reason: str
    recorded_at: datetime
    author_id: uuid.UUID | None


class DocumentOut(BaseModel):
    id: uuid.UUID
    version: int
    sender: str
    received_at: datetime
    document_type: str
    title: str | None
    media_type: str
    digest: str
    scan: str
    scan_reason: str | None
    status: str
    patient_id: uuid.UUID | None
    encounter_id: uuid.UUID | None
    reviewer_id: uuid.UUID | None
    reviewed_at: datetime | None
    review_note: str | None
    adjudication: str | None
    candidates: list[CandidateOut] = []
    versions: list[DocumentVersionOut] = []


class DocumentSummary(BaseModel):
    id: uuid.UUID
    sender: str
    received_at: datetime
    document_type: str
    title: str | None
    status: str
    encounter_id: uuid.UUID | None
    reviewed: bool


# --- Daybook tasks (UG03) ---------------------------------------------------------------


class CreateTask(Strict):
    patient_id: uuid.UUID | None = None
    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
    task_type: TaskType = TaskType.GENERAL
    priority: TaskPriority = TaskPriority.ROUTINE
    due_at: AwareDatetime
    assignee_id: uuid.UUID | None = None
    queue: str | None = Field(default=None, max_length=64, description="A role, e.g. nurse.")


class ReassignTask(Strict):
    assignee_id: uuid.UUID | None = None
    queue: str | None = Field(default=None, max_length=64)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class CompleteTask(Strict):
    note: str | None = Field(default=None, max_length=1000)


class CancelTask(Strict):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class AssignmentOut(BaseModel):
    assignee_id: uuid.UUID | None
    queue: str | None
    reason: str
    assigned_by_id: uuid.UUID | None
    recorded_at: datetime


class TaskOut(BaseModel):
    id: uuid.UUID
    version: int
    patient_id: uuid.UUID | None
    subject: str
    task_type: str
    priority: str
    status: str
    due_at: datetime
    overdue: bool
    assignee_id: uuid.UUID | None
    queue: str | None
    origin_type: str | None
    origin_id: uuid.UUID | None
    escalation_step: int
    created_by_id: uuid.UUID | None
    acknowledged_at: datetime | None
    completed_at: datetime | None
    completed_by_id: uuid.UUID | None
    outcome_note: str | None
    history: list[AssignmentOut]


# --- discharge (HS05, WF06 step 3, ST08) -----------------------------------------------


class DraftDischarge(Strict):
    disposition: Disposition
    summary: NoteBody
    follow_up: str | None = Field(default=None, max_length=2000)


class OutstandingItem(Strict):
    kind: OutstandingKind
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)
    ] = Field(description="Shown as the task subject: no clinical detail.")
    owner_id: uuid.UUID | None = None
    queue: str | None = Field(default=None, max_length=64)
    due_at: AwareDatetime
    exception_reason: str | None = Field(
        default=None,
        max_length=500,
        description="When no owner can be named: a supervised exception (HS05).",
    )


class Discharge(Strict):
    discharged_at: AwareDatetime
    outstanding: list[OutstandingItem] = Field(default_factory=list, max_length=50)


class DischargeSummaryOut(BaseModel):
    id: uuid.UUID
    version: int
    encounter_id: uuid.UUID
    patient_id: uuid.UUID
    status: str
    disposition: str
    summary: str
    follow_up: str | None
    author_id: uuid.UUID | None
    discharged_at: datetime | None
    signed_at: datetime | None
    signed_by_id: uuid.UUID | None
    tasks: list[uuid.UUID] = Field(
        default_factory=list, description="Tasks opened for the outstanding items."
    )


# --- conditions and care plans (HS12; SA-08) -------------------------------------------


class RecordCondition(Strict):
    code_system: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    code: Code
    display: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    certainty: Certainty = Certainty.CONFIRMED
    onset_date: date | None = None
    register_code: Pathway | None = Field(
        default=None, description="Puts the patient on this condition register."
    )


class ConditionOut(BaseModel):
    id: uuid.UUID
    version: int
    patient_id: uuid.UUID
    code_system: str
    code: str
    display: str
    certainty: str
    onset_date: date | None
    register_code: str | None
    recorded_at: datetime
    author_id: uuid.UUID | None


class RevisionIn(Strict):
    effective_from: AwareDatetime
    session_type: SessionType
    interval_days: int = Field(description="Days between sessions, 1 to 365.")
    sessions: int = Field(description="How many sessions to schedule, 1 to 52.")
    instructions: NoteBody
    protocol_code: str | None = Field(default=None, max_length=64)


class CreatePlan(Strict):
    patient_id: uuid.UUID
    condition_id: uuid.UUID | None = None
    pathway: Pathway
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
    owner_id: uuid.UUID
    review_date: date
    revision: RevisionIn


class RevisePlan(RevisionIn):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class CompleteCycle(Strict):
    note: str | None = Field(default=None, max_length=1000)


class ReleaseCycle(Strict):
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class DiscontinuePlan(Strict):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class PlanRevisionOut(BaseModel):
    id: uuid.UUID
    revision_number: int
    effective_from: datetime
    session_type: str
    interval_days: int
    instructions: str
    protocol_code: str | None
    authorised_by_id: uuid.UUID
    reason: str
    recorded_at: datetime


class PlanCycleOut(BaseModel):
    id: uuid.UUID
    version: int
    plan_revision_id: uuid.UUID
    revision_number: int
    scheduled_at: datetime
    status: str
    completed_at: datetime | None
    completed_by_id: uuid.UUID | None
    outcome_note: str | None


class CarePlanOut(BaseModel):
    id: uuid.UUID
    version: int
    patient_id: uuid.UUID
    condition_id: uuid.UUID | None
    pathway: str
    title: str
    owner_id: uuid.UUID
    status: str
    review_date: date
    current_revision: int
    discontinuation_reason: str | None
    revisions: list[PlanRevisionOut]
    cycles: list[PlanCycleOut]


class CarePlanSummary(BaseModel):
    id: uuid.UUID
    pathway: str
    title: str
    owner_id: uuid.UUID
    status: str
    review_date: date
    current_revision: int
    next_session: datetime | None


ChartOut.model_rebuild()


# --- wards, beds and occupancy (HS03, WF02 step 3) ----------------------------------


class CreateWard(Strict):
    facility_id: uuid.UUID
    code: Code
    name: str = Field(min_length=1, max_length=200)
    specialty: Code | None = None


class CreateBed(Strict):
    code: Code
    isolation_capable: bool = False


class SetBedStatus(Strict):
    status: BedStatus
    reason: str | None = Field(default=None, max_length=500)


class SetWardStatus(Strict):
    active: bool


class AssignBed(Strict):
    bed_id: uuid.UUID
    isolation: bool = False
    reason: str | None = Field(default=None, max_length=500)


class OccupancyOut(BaseModel):
    id: uuid.UUID
    bed_id: uuid.UUID
    bed_code: str
    ward_id: uuid.UUID
    ward_code: str
    encounter_id: uuid.UUID
    patient_id: uuid.UUID
    start_at: datetime
    end_at: datetime | None
    end_reason: EndReason | None
    isolation: bool
    reason: str | None
    previous_id: uuid.UUID | None


class BedOut(BaseModel):
    id: uuid.UUID
    version: int
    code: str
    status: BedStatus
    isolation_capable: bool
    status_reason: str | None
    occupancy: OccupancyOut | None


class WardOut(BaseModel):
    id: uuid.UUID
    version: int
    facility_id: uuid.UUID
    code: str
    name: str
    specialty: str | None
    active: bool
    beds: list[BedOut]
    available: int
    occupied: int


# --- theatres (HS03, WF05 step 2) ----------------------------------------------------


class CreateTheatre(Strict):
    facility_id: uuid.UUID
    code: Code
    name: str = Field(min_length=1, max_length=200)


class CreateTheatreSession(Strict):
    starts_at: AwareDatetime
    ends_at: AwareDatetime


class SetSessionStatus(Strict):
    status: SessionStatus
    reason: str | None = Field(default=None, max_length=500)


class BookTheatreCase(Strict):
    session_id: uuid.UUID
    encounter_id: uuid.UUID
    surgeon_id: uuid.UUID
    procedure: str = Field(min_length=1, max_length=200)
    procedure_code: Code | None = None
    laterality: Laterality
    estimated_minutes: int = Field(ge=5, le=24 * 60)
    care_plan_id: uuid.UUID | None = None


class RecordChecklistStep(Strict):
    step: ChecklistStep


class StartCase(Strict):
    override_reason: str | None = Field(default=None, min_length=1, max_length=500)


class CompleteCase(Strict):
    procedure_note: str = Field(min_length=1, max_length=20000)
    override_reason: str | None = Field(default=None, min_length=1, max_length=500)


class CancelCase(Strict):
    reason: str = Field(min_length=1, max_length=500)


class HandOverCase(Strict):
    recipient_id: uuid.UUID
    note: str | None = Field(default=None, max_length=2000)


class ChecklistEntry(BaseModel):
    step: ChecklistStep
    by_id: uuid.UUID | None
    at: datetime


class TheatreCaseOut(BaseModel):
    id: uuid.UUID
    version: int
    session_id: uuid.UUID
    theatre_id: uuid.UUID
    encounter_id: uuid.UUID
    patient_id: uuid.UUID
    surgeon_id: uuid.UUID
    care_plan_id: uuid.UUID | None
    procedure: str
    procedure_code: str | None
    laterality: Laterality
    estimated_minutes: int
    status: CaseStatus
    checklist: list[ChecklistEntry]
    override_reason: str | None
    started_at: datetime | None
    completed_at: datetime | None
    procedure_note: str | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    handover_recipient_id: uuid.UUID | None
    handed_over_at: datetime | None
    handover_note: str | None
    tasks: list[uuid.UUID]


class TheatreSessionOut(BaseModel):
    id: uuid.UUID
    version: int
    theatre_id: uuid.UUID
    theatre_code: str
    starts_at: datetime
    ends_at: datetime
    status: SessionStatus
    status_reason: str | None
    capacity_minutes: int
    booked_minutes: int
    cases: list[uuid.UUID]


class TheatreOut(BaseModel):
    id: uuid.UUID
    version: int
    facility_id: uuid.UUID
    code: str
    name: str
    active: bool


# --- radiology (HS07, WF05 step 1) ----------------------------------------------------


class RequestImaging(Strict):
    patient_id: uuid.UUID
    encounter_id: uuid.UUID
    code_system: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    code: Code
    display: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    modality: ImagingModality
    body_site: str = Field(min_length=1, max_length=100)
    laterality: Laterality
    priority: OrderPriority = OrderPriority.ROUTINE
    clinical_note: str = Field(min_length=1, max_length=1000)  # the radiologist vets on it
    result_owner_id: uuid.UUID | None = None


class VetImaging(Strict):
    decision: VetDecision
    protocol: str | None = Field(default=None, max_length=200)
    reason: str | None = Field(default=None, max_length=1000)


class ScheduleImaging(Strict):
    scheduled_at: AwareDatetime


class PatientIdentifierIn(Strict):
    issuer: Code
    value: Code


class ReceiveStudy(Strict):
    """A study arriving from the modality or PACS, with the identity it carries."""

    study_instance_uid: str = Field(pattern=r"^[0-9]+(\.[0-9]+)*$", max_length=64)
    accession_number: Code
    modality: ImagingModality
    performed_at: AwareDatetime
    pacs_reference: str = Field(min_length=1, max_length=255)
    patient_identifier: PatientIdentifierIn
    birth_date: date


class LinkStudy(Strict):
    imaging_request_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=500)


class ReportImaging(Strict):
    findings: str = Field(min_length=1, max_length=20000)
    conclusion: str = Field(min_length=1, max_length=2000)


class AddendumIn(Strict):
    text: str = Field(min_length=1, max_length=20000)
    needs_review: bool = True


class ImagingStudyOut(BaseModel):
    id: uuid.UUID
    version: int
    study_instance_uid: str
    accession_number: str
    modality: ImagingModality
    performed_at: datetime
    status: StudyStatus
    conflicts: list[str]
    imaging_request_id: uuid.UUID | None
    patient_id: uuid.UUID | None
    linked_by_id: uuid.UUID | None
    linked_at: datetime | None
    link_reason: str | None
    # The identity the study arrived with: on the reconciliation list only.
    received_issuer: str | None = None
    received_identifier: str | None = None
    received_birth_date: date | None = None


class ImagingRequestOut(BaseModel):
    id: uuid.UUID
    version: int
    service_request_id: uuid.UUID
    patient_id: uuid.UUID
    encounter_id: uuid.UUID
    code: str
    display: str
    priority: OrderPriority
    clinical_note: str | None
    modality: ImagingModality
    body_site: str
    laterality: Laterality
    state: ImagingState
    protocol: str | None
    vetting_note: str | None
    vetted_by_id: uuid.UUID | None
    scheduled_at: datetime | None
    accession_number: str | None
    studies: list[ImagingStudyOut]
    reports: list[ReportOut]


class ViewerAccessOut(BaseModel):
    """Short-lived, patient-bound access to one study in the PACS viewer."""

    study_instance_uid: str
    url: str
    token: str
    expires_at: datetime


class PacsCheck(Strict):
    token: str = Field(min_length=1, max_length=4096)
    study_instance_uid: str = Field(max_length=64)


class PacsCheckOut(BaseModel):
    study_instance_uid: str
    patient_id: uuid.UUID
    practitioner_id: uuid.UUID


# --- interfaces: HL7 v2 (CEDA section 6, WF03) -----------------------------------------


MessageStatus = Literal["processed", "held", "rejected"]


class Hl7In(Strict):
    message: str = Field(min_length=8, max_length=1_000_000)


class Hl7Out(BaseModel):
    message_id: uuid.UUID | None
    control_id: str | None
    message_type: str | None
    status: str  # processed, held or rejected
    ack_code: str  # AA accepted, AE application error, AR rejected
    error_code: str | None
    detail: str | None
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None
    ack: str | None  # the HL7 ACK message, for engines that want it verbatim


class InterfaceMessageOut(BaseModel):
    id: uuid.UUID
    sender: str
    control_id: str
    message_type: str
    status: str
    ack_code: str
    error_code: str | None
    detail: str | None
    placer_key: str | None
    patient_id: uuid.UUID | None
    resource_type: str | None
    resource_id: uuid.UUID | None
    recorded_at: datetime
    processed_at: datetime | None
