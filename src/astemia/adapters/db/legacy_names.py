"""Naming rules for legacy ERD entities and fields (ZETTER, AE_AMS, AHIS, PDi, AMS master).

The owner's rules, with no exceptions:

* The NHS number and NHS ID name a person's national identifier, so they
  become NIN, the Nigerian National Identification Number.
* Every other NHS becomes Astemia Medical Solutions.
* GP becomes medical doctor.

The original label is kept only as lineage (the extract dictionary's
source_label). This module is the one place that has to recognise the old
terms in the source ERDs.
"""

import re

_IDENTIFIERS = [
    # "NHS Number" / NHS_NUMBER / nhs_number / NHS_ID name the identifier itself: NIN.
    (re.compile(r"(?<![A-Za-z])NHS[ _](?:Number|ID)(?![a-z])"), "NIN"),
    (re.compile(r"(?<![A-Za-z])NHS_(?:NUMBER|ID)(?![A-Za-z])"), "NIN"),
    (re.compile(r"(?<![A-Za-z])nhs_(?:number|id)(?![A-Za-z])"), "nin"),
    (re.compile(r"\bNHAIS\b", re.I), "NIMC"),
]
_NHS = re.compile(r"(?<![A-Za-z])NHS(?![A-Za-z])", re.I)


def rename_nhs(label: str) -> str:
    """NHS number and NHS ID become NIN; every other NHS becomes Astemia Medical Solutions."""
    for pattern, repl in _IDENTIFIERS:
        label = pattern.sub(repl, label)

    def replace(m: re.Match[str]) -> str:
        text, start, end = m.group(0), m.start(), m.end()
        snake = (start > 0 and label[start - 1] == "_") or (end < len(label) and label[end] == "_")
        if snake:
            return "ASTEMIA_MEDICAL_SOLUTIONS" if text.isupper() else "astemia_medical_solutions"
        return "Astemia Medical Solutions"

    return _NHS.sub(replace, label)


# GP (general practitioner) is named "medical doctor", the term the ZETTER ERD
# already uses ("Registered Medical Doctor Number"). GP only as a word of its
# own: the CDS suffix VGP (variant grouping) is untouched.
_GP = re.compile(r"(?<![A-Za-z])(GP|gp|Gp)(?![A-Za-z])")


def gp_to_medical_doctor(label: str) -> str:
    def replace(m: re.Match[str]) -> str:
        text, start, end = m.group(0), m.start(), m.end()
        snake = (start > 0 and label[start - 1] == "_") or (end < len(label) and label[end] == "_")
        if snake:
            return "MEDICAL_DOCTOR" if text.isupper() else "medical_doctor"
        return "Medical Doctor" if text.isupper() else "medical doctor"

    return _GP.sub(replace, label)


def localise(label: str) -> str:
    """ASTEMIA naming for a legacy ERD label (see the module docstring)."""
    return gp_to_medical_doctor(rename_nhs(label))


def column_name(label: str) -> str:
    """'Date Name Valis To' -> 'date_name_valis_to'; 'A+E Arrival Mode' -> 'ae_arrival_mode'."""
    label = localise(label).replace("A+E", "AE").replace("+", " plus ")
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


# National-extract fields that carry the patient's identifier. medicare_number
# is retired in favour of the NIN, so outbound returns populate these from the
# NIN. Matched on exact labels: "MEDICARE Service Agreement ...", "MEDICARE
# Site" and similar name the Medicare programme, not a person, and stay unmapped.
NIN_VALUE = "patient_identifier[issuer=NG-NIN].value"
NIN_STATUS = "patient_identifier[issuer=NG-NIN].verification_status"
NIN_PSEUDONYM = "pseudonymise(patient_identifier[issuer=NG-NIN].value)"
_IDENTIFIER_FIELDS = {
    "medicare number": NIN_VALUE,
    "medicare_number": NIN_VALUE,
    "medicare_id": NIN_VALUE,
    "nin": NIN_VALUE,
    "medicare number status indicator": NIN_STATUS,
    "medicare_number_status_ind": NIN_STATUS,
    "status of medicare no": NIN_STATUS,
    "nin_status_ind": NIN_STATUS,
    "medicare_number_pseud": NIN_PSEUDONYM,
    "nin_pseud": NIN_PSEUDONYM,
}


def identifier_mapping(label: str) -> str | None:
    return _IDENTIFIER_FIELDS.get(label.strip().lower())
