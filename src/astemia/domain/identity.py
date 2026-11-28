"""Patient identity register rules (CEDA 3.2 Patient, PatientIdentifier)."""

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from astemia.domain.common import EffectivePrecision, InvalidTransition, InvariantViolation


class NameType(StrEnum):
    USUAL = "usual"
    PREFERRED = "preferred"
    MAIDEN = "maiden"
    ALIAS = "alias"
    PREVIOUS = "previous"


class PatientStatus(StrEnum):
    ACTIVE = "active"
    TEMPORARY = "temporary"
    MERGED = "merged"
    DECEASED = "deceased"
    CLOSED = "closed"  # closed in the index: moved away or discharged from all services


# Records still open in the patient index.
OPEN_STATUSES = frozenset({PatientStatus.ACTIVE, PatientStatus.TEMPORARY})


class AdministrativeSex(StrEnum):
    FEMALE = "female"
    MALE = "male"
    OTHER = "other"
    UNKNOWN = "unknown"


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    REJECTED = "rejected"


# Issuer authorities switched on per tenant country profile (CEDA 6.4). Values
# are validated for shape only; verification against the national service is
# an adapter concern.
IDENTIFIER_FORMATS: dict[str, re.Pattern[str]] = {
    # National Identification Number issued by NIMC: 11 digits.
    "NG-NIN": re.compile(r"^\d{11}$"),
    # Medicare number from the legacy PDI (ERD medicare_number). Retired in
    # favour of the NIN: kept only as a previous identifier on migrated records.
    "NG-MEDICARE": re.compile(r"^[A-Z0-9-]{4,20}$"),
    # Local patient identifier, scoped by the issuing organisation.
    "LOCAL-MRN": re.compile(r"^[A-Z0-9-]{3,32}$"),
}


class IdentifierType(StrEnum):
    CURRENT = "current"
    TEMPORARY = "temporary"
    OLD_STYLE = "old_style"
    PREVIOUS = "previous"


# Issuers that may no longer be bound as a live identifier. Their values are
# kept as previous identifiers so legacy records can still be matched.
RETIRED_ISSUERS: dict[str, str] = {"NG-MEDICARE": "NG-NIN"}


def check_issuer_allowed(issuer: str, identifier_type: IdentifierType) -> None:
    if issuer in RETIRED_ISSUERS and identifier_type is not IdentifierType.PREVIOUS:
        raise InvariantViolation(
            f"{issuer} is retired in favour of {RETIRED_ISSUERS[issuer]}; "
            "record it only as a previous identifier",
            code="medicare_number_retired",
        )


def binds_actively(issuer: str) -> bool:
    """A retired issuer's number never holds the active, unique binding."""
    return issuer not in RETIRED_ISSUERS


def validate_identifier(issuer: str, value: str) -> str:
    pattern = IDENTIFIER_FORMATS.get(issuer)
    if pattern is None:
        raise InvariantViolation(f"unknown identifier issuer {issuer!r}", code="unknown_issuer")
    normalised = value.replace(" ", "").upper()
    if not pattern.match(normalised):
        raise InvariantViolation(
            f"identifier value is not valid for {issuer}", code="bad_identifier"
        )
    return normalised


# Postcode formats by country (ISO 3166-1 alpha-2). Nigeria uses six-digit
# NIPOST codes; UK codes keep their outward and inward parts.
POSTCODE_FORMATS = {
    "NG": re.compile(r"^\d{6}$"),
    "GB": re.compile(r"^[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}$"),
}
OTHER_POSTCODE = re.compile(r"^[A-Z0-9][A-Z0-9 -]{1,10}[A-Z0-9]$")


def normalise_postcode(country: str, postcode: str) -> str:
    """The postcode as it is filed: upper case, single spaces, a UK code split
    into its two parts. Refused when it does not fit the country's format."""
    value = " ".join(postcode.upper().split())
    if country == "GB" and " " not in value and len(value) >= 5:
        value = f"{value[:-3]} {value[-3:]}"
    pattern = POSTCODE_FORMATS.get(country, OTHER_POSTCODE)
    if not pattern.match(value):
        raise InvariantViolation(
            f"postcode is not valid for country {country}", code="bad_postcode"
        )
    return value


def check_address(
    *, temporary: bool, has_address: bool, country: str | None, state: str | None, lga: str | None
) -> None:
    """Every patient is registered with a full address and postcode. Only an
    unidentified (temporary) registration, such as an unconscious patient, may
    wait for it. A Nigerian address names its state and local government area."""
    if not has_address:
        if temporary:
            return
        raise InvariantViolation(
            "a full address with postcode is required to register a patient",
            code="address_required",
        )
    if country == "NG" and not (state and lga):
        raise InvariantViolation(
            "a Nigerian address needs its state and local government area",
            code="address_incomplete",
        )


class AddressChangeReason(StrEnum):
    MOVED = "moved"  # the patient lives somewhere new
    CORRECTION = "correction"  # the address on file was wrong
    IDENTIFIED = "identified"  # an unidentified patient's address, now known


def check_address_change(status: str, reason: AddressChangeReason, same_as_current: bool) -> None:
    """A changed address ends the current one and keeps it as history. A merged
    record is changed through the record it was merged into; an address that is
    already on file is not filed again."""
    if status == PatientStatus.MERGED:
        raise InvariantViolation(
            "this record was merged: change the address on the record it was merged into",
            code="patient_merged",
        )
    if reason is AddressChangeReason.IDENTIFIED and status != PatientStatus.TEMPORARY:
        raise InvariantViolation(
            "'identified' is for a patient registered without an identity",
            code="not_temporary",
        )
    if same_as_current:
        raise InvariantViolation("this address is already on file", code="address_unchanged")


def validate_birth_date(birth_date: date, precision: EffectivePrecision, today: date) -> None:
    if birth_date > today:
        raise InvariantViolation("date of birth is in the future", code="bad_birth_date")
    if precision not in (EffectivePrecision.YEAR, EffectivePrecision.DAY):
        raise InvariantViolation("date of birth precision is year or day", code="bad_birth_date")


# -- Patient index stewardship (ICRS 3.2.8-3.2.21, 3.2.33) ---------------------


class ClosureReason(StrEnum):
    DEATH = "death"
    MOVED_AWAY = "moved_away"
    DISCHARGED = "discharged"


def duplicate_key(family_name: str, birth_date: date, sex: str) -> tuple[str, date, str]:
    """Records that share this key are probable duplicates (ICRS 3.2.8, 3.2.11)."""
    return (" ".join(family_name.split()).casefold(), birth_date, sex)


def check_merge(
    prior_id: object, survivor_id: object, prior_status: str, survivor_status: str
) -> None:
    if prior_id == survivor_id:
        raise InvariantViolation("a record cannot be merged into itself", code="merge_into_self")
    if prior_status not in OPEN_STATUSES:
        raise InvalidTransition(f"a {prior_status} record cannot be merged", code="not_mergeable")
    if survivor_status not in OPEN_STATUSES:
        raise InvalidTransition(
            f"a record cannot be merged into a {survivor_status} record",
            code="survivor_not_open",
        )


def check_identifiers_compatible(prior: dict[str, str], survivor: dict[str, str]) -> None:
    """Two records holding different values from the same issuer are two people."""
    clashes = sorted(i for i in prior.keys() & survivor.keys() if prior[i] != survivor[i])
    if clashes:
        raise InvariantViolation(
            "the records hold different identifiers from " + ", ".join(clashes),
            code="identifier_mismatch",
        )


def closure_status(reason: ClosureReason) -> PatientStatus:
    return PatientStatus.DECEASED if reason is ClosureReason.DEATH else PatientStatus.CLOSED


def check_closable(status: str, exit_date: date, birth_date: date, today: date) -> None:
    if status not in OPEN_STATUSES:
        raise InvalidTransition(f"a {status} record cannot be closed", code="not_closable")
    if exit_date > today:
        raise InvariantViolation("closure date is in the future", code="bad_closure_date")
    if exit_date < birth_date:
        raise InvariantViolation("closure date is before birth", code="bad_closure_date")


# -- Explainable matching (UG02, WF01 step 1; ICRS 3.2.34) ---------------------

MATCH_LIKELY = 85
MATCH_POSSIBLE = 60

_SOUNDEX = {
    **dict.fromkeys("BFPV", "1"),
    **dict.fromkeys("CGJKQSXZ", "2"),
    **dict.fromkeys("DT", "3"),
    "L": "4",
    **dict.fromkeys("MN", "5"),
    "R": "6",
}


def phonetic(name: str) -> str:
    """Soundex key, so spelling variants of a name sort together."""
    letters = [c for c in name.upper() if "A" <= c <= "Z"]
    if not letters:
        return ""
    key, last = letters[0], _SOUNDEX.get(letters[0], "")
    for c in letters[1:]:
        code = _SOUNDEX.get(c, "")
        if code and code != last:
            key += code
        if c not in "HW":
            last = code
    return (key + "000")[:4]


class MatchBand(StrEnum):
    LIKELY = "likely"
    POSSIBLE = "possible"


@dataclass(frozen=True, slots=True)
class Demographics:
    family_name: str
    given_name: str
    birth_date: date
    birth_date_precision: EffectivePrecision
    administrative_sex: str
    mother_name: str | None = None
    identifiers: frozenset[tuple[str, str]] = frozenset()
    verified: frozenset[tuple[str, str]] = frozenset()


@dataclass(frozen=True, slots=True)
class MatchScore:
    score: int
    reasons: tuple[str, ...]

    @property
    def band(self) -> MatchBand | None:
        if self.score >= MATCH_LIKELY:
            return MatchBand.LIKELY
        if self.score >= MATCH_POSSIBLE:
            return MatchBand.POSSIBLE
        return None


def _same(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def score_match(probe: Demographics, candidate: Demographics) -> MatchScore:
    """Explainable match score, 0 to 100. Every point carries a reason, so the
    registrar and the steward see why two records were put side by side."""
    if probe.identifiers & candidate.identifiers:
        return MatchScore(100, ("identifier",))
    score, reasons = 0, list[str]()
    both_days = (
        probe.birth_date_precision == candidate.birth_date_precision == EffectivePrecision.DAY
    )
    if both_days and probe.birth_date == candidate.birth_date:
        score += 30
        reasons.append("birth_date")
    elif not both_days and probe.birth_date.year == candidate.birth_date.year:
        score += 15
        reasons.append("birth_year")
    if _same(probe.family_name, candidate.family_name):
        score += 25
        reasons.append("family_name")
    elif phonetic(probe.family_name) == phonetic(candidate.family_name):
        score += 15
        reasons.append("family_name_sounds_like")
    if _same(probe.given_name, candidate.given_name):
        score += 20
        reasons.append("given_name")
    elif phonetic(probe.given_name) == phonetic(candidate.given_name):
        score += 10
        reasons.append("given_name_sounds_like")
    elif probe.given_name[:1].casefold() == candidate.given_name[:1].casefold():
        score += 5
        reasons.append("given_initial")
    if probe.administrative_sex == candidate.administrative_sex != "unknown":
        score += 5
        reasons.append("administrative_sex")
    if _same(probe.mother_name, candidate.mother_name):
        score += 10
        reasons.append("mother_name")
    probe_issuers = dict(probe.verified)
    if any(probe_issuers.get(issuer, value) != value for issuer, value in candidate.verified):
        # Two different verified national numbers: strong evidence of two people.
        score -= 40
        reasons.append("verified_identifier_differs")
    return MatchScore(max(score, 0), tuple(reasons))
