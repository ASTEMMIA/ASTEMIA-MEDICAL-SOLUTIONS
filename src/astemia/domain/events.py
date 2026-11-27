"""Event contracts (DATA-03). Breaking changes publish a new schema version."""

from enum import StrEnum


class EventType(StrEnum):
    PATIENT_REGISTERED = "patient.registered"
    ENCOUNTER_ADMITTED = "encounter.admitted"
    ORDER_PLACED = "order.placed"
    RESULT_RELEASED = "result.released"
    RESULT_AMENDED = "result.amended"
    RESULT_ACKNOWLEDGED = "result.acknowledged"
    SERVICE_CATALOGUE_CHANGED = "service_catalogue.changed"


SCHEMA_VERSION: dict[EventType, int] = dict.fromkeys(EventType, 1)
