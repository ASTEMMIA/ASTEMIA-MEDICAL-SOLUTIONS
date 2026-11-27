"""Extract the entity/field catalogue from a Visio database-model (.vsdx) file.

Visio's Database Modeling engine keeps the full model, including entities that
are not drawn on the page, in an embedded OLE store
(VisDBEngrData/VisDBEngrModelEngData/MAPInfo). Names there are MFC CStrings:
the marker FF FE FF, a length, then UTF-16LE text. The bytes that follow each
string say what kind of record it is:

    entity  <name> 01 FF FE FF 00 00 FF FE FF <len> <name again>
    field   <name> 01 FF FE FF 00 00 00 00 <key>    (<key> 01 = primary-key column)

Every field belongs to the entity record before it. Classifying records by
these tags, rather than by the text, means nothing is maintained by hand: a
field that legitimately appears twice in a national extract (two records) is
never mistaken for an entity, and nested sub-model entities are found wherever
they sit. Usage:

    uv run --group tools python tools/extract_vsdx_erd.py ERD.vsdx out.json
"""

import io
import json
import sys
import zipfile
from collections.abc import Iterator

import olefile

STREAM = "VisDBEngrData/VisDBEngrModelEngData/MAPInfo"
CSTRING = b"\xff\xfe\xff"
ENTITY_TAG = b"\x01" + CSTRING + b"\x00\x00" + CSTRING
FIELD_TAG = b"\x01" + CSTRING + b"\x00\x00\x00\x00"


def cstrings(blob: bytes) -> Iterator[tuple[int, int, str]]:
    """Yield (start, end, text) for every UTF-16 CString in the stream."""
    i = blob.find(CSTRING)
    while i != -1:
        p = i + 3
        if p < len(blob):
            n = blob[p]
            p += 1
            if n == 0xFF and p + 2 <= len(blob):  # long string: 16-bit length
                n = int.from_bytes(blob[p : p + 2], "little")
                p += 2
            end = p + 2 * n
            if n and end <= len(blob):
                try:
                    text: str | None = blob[p:end].decode("utf-16le")
                except UnicodeDecodeError:
                    text = None  # not a string record
                if text is not None:
                    yield i, end, text
        i = blob.find(CSTRING, i + 1)


def classify(blob: bytes, end: int, text: str) -> str | None:
    if blob[end : end + len(ENTITY_TAG)] == ENTITY_TAG:
        # The physical name repeats the logical one for every entity.
        n = len(text)
        at = end + len(ENTITY_TAG)
        if blob[at] == n and blob[at + 1 : at + 1 + 2 * n].decode("utf-16le", "replace") == text:
            return "entity"
    if blob[end : end + len(FIELD_TAG)] == FIELD_TAG:
        flag = blob[end + len(FIELD_TAG)]
        if flag in (0, 1):
            return "key" if flag else "field"
    return None


def extract(path: str) -> dict[str, object]:
    with zipfile.ZipFile(path) as z:
        ole_name = next(n for n in z.namelist() if n.startswith("visio/embeddings/oleObject"))
        ole = olefile.OleFileIO(io.BytesIO(z.read(ole_name)))
    blob = ole.openstream(STREAM).read()
    entities: list[dict[str, object]] = []
    skip_until = -1
    for start, end, text in cstrings(blob):
        if start < skip_until:
            continue  # the repeated physical name of the entity just read
        kind = classify(blob, end, text)
        if kind == "entity":
            entities.append({"name": text.strip(), "fields": [], "primary_key": []})
            skip_until = end + len(ENTITY_TAG) + 1 + 2 * len(text)
        elif kind in ("field", "key") and entities:
            entities[-1]["fields"].append(text.strip())  # type: ignore[attr-defined]
            if kind == "key":
                entities[-1]["primary_key"].append(text.strip())  # type: ignore[attr-defined]
    return {"source": path.rsplit("/", 1)[-1], "entities": entities}


if __name__ == "__main__":
    data = extract(sys.argv[1])
    with open(sys.argv[2], "w") as f:
        json.dump(data, f, indent=1)
    print(f"{len(data['entities'])} entities")  # type: ignore[arg-type]
