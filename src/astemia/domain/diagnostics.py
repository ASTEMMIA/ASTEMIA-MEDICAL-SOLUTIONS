"""Orders, results and acknowledgement (CEDA 3.2; Annex A WF03)."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from astemia.domain.common import InvariantViolation, transition


class ServiceRequestStatus(StrEnum):
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    REVOKED = "revoked"
    ENTERED_IN_ERROR = "entered_in_error"


class OrderPriority(StrEnum):
    ROUTINE = "routine"
    URGENT = "urgent"
    STAT = "stat"


_ORDER: dict[ServiceRequestStatus, frozenset[ServiceRequestStatus]] = {
    ServiceRequestStatus.ACTIVE: frozenset(
        {
            ServiceRequestStatus.ON_HOLD,
            ServiceRequestStatus.COMPLETED,
            ServiceRequestStatus.REVOKED,
            ServiceRequestStatus.ENTERED_IN_ERROR,
        }
    ),
    ServiceRequestStatus.ON_HOLD: frozenset(
        {ServiceRequestStatus.ACTIVE, ServiceRequestStatus.REVOKED}
    ),
    # A completed order stays completed when an amended report arrives.
    ServiceRequestStatus.COMPLETED: frozenset({ServiceRequestStatus.COMPLETED}),
}


def move_order(current: ServiceRequestStatus, target: ServiceRequestStatus) -> ServiceRequestStatus:
    return transition(current, target, _ORDER, "order")


class ReportStatus(StrEnum):
    PRELIMINARY = "preliminary"
    FINAL = "final"
    AMENDED = "amended"
    CANCELLED = "cancelled"


class ObservationStatus(StrEnum):
    PRELIMINARY = "preliminary"
    FINAL = "final"
    AMENDED = "amended"
    CANCELLED = "cancelled"


class ValueType(StrEnum):
    QUANTITY = "quantity"
    STRING = "string"
    CODED = "coded"


class Flag(StrEnum):
    NORMAL = "N"
    LOW = "L"
    HIGH = "H"
    ABNORMAL = "A"


@dataclass(frozen=True, slots=True)
class ObservationValue:
    value_type: ValueType
    quantity: Decimal | None = None
    unit: str | None = None  # UCUM
    text: str | None = None
    code: str | None = None
    ref_low: Decimal | None = None
    ref_high: Decimal | None = None

    def __post_init__(self) -> None:
        match self.value_type:
            case ValueType.QUANTITY:
                if self.quantity is None or not self.unit:
                    raise InvariantViolation("a quantity needs a value and a UCUM unit")
            case ValueType.STRING:
                if not self.text:
                    raise InvariantViolation("a string result needs text")
            case ValueType.CODED:
                if not self.code:
                    raise InvariantViolation("a coded result needs a code")
        if self.ref_low is not None and self.ref_high is not None and self.ref_low > self.ref_high:
            raise InvariantViolation("reference range low is above high")

    def flag(self) -> Flag | None:
        if self.value_type is not ValueType.QUANTITY or self.quantity is None:
            return None
        if self.ref_low is not None and self.quantity < self.ref_low:
            return Flag.LOW
        if self.ref_high is not None and self.quantity > self.ref_high:
            return Flag.HIGH
        if self.ref_low is None and self.ref_high is None:
            return None
        return Flag.NORMAL


def release_status(existing: ReportStatus | None, requested: ReportStatus) -> ReportStatus:
    """A release on an order that already has a final report is an amendment."""
    if requested is ReportStatus.CANCELLED:
        raise InvariantViolation("cancel a report through its own action")
    if existing in (ReportStatus.FINAL, ReportStatus.AMENDED):
        return ReportStatus.AMENDED
    return requested


class ReviewState(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    ESCALATED = "escalated"
    SUPERSEDED = "superseded"


_REVIEW: dict[ReviewState, frozenset[ReviewState]] = {
    ReviewState.OPEN: frozenset(
        {ReviewState.ACKNOWLEDGED, ReviewState.ESCALATED, ReviewState.SUPERSEDED}
    ),
    ReviewState.ESCALATED: frozenset({ReviewState.ACKNOWLEDGED, ReviewState.SUPERSEDED}),
}


def move_review(current: ReviewState, target: ReviewState) -> ReviewState:
    return transition(current, target, _REVIEW, "result review")
