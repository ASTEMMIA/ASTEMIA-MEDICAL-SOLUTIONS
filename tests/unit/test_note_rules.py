"""Clinical note rules (SA-07, UG02, ST04): pure domain."""

import pytest

from astemia.domain import notes as nt
from astemia.domain.common import InvalidTransition, InvariantViolation

E = nt.EntryStatus


def test_signing_moves_a_draft_to_signed_then_amended() -> None:
    assert nt.after_signing(E.DRAFT, True) is E.SIGNED
    assert nt.after_signing(E.SIGNED, False) is E.AMENDED
    assert nt.after_signing(E.AMENDED, False) is E.AMENDED
    with pytest.raises(InvalidTransition):
        nt.after_signing(E.DRAFT, False)


def test_signing_needs_an_identified_patient_and_a_live_encounter() -> None:
    nt.check_identified("active")
    with pytest.raises(InvariantViolation) as e:
        nt.check_identified("temporary")
    assert e.value.code == "patient_unidentified"
    nt.check_writable("finished")
    for state in ("cancelled", "entered_in_error"):
        with pytest.raises(InvalidTransition):
            nt.check_writable(state)


def test_nurses_sign_nursing_notes_and_clinicians_sign_the_rest() -> None:
    assert nt.SIGN_CAPABILITY[nt.NoteType.NURSING] == "note:sign_nursing"
    assert {nt.SIGN_CAPABILITY[t] for t in nt.NoteType if t is not nt.NoteType.NURSING} == {
        "note:sign"
    }
