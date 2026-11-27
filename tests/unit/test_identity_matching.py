"""Duplicate matching and merge rules (UG02, WF01, E3): pure domain."""

import uuid
from datetime import date

import pytest

from astemia.domain import identity as idn
from astemia.domain.common import EffectivePrecision, InvalidTransition

DAY, YEAR = EffectivePrecision.DAY, EffectivePrecision.YEAR


def person(**kw: object) -> idn.Demographics:
    base: dict[str, object] = {
        "family_name": "Adeyemi",
        "given_name": "Folake",
        "birth_date": date(1984, 3, 9),
        "birth_date_precision": DAY,
        "administrative_sex": "female",
        "mother_name": "Bisi Adeyemi",
    }
    return idn.Demographics(**{**base, **kw})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Robert", "R163"),
        ("Rupert", "R163"),
        ("Ashcraft", "A261"),  # H between two letters of the same code
        ("Tymczak", "T522"),
        ("Pfister", "P236"),
        ("Adeyemi", "A350"),
        ("Adeyemmi", "A350"),
        ("O'Kafor", "O216"),
        ("", ""),
        ("123", ""),
    ],
)
def test_phonetic_key(name: str, key: str) -> None:
    assert idn.phonetic(name) == key


def test_same_person_is_a_likely_match_with_every_reason() -> None:
    m = idn.score_match(person(), person(family_name=" adeyemi ", mother_name="bisi  adeyemi"))
    assert m.score == 90 and m.band is idn.MatchBand.LIKELY
    assert m.reasons == (
        "birth_date",
        "family_name",
        "given_name",
        "administrative_sex",
        "mother_name",
    )


def test_a_shared_active_identifier_is_definite() -> None:
    nin = frozenset({("NG-NIN", "12345678901")})
    m = idn.score_match(person(identifiers=nin), person(family_name="Other", identifiers=nin))
    assert (m.score, m.reasons, m.band) == (100, ("identifier",), idn.MatchBand.LIKELY)


def test_spelling_variants_and_initials_score_less() -> None:
    m = idn.score_match(person(), person(family_name="Adeyemmi", given_name="Folakay"))
    assert "family_name_sounds_like" in m.reasons and "given_name_sounds_like" in m.reasons
    assert m.score == 30 + 15 + 10 + 5 + 10 and m.band is idn.MatchBand.POSSIBLE
    m = idn.score_match(person(), person(given_name="Funmi", mother_name=None))
    assert "given_initial" in m.reasons and "mother_name" not in m.reasons


def test_year_only_birth_dates_match_on_the_year() -> None:
    m = idn.score_match(person(), person(birth_date=date(1984, 1, 1), birth_date_precision=YEAR))
    assert "birth_year" in m.reasons and "birth_date" not in m.reasons
    m = idn.score_match(person(), person(birth_date=date(1984, 3, 10)))
    assert "birth_year" not in m.reasons and "birth_date" not in m.reasons


def test_different_verified_numbers_point_to_two_people() -> None:
    a = person(verified=frozenset({("NG-NIN", "11111111111")}))
    b = person(verified=frozenset({("NG-NIN", "22222222222")}))
    m = idn.score_match(a, b)
    assert m.score == 50 and m.band is None and "verified_identifier_differs" in m.reasons
    # Unknown sex never counts, and the score does not go below zero.
    far = idn.score_match(
        idn.Demographics("Eze", "Uche", date(1990, 1, 1), DAY, "unknown", verified=a.verified),
        idn.Demographics("Obi", "Ada", date(1970, 1, 1), DAY, "unknown", verified=b.verified),
    )
    assert far.score == 0 and far.band is None


def test_merge_rules() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    idn.check_merge(a, "temporary", b, "active")
    with pytest.raises(InvalidTransition, match="itself"):
        idn.check_merge(a, "active", a, "active")
    with pytest.raises(InvalidTransition) as e:
        idn.check_merge(a, "merged", b, "active")
    assert e.value.code == "prior_not_mergeable"
    with pytest.raises(InvalidTransition) as e:
        idn.check_merge(a, "active", b, "deceased")
    assert e.value.code == "survivor_not_mergeable"


def test_unmerge_rules() -> None:
    idn.check_unmerge("merge", True)
    with pytest.raises(InvalidTransition) as e:
        idn.check_unmerge("unmerged", True)
    assert e.value.code == "already_unmerged"
    with pytest.raises(InvalidTransition) as e:
        idn.check_unmerge("merge", False)
    assert e.value.code == "not_reversible"
