"""Encounter state machine (CEDA 3.2 Encounter; Annex A WF02)."""

from enum import StrEnum

from astemia.domain.common import transition


class EncounterClass(StrEnum):
    INPATIENT = "inpatient"
    EMERGENCY = "emergency"
    AMBULATORY = "ambulatory"
    DAY_CASE = "day_case"
    VIRTUAL = "virtual"


class EncounterState(StrEnum):
    PLANNED = "planned"
    ARRIVED = "arrived"
    IN_PROGRESS = "in_progress"
    ON_LEAVE = "on_leave"
    FINISHED = "finished"
    CANCELLED = "cancelled"
    ENTERED_IN_ERROR = "entered_in_error"


_ALLOWED: dict[EncounterState, frozenset[EncounterState]] = {
    EncounterState.PLANNED: frozenset(
        {EncounterState.ARRIVED, EncounterState.IN_PROGRESS, EncounterState.CANCELLED}
    ),
    EncounterState.ARRIVED: frozenset({EncounterState.IN_PROGRESS, EncounterState.CANCELLED}),
    EncounterState.IN_PROGRESS: frozenset(
        {EncounterState.ON_LEAVE, EncounterState.FINISHED, EncounterState.ENTERED_IN_ERROR}
    ),
    EncounterState.ON_LEAVE: frozenset({EncounterState.IN_PROGRESS, EncounterState.FINISHED}),
}

# States in which new clinical activity (orders, notes) may attach.
OPEN_STATES = frozenset(
    {EncounterState.ARRIVED, EncounterState.IN_PROGRESS, EncounterState.ON_LEAVE}
)


def move(current: EncounterState, target: EncounterState) -> EncounterState:
    return transition(current, target, _ALLOWED, "encounter")


def admission_state(encounter_class: EncounterClass) -> EncounterState:
    """An admission recorded through POST /v1/encounters starts in progress."""
    return EncounterState.IN_PROGRESS
