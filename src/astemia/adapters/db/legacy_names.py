"""Naming rules for legacy ERD entities and fields (ZETTER, AE_AMS, AHIS).

NHS identifiers are renamed to NIN, the Nigerian National Identification
Number, everywhere ASTEMIA stores or exposes them. The original label is kept
in the extract dictionary for traceability. The NHS business-service code is
named after the ERD's own Medicare BS Code instead, because it is a service
code and not a person identifier.
"""

import re

_SPECIFIC = [
    (re.compile(r"\bNHS\s+BS\b", re.I), "Medicare BS"),
    # "NHS Number" / NHS_NUMBER / nhs_number / NHS_ID name the identifier itself: NIN.
    (re.compile(r"(?<![A-Za-z])NHS[ _](?:Number|ID)(?![a-z])"), "NIN"),
    (re.compile(r"(?<![A-Za-z])NHS_(?:NUMBER|ID)(?![A-Za-z])"), "NIN"),
    (re.compile(r"(?<![A-Za-z])nhs_(?:number|id)(?![A-Za-z])"), "nin"),
    (re.compile(r"\bNHAIS\b", re.I), "NIMC"),
]
_NHS = re.compile(r"(?<![A-Za-z])NHS(?![A-Za-z])|(?<=_)NHS(?=_)|^NHS(?=_)|(?<=_)NHS$", re.I)


def nhs_to_nin(label: str) -> str:
    for pattern, repl in _SPECIFIC:
        label = pattern.sub(repl, label)

    def same_case(m: re.Match[str]) -> str:
        text = m.group(0)
        return "NIN" if text.isupper() else ("nin" if text.islower() else "Nin")

    return _NHS.sub(same_case, label)


def column_name(label: str) -> str:
    """'Date Name Valis To' -> 'date_name_valis_to'; 'A+E Arrival Mode' -> 'ae_arrival_mode'."""
    label = nhs_to_nin(label).replace("A+E", "AE").replace("+", " plus ")
    slug = re.sub(r"[^0-9A-Za-z]+", "_", label).strip("_").lower()
    slug = re.sub(r"_+", "_", slug)
    if not slug or slug[0].isdigit():
        slug = f"f_{slug}"
    return slug[:56]


def entity_key(name: str) -> str:
    """Normalise entity names across ERDs: 'Address /Party', 'ADDRESS/PARTY' and
    'Address Party' are one entity; parenthetical model tags are dropped."""
    name = re.sub(r"\(\s*LRS LOGICAL DATA MODEL\s*\)", "", name, flags=re.I)
    name = name.replace("Legitmate", "Legitimate").replace(
        "HealthProfessional", "Healthcare Professional"
    )
    return column_name(name)


def unique_names(labels: list[str]) -> list[tuple[str, str, int]]:
    """(label, key, occurrence) with repeated labels suffixed _2, _3, ..."""
    seen: dict[str, int] = {}
    out = []
    for label in labels:
        base = column_name(label)
        seen[base] = seen.get(base, 0) + 1
        n = seen[base]
        out.append((label, base if n == 1 else f"{base[:52]}_{n}", n))
    return out
