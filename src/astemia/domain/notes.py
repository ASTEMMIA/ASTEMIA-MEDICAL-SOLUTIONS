"""Clinical notes (CEDA SA-07 ClinicalEntry and EntryRevision; UG02, WF01 step 3,
ST04). Pure rules.

An entry is drafted, then signed. Signing freezes that revision for good; a
correction is a new revision that references the one it replaces, and the
original stays with its author.
"""

from enum import StrEnum

from astemia.domain.common import InvalidTransition, InvariantViolation, transition


class NoteType(StrEnum):
    CONSULTATION = "consultation"
    PROGRESS = "progress"
    WARD_ROUND = "ward_round"
    PROCEDURE = "procedure"
    NURSING = "nursing"
    MENTAL_HEALTH_ASSESSMENT = "mental_health_assessment"


# The capability needed to sign each note type: nurses sign nursing notes,
# clinicians sign everything (ST04: no signing without signing permission).
SIGN_CAPABILITY: dict[NoteType, str] = {
    **dict.fromkeys(NoteType, "note:sign"),
    NoteType.NURSING: "note:sign_nursing",
}


class EntryStatus(StrEnum):
    DRAFT = "draft"
    SIGNED = "signed"
    AMENDED = "amended"  # signed, with a later signed correction


_ENTRY: dict[EntryStatus, frozenset[EntryStatus]] = {
    EntryStatus.DRAFT: frozenset({EntryStatus.SIGNED}),
    EntryStatus.SIGNED: frozenset({EntryStatus.AMENDED}),
    EntryStatus.AMENDED: frozenset({EntryStatus.AMENDED}),
}


def after_signing(current: EntryStatus, first_revision: bool) -> EntryStatus:
    target = EntryStatus.SIGNED if first_revision else EntryStatus.AMENDED
    return transition(current, target, _ENTRY, "entry")


class RevisionStatus(StrEnum):
    DRAFT = "draft"
    SIGNED = "signed"


def check_identified(patient_status: str) -> None:
    """UG02: no signed entry against an unidentified (temporary) chart."""
    if patient_status == "temporary":
        raise InvariantViolation(
            "identify the patient before signing; the chart is a temporary identity",
            code="patient_unidentified",
        )


def check_writable(encounter_state: str) -> None:
    if encounter_state in ("cancelled", "entered_in_error"):
        raise InvalidTransition(
            f"notes cannot be written on a {encounter_state} encounter",
            code="encounter_not_writable",
        )
