// Generated from the API's OpenAPI schema by tools/web_types.py. Do not edit:
// change the Pydantic models and regenerate.

export type AccessEntry = {
  occurred_at: string;
  actor_subject: string;
  actor_practitioner_id: string | null;
  action: string;
  outcome: string;
  reason_code: string | null;
  flags: string[];
};

export type AccessReportOut = {
  patient_id: string;
  start: string;
  end: string;
  entries: AccessEntry[];
  by_actor: ActorSummary[];
  flagged: number;
};

export type Acknowledge = {
  note?: string | null;
};

export type ActivateService = {
  facility_id: string;
  owner_id: string;
  approval_reference: string;
  queue_roles?: string[];
};

export type ActorSummary = {
  actor_subject: string;
  entries: number;
  flagged: number;
};

export type AdministrativeSex = "female" | "male" | "other" | "unknown";

export type AdmitEncounter = {
  patient_id: string;
  facility_id: string;
  responsible_practitioner_id: string;
  visit_authority: string;
  visit_number: string;
  encounter_class?: EncounterClass;
  service: string;
  admission_route?: string | null;
  admitted_at: string;
  sensitivity?: Sensitivity;
  ae?: AeAttendanceIn | null;
};

/** A&E detail for an emergency admission (ERD AE_TRANSACTION). */
export type AeAttendanceIn = {
  attendance_number: string;
  arrival_mode: string;
  attendance_category: string;
  patient_group?: string | null;
  referral_source?: string | null;
  incident_location_type?: string | null;
  initial_assessment_at?: string | null;
};

export type AeAttendanceOut = {
  attendance_number: string;
  arrival_mode: string;
  attendance_category: string;
  patient_group?: string | null;
  referral_source?: string | null;
  incident_location_type?: string | null;
  arrival_at: string;
  initial_assessment_at?: string | null;
  seen_for_treatment_at?: string | null;
  conclusion_at?: string | null;
  departure_at?: string | null;
  attendance_disposal?: string | null;
};

export type AmendEntry = {
  body: string;
  reason: string;
};

export type AppointAdvocate = {
  practitioner_id: string;
};

export type AssignmentOut = {
  assignee_id: string | null;
  queue: string | null;
  reason: string;
  assigned_by_id: string | null;
  recorded_at: string;
};

export type AttendanceOutcome = "attended" | "no_show" | "failed_connection";

export type BookAppointment = {
  hold_id: string;
  patient_id: string;
  referral_id?: string | null;
  reason?: string | null;
};

export type CancelAppointment = {
  reason: string;
};

export type CancelTask = {
  reason: string;
};

/** A possible duplicate, with only enough shown to tell people apart. */
export type CandidateOut = {
  id: string;
  /** For If-Match when this record is merged. */
  version: number;
  status: string;
  score: number;
  band: string | null;
  reasons: string[];
  family_name: string;
  given_initial: string;
  birth_year: number;
  administrative_sex: string;
  identifiers: IdentifierOut[];
};

export type CarePlanOut = {
  id: string;
  version: number;
  patient_id: string;
  condition_id: string | null;
  pathway: string;
  title: string;
  owner_id: string;
  status: string;
  review_date: string;
  current_revision: number;
  discontinuation_reason: string | null;
  revisions: PlanRevisionOut[];
  cycles: PlanCycleOut[];
};

export type CarePlanSummary = {
  id: string;
  pathway: string;
  title: string;
  owner_id: string;
  status: string;
  review_date: string;
  current_revision: number;
  next_session: string | null;
};

export type Certainty = "provisional" | "confirmed" | "refuted";

export type ChartOut = {
  patient: PatientOut;
  encounters: EncounterOut[];
  orders: OrderOut[];
  reports: ReportOut[];
  open_reviews: ReviewOut[];
  masked_fields: string[];
  withheld_records: number;
  merged_from?: string[];
  /** care_relationship, or emergency_grant for time-boxed emergency access */
  access_basis?: string;
  /** Mental health legal status in force (ICRS 5.5.15). */
  legal_status?: LegalStatusOut | null;
  /** Signed clinical notes, newest first. */
  entries?: EntrySummary[];
  /** Filed correspondence, newest first. */
  documents?: DocumentSummary[];
  /** Signed discharge summaries, newest first. */
  discharges?: DischargeSummaryOut[];
  /** The problem list, refuted conditions excluded. */
  conditions?: ConditionOut[];
  care_plans?: CarePlanSummary[];
};

/** A batch of closures, for example a list of death registrations (ICRS 3.2.20). */
export type CloseBatch = {
  items: ClosureItem[];
};

export type CloseConcern = {
  outcome: "upheld" | "not_upheld";
  note: string;
};

/** Close a record in the index (ICRS 3.2.18-3.2.19). */
export type ClosePatient = {
  reason: ClosureReason;
  exit_date: string;
};

export type ClosureItem = {
  reason: ClosureReason;
  exit_date: string;
  patient_id: string;
};

export type ClosureReason = "death" | "moved_away" | "discharged";

export type CompleteCycle = {
  note?: string | null;
};

export type CompleteTask = {
  note?: string | null;
};

export type ConcernCategory = "restrictive_practice" | "neglect" | "dignity" | "medication" | "abuse" | "other";

export type ConcernOut = {
  id: string;
  version: number;
  patient_id: string;
  raised_by: string;
  raised_by_name: string | null;
  recorded_by: string | null;
  category: string;
  description: string;
  about_practitioner_id: string | null;
  status: string;
  respond_by: string;
  overdue: boolean;
  closed_at: string | null;
  closed_by_id: string | null;
  outcome_note: string | null;
  recorded_at: string;
};

export type ConcernStatus = "open" | "upheld" | "not_upheld";

export type ConditionOut = {
  id: string;
  version: number;
  patient_id: string;
  code_system: string;
  code: string;
  display: string;
  certainty: string;
  onset_date: string | null;
  register_code: string | null;
  recorded_at: string;
  author_id: string | null;
};

export type CreateEntry = {
  note_type: NoteType;
  title?: string | null;
  body: string;
  sensitivity?: Sensitivity;
};

export type CreatePlan = {
  patient_id: string;
  condition_id?: string | null;
  pathway: Pathway;
  title: string;
  owner_id: string;
  review_date: string;
  revision: RevisionIn;
};

/** A run of consecutive slots for one clinician, service and site. */
export type CreateSlots = {
  facility_id: string;
  practitioner_id: string;
  service: string;
  starts_at: string;
  /** Length of each slot, 5 to 240. */
  minutes?: number;
  /** How many consecutive slots, 1 to 50. */
  count?: number;
  slot_type?: SlotType;
  modality?: Modality;
  timezone?: string;
};

export type CreateTask = {
  patient_id?: string | null;
  subject: string;
  task_type?: TaskType;
  priority?: Priority;
  due_at: string;
  assignee_id?: string | null;
  /** A role, e.g. nurse. */
  queue?: string | null;
};

export type DecideReferral = {
  decision: "accepted" | "rejected";
  reason?: string | null;
};

export type Discharge = {
  discharged_at: string;
  outstanding?: OutstandingItem[];
};

export type DischargeSummaryOut = {
  id: string;
  version: number;
  encounter_id: string;
  patient_id: string;
  status: string;
  disposition: string;
  summary: string;
  follow_up: string | null;
  author_id: string | null;
  discharged_at: string | null;
  signed_at: string | null;
  signed_by_id: string | null;
  /** Tasks opened for the outstanding items. */
  tasks?: string[];
};

export type DiscontinuePlan = {
  reason: string;
};

export type Disposition = "home" | "home_with_support" | "transferred" | "self_discharge" | "died";

export type DocumentOut = {
  id: string;
  version: number;
  sender: string;
  received_at: string;
  document_type: string;
  title: string | null;
  media_type: string;
  digest: string;
  scan: string;
  scan_reason: string | null;
  status: string;
  patient_id: string | null;
  encounter_id: string | null;
  reviewer_id: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  adjudication: string | null;
  candidates?: CandidateOut[];
  versions?: DocumentVersionOut[];
};

export type DocumentStatus = "quarantined" | "rejected" | "filed" | "reviewed";

export type DocumentSummary = {
  id: string;
  sender: string;
  received_at: string;
  document_type: string;
  title: string | null;
  status: string;
  encounter_id: string | null;
  reviewed: boolean;
};

export type DocumentVersionOut = {
  version_number: number;
  digest: string;
  patient_id: string | null;
  encounter_id: string | null;
  title: string | null;
  document_type: string;
  reason: string;
  recorded_at: string;
  author_id: string | null;
};

export type DraftDischarge = {
  disposition: Disposition;
  summary: string;
  follow_up?: string | null;
};

/** Open index records that share family name, date of birth and sex. */
export type DuplicateGroup = {
  family_name: string;
  birth_date: string;
  administrative_sex: string;
  patient_ids: string[];
};

export type EffectivePrecision = "year" | "day" | "minute" | "second";

export type EmergencyGrantOut = {
  id: string;
  version: number;
  patient_id: string;
  practitioner_id: string;
  purpose: string;
  scope: string;
  starts_at: string;
  expires_at: string;
  live: boolean;
  step_up: string;
  review_due_at: string;
  review_overdue: boolean;
  reviewed_at: string | null;
  reviewed_by_id: string | null;
  review_outcome: string | null;
  review_note: string | null;
};

export type EncounterClass = "inpatient" | "emergency" | "ambulatory" | "day_case" | "virtual";

export type EncounterOut = {
  id: string;
  version: number;
  patient_id: string;
  facility_id: string;
  responsible_practitioner_id: string;
  visit_authority: string;
  visit_number: string;
  encounter_class: string;
  service: string;
  state: string;
  period_start: string;
  period_end?: string | null;
  clinical_service_id?: string | null;
  ae?: AeAttendanceOut | null;
  disposition?: string | null;
};

export type EndIntervention = {
  ended_at: string;
  debrief_offered: boolean;
  injury?: boolean;
  injury_detail?: string | null;
};

export type EntryOut = {
  id: string;
  version: number;
  patient_id: string;
  encounter_id: string;
  note_type: string;
  title: string | null;
  status: string;
  sensitivity: string;
  author_id: string | null;
  revisions: RevisionOut[];
};

/** The current signed text of an entry, as the chart shows it. */
export type EntrySummary = {
  id: string;
  encounter_id: string;
  note_type: string;
  title: string | null;
  status: string;
  revision_number: number;
  body: string;
  signed_at: string;
  signed_by_id: string;
};

/** A site where care happens (CEDA facility). */
export type FacilityOut = {
  id: string;
  site_identifier: string;
  site_name: string;
  organisation_id: string;
  organisation_name: string;
};

export type FileDocument = {
  patient_id: string;
  encounter_id?: string | null;
  reviewer_id: string;
  title?: string | null;
  /** Required when more than one patient could match (UG04). */
  adjudication?: string | null;
};

export type HTTPValidationError = {
  detail?: ValidationError[];
};

export type IdentifierIn = {
  issuer: string;
  value: string;
  identifier_type?: string;
  verified?: boolean;
};

export type IdentifierOut = {
  issuer: string;
  value: string;
  identifier_type: string;
  verification_status: string;
};

export type InterventionOut = {
  id: string;
  version: number;
  patient_id: string;
  encounter_id: string | null;
  intervention_type: string;
  reason: string;
  authorised_by_id: string;
  recorded_by_id: string | null;
  staff_ids: string[];
  started_at: string;
  ended_at: string | null;
  duration_minutes: number | null;
  injury: boolean;
  injury_detail: string | null;
  debrief_offered: boolean | null;
  legal_status_id: string | null;
  flags: string[];
  review_due_at: string;
  review_overdue: boolean;
  reviewed_at: string | null;
  reviewed_by_id: string | null;
  review_outcome: string | null;
  review_note: string | null;
};

export type InterventionType = "physical_restraint" | "mechanical_restraint" | "seclusion" | "rapid_tranquillisation";

/** An order still waiting for its result, with the patient it is for. */
export type LabOrderOut = {
  order: OrderOut;
  patient: PatientOut;
  ordered_at: string;
};

/** The patient's legal status under mental health law (ICRS 5.5.9). */
export type LegalStatus = "informal" | "emergency_holding" | "detained_assessment" | "detained_treatment" | "community_treatment";

export type LegalStatusOut = {
  id: string;
  version: number;
  patient_id: string;
  status: string;
  legal_basis: string | null;
  valid_from: string;
  valid_until: string | null;
  authorised_by_id: string;
  reason: string;
  ended_at: string | null;
  current: boolean;
  lapsed: boolean;
  expiring: boolean;
};

export type MatchOut = {
  candidates: CandidateOut[];
};

/** Search before registering. Demographics travel in the body, never in a URL. */
export type MatchQuery = {
  family_name: string;
  given_names: string;
  birth_date: string;
  birth_date_precision?: EffectivePrecision;
  administrative_sex: AdministrativeSex;
  mother_name?: string | null;
  identifiers?: IdentifierIn[];
};

export type MeOut = {
  subject: string;
  tenant_id: string;
  tenant_name: string;
  roles: string[];
  capabilities: string[];
  practitioner_id: string | null;
  display_name: string;
};

/** Merge this (prior) record into the survivor (ICRS 3.2.12, 3.2.33). */
export type MergePatient = {
  survivor_id: string;
  reason: string;
};

export type Modality = "in_person" | "video" | "phone" | "home";

export type NameOut = {
  name_type: string;
  title?: string | null;
  family_name: string;
  given_name: string;
  other_given_name?: string | null;
  suffix?: string | null;
};

export type NoteType = "consultation" | "progress" | "ward_round" | "procedure" | "nursing" | "mental_health_assessment";

export type ObservationIn = {
  code_system: string;
  code: string;
  display: string;
  value_type: ValueType;
  quantity?: number | string | null;
  unit?: string | null;
  text?: string | null;
  value_code?: string | null;
  ref_low?: number | string | null;
  ref_high?: number | string | null;
  original_value?: string | null;
};

export type ObservationOut = {
  observation_id: string;
  revision_id: string;
  revision: number;
  code_system: string;
  code: string;
  display: string;
  status: string;
  value_type: string;
  quantity?: string | null;
  unit?: string | null;
  text?: string | null;
  value_code?: string | null;
  ref_low?: string | null;
  ref_high?: string | null;
  flag?: string | null;
};

export type OrderOut = {
  id: string;
  version: number;
  patient_id: string;
  encounter_id: string;
  placer_authority: string;
  placer_id: string;
  code_system: string;
  code: string;
  display: string;
  status: string;
  priority: string;
  requester_id: string;
  result_owner_id: string;
};

export type OrderPriority = "routine" | "urgent" | "stat";

export type OutstandingItem = {
  kind: OutstandingKind;
  /** Shown as the task subject: no clinical detail. */
  description: string;
  owner_id?: string | null;
  queue?: string | null;
  due_at: string;
  /** When no owner can be named: a supervised exception (HS05). */
  exception_reason?: string | null;
};

export type OutstandingKind = "medication" | "referral" | "follow_up";

export type Pathway = "diabetes" | "renal" | "cardiovascular" | "oncology" | "older_person";

/** Who the sender says the document is about, for matching. */
export type PatientHint = {
  family_name: string;
  given_names: string;
  birth_date: string;
  administrative_sex: AdministrativeSex;
  nin?: string | null;
};

export type PatientOut = {
  id: string;
  version: number;
  family_name: string;
  given_names: string;
  birth_date: string;
  birth_date_precision: string;
  administrative_sex: string;
  status: string;
  names?: NameOut[];
  identifiers?: IdentifierOut[];
  date_of_exit?: string | null;
  merged_into?: string | null;
};

export type PlaceOrder = {
  patient_id: string;
  encounter_id: string;
  code_system: string;
  code: string;
  display: string;
  original_system?: string | null;
  original_code?: string | null;
  priority?: OrderPriority;
  result_owner_id?: string | null;
  backup_owner_id?: string | null;
  clinical_note?: string | null;
};

export type PlanCycleOut = {
  id: string;
  version: number;
  plan_revision_id: string;
  revision_number: number;
  scheduled_at: string;
  status: string;
  completed_at: string | null;
  completed_by_id: string | null;
  outcome_note: string | null;
};

export type PlanRevisionOut = {
  id: string;
  revision_number: number;
  effective_from: string;
  session_type: string;
  interval_days: number;
  instructions: string;
  protocol_code: string | null;
  authorised_by_id: string;
  reason: string;
  recorded_at: string;
};

/** A member of staff as others see them: for names on records and pickers. */
export type PractitionerOut = {
  id: string;
  display_name: string;
  professional_register: string | null;
  specialist_area: string | null;
};

export type Priority = "routine" | "urgent";

export type ProvisionCatalogue = {
  facility_id: string;
  /** Department groups to provision; all when omitted. */
  group_codes?: string[] | null;
};

export type RaiseConcern = {
  patient_id: string;
  raised_by: RaisedBy;
  raised_by_name?: string | null;
  category: ConcernCategory;
  description: string;
  /** The member of staff the concern is about, if any. */
  about_practitioner_id?: string | null;
};

export type RaisedBy = "patient" | "family" | "advocate" | "staff";

export type ReassignTask = {
  assignee_id?: string | null;
  queue?: string | null;
  reason: string;
};

export type ReceiveDocument = {
  sender: string;
  received_at: string;
  /** For example letter, discharge_summary, result. */
  document_type: string;
  title?: string | null;
  media_type: string;
  content_base64: string;
  patient_hint?: PatientHint | null;
};

export type RecordAttendance = {
  outcome: AttendanceOutcome;
  /** Required for a video or phone consultation that took place (UG02). */
  identity_verified?: boolean;
};

export type RecordCondition = {
  code_system: string;
  code: string;
  display: string;
  certainty?: Certainty;
  onset_date?: string | null;
  /** Puts the patient on this condition register. */
  register_code?: Pathway | null;
};

export type RecordIntervention = {
  patient_id: string;
  encounter_id?: string | null;
  intervention_type: InterventionType;
  /** Why less restrictive options were not enough. */
  reason: string;
  authorised_by_id: string;
  staff_ids: string[];
  started_at: string;
  ended_at?: string | null;
  injury?: boolean;
  injury_detail?: string | null;
  debrief_offered?: boolean | null;
};

export type ReferralOut = {
  id: string;
  version: number;
  patient_id: string;
  referrer_id: string;
  source_encounter_id: string;
  requesting_service: string | null;
  receiving_service: string;
  priority: string;
  reason: string;
  status: string;
  decided_by_id: string | null;
  decided_at: string | null;
  decision_reason: string | null;
  recorded_at: string;
  referring_facility_id: string | null;
  receiving_facility_id: string | null;
  referring_level: string | null;
  receiving_level: string | null;
  records_count: number | null;
};

export type ReferralPriority = "routine" | "urgent";

/** The patient's historical records that travel with a referral, as the receiving team may see them: masked and with sensitive records withheld. */
export type ReferralRecordsOut = {
  referral: ReferralOut;
  patient: PatientOut;
  encounters: EncounterOut[];
  orders: OrderOut[];
  reports: ReportOut[];
  masked_fields: string[];
  withheld_records: number;
};

export type ReferralStatus = "submitted" | "accepted" | "rejected" | "scheduled" | "closed";

export type RegisterPatient = {
  title?: string | null;
  family_name: string;
  given_names: string;
  mother_name?: string | null;
  father_name?: string | null;
  preferred_language?: string | null;
  state_of_origin?: string | null;
  birth_date: string;
  birth_date_precision?: EffectivePrecision;
  administrative_sex: AdministrativeSex;
  temporary?: boolean;
  identifiers?: IdentifierIn[];
};

export type ReindexDocument = {
  patient_id: string;
  encounter_id?: string | null;
  title?: string | null;
  document_type: string;
  reason: string;
};

export type ReleaseCycle = {
  note: string;
};

export type ReleaseReport = {
  service_request_id: string;
  status?: ReportStatus;
  filler_authority?: string | null;
  filler_id?: string | null;
  effective_at: string;
  conclusion?: string | null;
  observations: ObservationIn[];
};

export type ReportOut = {
  id: string;
  version: number;
  service_request_id: string;
  patient_id: string;
  status: string;
  released_at: string;
  prior_report_id?: string | null;
  review_id?: string | null;
  observations?: ObservationOut[];
};

export type ReportStatus = "preliminary" | "final" | "amended" | "cancelled";

export type RequestEmergencyAccess = {
  patient_id: string;
  /** Why the chart is needed now; read by the privacy reviewer. */
  purpose: string;
};

export type RescheduleAppointment = {
  /** A live hold on the new slot. */
  hold_id: string;
};

export type ResolveReview = {
  /** A merge (POST /v1/patients/{id}/merge) resolves the task itself. */
  resolution: "distinct";
  reason: string;
};

export type RetireService = {
  reason: string;
};

export type ReviewDocument = {
  note: string;
};

export type ReviewEmergencyAccess = {
  outcome: "appropriate" | "inappropriate";
  note: string;
};

export type ReviewIntervention = {
  outcome: ReviewOutcome;
  note: string;
};

export type ReviewOut = {
  id: string;
  version: number;
  report_id: string;
  patient_id: string;
  assignee_id: string;
  state: string;
  acknowledged_at?: string | null;
};

export type ReviewOutcome = "appropriate" | "concerns" | "escalated";

export type ReviewTaskOut = {
  id: string;
  version: number;
  score: number;
  reasons: string[];
  origin: string | null;
  note: string | null;
  resolved: boolean;
  resolution: string | null;
  resolved_at: string | null;
  resolved_by_id: string | null;
  records: CandidateOut[];
};

export type RevisePlan = {
  effective_from: string;
  session_type: SessionType;
  /** Days between sessions, 1 to 365. */
  interval_days: number;
  /** How many sessions to schedule, 1 to 52. */
  sessions: number;
  instructions: string;
  protocol_code?: string | null;
  reason: string;
};

export type RevisionIn = {
  effective_from: string;
  session_type: SessionType;
  /** Days between sessions, 1 to 365. */
  interval_days: number;
  /** How many sessions to schedule, 1 to 52. */
  sessions: number;
  instructions: string;
  protocol_code?: string | null;
};

export type RevisionOut = {
  id: string;
  revision_number: number;
  status: string;
  body: string;
  author_id: string | null;
  recorded_at: string;
  signed_at: string | null;
  signed_by_id: string | null;
  supersedes_id: string | null;
  amendment_reason: string | null;
};

export type Sensitivity = "normal" | "restricted" | "mental_health" | "sexual_health" | "safeguarding" | "genetics";

export type ServiceOut = {
  id: string;
  version: number;
  code: string;
  name: string;
  group_code: string | null;
  group_name: string | null;
  division: string | null;
  age_policy: string;
  care_settings: string[];
  status: string;
  owner_id?: string | null;
  facilities?: string[];
};

export type SessionType = "dialysis" | "treatment_cycle" | "monitoring" | "review";

export type SetLegalStatus = {
  status: LegalStatus;
  /** The law and power, required when detained. */
  legal_basis?: string | null;
  valid_from: string;
  valid_until?: string | null;
  authorised_by_id: string;
  reason: string;
};

export type SlotOut = {
  id: string;
  facility_id: string;
  practitioner_id: string;
  service: string;
  slot_type: string;
  modality: string;
  starts_at: string;
  ends_at: string;
  timezone: string;
  status: string;
};

export type SlotType = "new" | "follow_up" | "urgent";

export type SubmitReferral = {
  patient_id: string;
  referring_facility_id: string;
  /** The general, teaching or specialist hospital (or other facility) the patient is referred to. The patient's historical records always go with it. */
  receiving_facility_id: string;
  /** The care episode whose records go with the referral; defaults to the patient's most recent one. A patient with no care records is refused. */
  encounter_id?: string | null;
  receiving_service: string;
  requesting_service?: string | null;
  priority?: ReferralPriority;
  reason: string;
};

export type TaskOut = {
  id: string;
  version: number;
  patient_id: string | null;
  subject: string;
  task_type: string;
  priority: string;
  status: string;
  due_at: string;
  overdue: boolean;
  assignee_id: string | null;
  queue: string | null;
  origin_type: string | null;
  origin_id: string | null;
  escalation_step: number;
  created_by_id: string | null;
  acknowledged_at: string | null;
  completed_at: string | null;
  completed_by_id: string | null;
  outcome_note: string | null;
  history: AssignmentOut[];
};

export type TaskType = "recall" | "referral_follow_up" | "result_follow_up" | "document_review" | "discharge_follow_up" | "general";

export type UnmergePatient = {
  reason: string;
};

export type UpdateDraft = {
  body: string;
};

export type ValidationError = {
  loc: (string | number)[];
  msg: string;
  type: string;
  input?: unknown;
  ctx?: Record<string, unknown>;
};

export type ValueType = "quantity" | "string" | "coded";
