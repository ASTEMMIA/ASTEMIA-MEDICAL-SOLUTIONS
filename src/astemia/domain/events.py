"""Event contracts (DATA-03). Breaking changes publish a new schema version."""

from enum import StrEnum


class EventType(StrEnum):
    PATIENT_REGISTERED = "patient.registered"
    PATIENT_MERGED = "patient.merged"
    PATIENT_UNMERGED = "patient.unmerged"
    PATIENT_CLOSED = "patient.closed"
    IDENTITY_REVIEW_OPENED = "identity_review.opened"
    IDENTITY_REVIEW_RESOLVED = "identity_review.resolved"
    # The privacy alert for every emergency access grant (SEC-04).
    EMERGENCY_ACCESS_GRANTED = "emergency_access.granted"
    EMERGENCY_ACCESS_REVIEWED = "emergency_access.reviewed"
    APPOINTMENT_BOOKED = "appointment.booked"
    APPOINTMENT_RESCHEDULED = "appointment.rescheduled"
    APPOINTMENT_CANCELLED = "appointment.cancelled"
    APPOINTMENT_OUTCOME_RECORDED = "appointment.outcome_recorded"
    REFERRAL_SUBMITTED = "referral.submitted"
    REFERRAL_DECIDED = "referral.decided"
    RESTRICTIVE_INTERVENTION_RECORDED = "restrictive_intervention.recorded"
    RESTRICTIVE_INTERVENTION_ENDED = "restrictive_intervention.ended"
    RESTRICTIVE_INTERVENTION_REVIEWED = "restrictive_intervention.reviewed"
    LEGAL_STATUS_CHANGED = "mental_health_legal_status.changed"
    CONCERN_RAISED = "safeguarding_concern.raised"
    CONCERN_CLOSED = "safeguarding_concern.closed"
    ADVOCATE_APPOINTED = "patient_advocate.appointed"
    ENTRY_SIGNED = "clinical_entry.signed"
    ENCOUNTER_ADMITTED = "encounter.admitted"
    ORDER_PLACED = "order.placed"
    RESULT_RELEASED = "result.released"
    RESULT_AMENDED = "result.amended"
    RESULT_ACKNOWLEDGED = "result.acknowledged"
    SERVICE_CATALOGUE_CHANGED = "service_catalogue.changed"


SCHEMA_VERSION: dict[EventType, int] = dict.fromkeys(EventType, 1)
