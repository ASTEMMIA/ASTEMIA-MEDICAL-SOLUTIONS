"""Patient identity register rules (CEDA 3.2 Patient, PatientIdentifier)."""

import re
from datetime import date
from enum import StrEnum

from astemia.domain.common import EffectivePrecision, InvariantViolation


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


def validate_birth_date(birth_date: date, precision: EffectivePrecision, today: date) -> None:
    if birth_date > today:
        raise InvariantViolation("date of birth is in the future", code="bad_birth_date")
    if precision not in (EffectivePrecision.YEAR, EffectivePrecision.DAY):
        raise InvariantViolation("date of birth precision is year or day", code="bad_birth_date")
