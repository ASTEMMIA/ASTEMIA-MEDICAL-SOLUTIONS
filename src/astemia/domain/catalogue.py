"""Service catalogue rules (Annex A16, CAT-01..05). Pure Python."""

from enum import StrEnum

from astemia.domain.common import InvariantViolation, transition


class ServiceStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class AgePolicy(StrEnum):
    ADULT = "adult"
    PAEDIATRIC = "paediatric"
    ALL = "all"


class CareSetting(StrEnum):
    EMERGENCY = "emergency"
    INPATIENT = "inpatient"
    OUTPATIENT = "outpatient"
    DAY_CASE = "day_case"
    COMMUNITY = "community"
    VIRTUAL = "virtual"
    DIAGNOSTIC = "diagnostic"
    SUPPORT = "support"


_STATUS: dict[ServiceStatus, frozenset[ServiceStatus]] = {
    ServiceStatus.DRAFT: frozenset({ServiceStatus.ACTIVE, ServiceStatus.RETIRED}),
    ServiceStatus.ACTIVE: frozenset({ServiceStatus.RETIRED}),
}


def move(current: ServiceStatus, target: ServiceStatus) -> ServiceStatus:
    return transition(current, target, _STATUS, "service")


def check_activation(owner_set: bool, facility_set: bool, approval_reference: str | None) -> None:
    """CAT-01/CAT-05: a named owner, a facility assignment and documented approval."""
    missing = [
        name
        for name, ok in (
            ("owner", owner_set),
            ("facility", facility_set),
            ("approval", bool(approval_reference)),
        )
        if not ok
    ]
    if missing:
        raise InvariantViolation(
            "service cannot be activated without: " + ", ".join(missing),
            code="activation_incomplete",
        )
