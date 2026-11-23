"""Extract the entity/field catalogue from a Visio database-model (.vsdx) file.

Visio's Database Modeling engine keeps the model in an embedded OLE store
(VisDBEngrData/.../MAPInfo). Each mapping group is an entity; its field names
follow as UTF-16 strings. Relationship labels ("has", "is of") are separated
out. Usage:

    uv run --group tools python tools/extract_vsdx_erd.py ERD.vsdx out.json
"""

import io
import json
import re
import sys
import zipfile

import olefile

STREAM = "VisDBEngrData/VisDBEngrModelEngData/MAPInfo"
REL_LABELS = {"has", "is of"}
# Flat national extracts. Their fields legitimately repeat back to back
# (repeating groups), so inside them only an UPPER_SNAKE table name such as
# STG_999_COM_DIAG starts a nested entity.
FLAT_GROUPS = re.compile(
    r"^(Mental Health Extract|Ward Attenders|Elective Admissions|ADMITTED PATIENT CARE|"
    r"OUTPATIENTS|STG_010_AE_TRANSACTION|AE_TRANSACTION|LND_010_AE_MK)",
    re.I,
)
# Field labels that some ERDs store as if they started a new group, although
# they sit inside a flat extract (seen in PDi_AMS and ZETTER_AMS).
CONTINUATIONS = {
    "Contract serial no",
    "No. organ systems supported",
    "Sheltered Work Attendance Indicator",
}


def strings(blob: bytes) -> list[tuple[str, str]]:
    out = []
    for m in re.finditer(rb"((?:[\x20-\x7e]\x00){3,})|([\x20-\x7e]{3,})", blob):
        if m.group(1):
            out.append(("W", m.group(1).decode("utf-16le")))
        else:
            out.append(("A", m.group(2).decode()))
    return out


def extract(path: str) -> dict[str, object]:
    with zipfile.ZipFile(path) as z:
        ole_name = next(n for n in z.namelist() if n.startswith("visio/embeddings/oleObject"))
        ole = olefile.OleFileIO(io.BytesIO(z.read(ole_name)))
    rows = strings(ole.openstream(STREAM).read())
    starts = [
        i
        for i in range(1, len(rows) - 1)
        if rows[i][0] == "W" and rows[i + 1] == rows[i] and rows[i - 1][0] == "A"
    ]
    entities: list[dict[str, object]] = []
    for k, i in enumerate(starts):
        end = starts[k + 1] - 1 if k + 1 < len(starts) else len(rows)
        texts = [t.strip() for kind, t in rows[i + 2 : end] if kind == "W"]
        # A nested entity (drawn inside a sub-model) is introduced by its name
        # written twice in a row. Inside a flat extract the known repeated field
        # labels (CONTINUATIONS) do not start an entity.
        name = rows[i][1].strip()
        previous = entities[-1] if entities else None
        if previous is not None and previous.get("flat") and name in CONTINUATIONS:
            current = previous  # Visio stored a repeated extract label as a group start
            current["fields"].append(name)  # type: ignore[attr-defined]
        else:
            current = {
                "name": name,
                "fields": [],
                "relationship_labels": 0,
                "flat": bool(FLAT_GROUPS.match(name)),
            }
            entities.append(current)
        j = 0
        while j < len(texts):
            t = texts[j]
            if (
                j + 1 < len(texts)
                and texts[j + 1] == t
                and t not in REL_LABELS
                and t not in CONTINUATIONS
            ):
                current = {
                    "name": t,
                    "fields": [],
                    "relationship_labels": 0,
                    "flat": bool(FLAT_GROUPS.match(t)),
                }
                entities.append(current)
                j += 2
                continue
            if t in REL_LABELS:
                current["relationship_labels"] += 1  # type: ignore[operator]
            elif (
                re.match(r"[A-Za-z0-9(]", t)
                and re.search(r"[A-Za-z]{2}", t)
                and not re.search(r"[{}\[\]]", t)
            ):
                current["fields"].append(t)  # type: ignore[attr-defined]
            j += 1
    for e in entities:
        e.pop("flat", None)
    return {"source": path.rsplit("/", 1)[-1], "entities": entities}


if __name__ == "__main__":
    data = extract(sys.argv[1])
    with open(sys.argv[2], "w") as f:
        json.dump(data, f, indent=1)
    print(f"{len(data['entities'])} entities")  # type: ignore[arg-type]
