"""Wards, beds and occupancy (CEDA HS03, WF02 step 3). Pure rules.

A bed holds at most one patient at a time and an encounter occupies at most
one bed at a time; the database guards both. A transfer closes the old
occupancy and opens the new one in the same transaction, so a patient is
never in two beds or in none in between.
"""

from enum import StrEnum

from astemia.domain.common import InvariantViolation
from astemia.domain.encounter import OPEN_STATES, EncounterClass, EncounterState


class BedStatus(StrEnum):
    AVAILABLE = "available"
    CLOSED = "closed"  # out of use: cleaning, repair, staffing


class EndReason(StrEnum):
    TRANSFER = "transfer"
    DISCHARGE = "discharge"


# Encounters that are given a bed. Clinic and virtual visits are not.
BEDDED_CLASSES = frozenset(
    {EncounterClass.INPATIENT, EncounterClass.EMERGENCY, EncounterClass.DAY_CASE}
)


def check_encounter(state: EncounterState, encounter_class: EncounterClass) -> None:
    if encounter_class not in BEDDED_CLASSES:
        raise InvariantViolation(
            f"a {encounter_class.value} encounter is not given a bed", code="encounter_not_bedded"
        )
    if state not in OPEN_STATES:
        raise InvariantViolation(
            f"the encounter is {state.value}; only an open encounter takes a bed",
            code="encounter_not_open",
        )


def check_bed(
    status: BedStatus,
    ward_active: bool,
    isolation_capable: bool,
    *,
    isolation: bool,
    same_facility: bool,
) -> None:
    """A bed can be given only if it is open, on an open ward in the patient's
    facility, and can isolate the patient when isolation is needed."""
    if not ward_active:
        raise InvariantViolation("that ward is closed", code="ward_closed")
    if status is not BedStatus.AVAILABLE:
        raise InvariantViolation("that bed is closed", code="bed_closed")
    if not same_facility:
        raise InvariantViolation(
            "that bed is in another facility; transfer the patient between facilities first",
            code="bed_in_another_facility",
        )
    if isolation and not isolation_capable:
        raise InvariantViolation(
            "the patient needs isolation and that bed cannot provide it",
            code="isolation_unavailable",
        )
