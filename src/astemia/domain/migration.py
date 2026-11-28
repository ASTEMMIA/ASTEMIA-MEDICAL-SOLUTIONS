"""Migration of existing patient records (CEDA MIG-01 to MIG-03). Pure rules.

Legacy rows are staged verbatim with a digest of their values. Each staged
person becomes a canonical patient only if it passes the same checks as the
registration desk; otherwise it is quarantined with a reason. A source row
that has been loaded once is never loaded again, and a changed version of it
is quarantined rather than applied over the live record. Reconciliation
compares counts, and a digest of each loaded patient's identity as mapped
against the same digest taken from the live record.
"""

import hashlib
import json
import re
from datetime import date
from enum import StrEnum

from astemia.domain.common import InvariantViolation


class RecordStatus(StrEnum):
    LOADED = "loaded"
    QUARANTINED = "quarantined"


# Legacy sex codes (PDS/PDI style) as administrative sex.
SEX = {
    "M": "male",
    "1": "male",
    "MALE": "male",
    "F": "female",
    "2": "female",
    "FEMALE": "female",
    "U": "unknown",
    "0": "unknown",
    "9": "unknown",
    "I": "other",
}

_DATES = (
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"), (1, 2, 3)),
    (re.compile(r"^(\d{4})(\d{2})(\d{2})$"), (1, 2, 3)),
    (re.compile(r"^(\d{2})/(\d{2})/(\d{4})$"), (3, 2, 1)),  # day/month/year
)


def row_digest(values: dict[str, str | None]) -> str:
    """The digest of a staged row's values, independent of field order."""
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def legacy_date(text: str | None, field: str) -> date:
    for pattern, (y, m, d) in _DATES:
        found = pattern.match((text or "").strip())
        if found:
            try:
                return date(int(found[y]), int(found[m]), int(found[d]))
            except ValueError:
                break
    raise InvariantViolation(f"{field} {text!r} is not a date", code="bad_date")


def legacy_sex(code: str | None) -> str:
    sex = SEX.get((code or "").strip().upper())
    if sex is None:
        raise InvariantViolation(f"sex code {code!r} is not known", code="bad_sex")
    return sex


def identity_digest(nin: str, birth_date: date, sex: str, family: str, given: str) -> str:
    """What reconciliation compares: the identity as mapped at load, and the
    same fields read back from the live record."""
    parts = [nin, birth_date.isoformat(), sex, family.strip().upper(), given.strip().upper()]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()
