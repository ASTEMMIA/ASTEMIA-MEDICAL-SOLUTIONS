"""Shared domain vocabulary (CEDA 3.1 envelope). Pure Python: no I/O."""

import uuid
from enum import StrEnum


def new_id() -> uuid.UUID:
    """Time-ordered UUIDv7: opaque, and kind to InnoDB clustered indexes."""
    return uuid.uuid7()


class DomainError(Exception):
    """Base for broken invariants. Carries a stable error code for the API."""

    code = "domain_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class InvariantViolation(DomainError):
    code = "invariant_violation"


class InvalidTransition(DomainError):
    code = "invalid_transition"


class Sensitivity(StrEnum):
    NORMAL = "normal"
    RESTRICTED = "restricted"
    MENTAL_HEALTH = "mental_health"
    SEXUAL_HEALTH = "sexual_health"
    SAFEGUARDING = "safeguarding"
    GENETICS = "genetics"


class EffectivePrecision(StrEnum):
    YEAR = "year"
    DAY = "day"
    MINUTE = "minute"
    SECOND = "second"


class DataAbsentReason(StrEnum):
    """Kept distinct from NULL (CEDA 3.1)."""

    UNKNOWN = "unknown"
    WITHHELD = "withheld"
    CLEARED = "cleared"
    NOT_APPLICABLE = "not_applicable"


def transition[S: StrEnum](current: S, target: S, allowed: dict[S, frozenset[S]], what: str) -> S:
    if target not in allowed.get(current, frozenset()):
        raise InvalidTransition(f"{what} cannot move from {current} to {target}")
    return target
