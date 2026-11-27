"""Command inputs and resource outputs (Pydantic for every input and output)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from astemia.domain.common import EffectivePrecision, Sensitivity
from astemia.domain.diagnostics import OrderPriority, ReportStatus, ValueType
from astemia.domain.encounter import EncounterClass
from astemia.domain.identity import AdministrativeSex

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


class PatientOut(Resource):
    family_name: str
    given_names: str
    birth_date: date
    birth_date_precision: str
    administrative_sex: str
    status: str
    names: list[NameOut] = []
    identifiers: list[IdentifierOut] = []


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
