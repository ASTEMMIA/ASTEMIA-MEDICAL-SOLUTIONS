"""The ERD extractor classifies records by their binary tags, not by text."""

import importlib.util
import pathlib

import pytest

pytest.importorskip("olefile")
_spec = importlib.util.spec_from_file_location(
    "extract_vsdx_erd", pathlib.Path(__file__).parents[2] / "tools" / "extract_vsdx_erd.py"
)
assert _spec and _spec.loader
erd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(erd)


def cs(text: str) -> bytes:
    return erd.CSTRING + bytes([len(text)]) + text.encode("utf-16le")


def entity(name: str) -> bytes:
    return cs(name) + b"\x01" + erd.CSTRING + b"\x00\x00" + cs(name)


def field(name: str, key: bool = False) -> bytes:
    return cs(name) + b"\x01" + erd.CSTRING + b"\x00\x00\x00\x00" + (b"\x01" if key else b"\x00")


def parse(blob: bytes) -> list[tuple[str, list[str], list[str]]]:
    out: list[tuple[str, list[str], list[str]]] = []
    skip = -1
    for start, end, text in erd.cstrings(blob):
        if start < skip:
            continue
        kind = erd.classify(blob, end, text)
        if kind == "entity":
            out.append((text, [], []))
            skip = end + len(erd.ENTITY_TAG) + 1 + 2 * len(text)
        elif kind in ("field", "key"):
            out[-1][1].append(text)
            if kind == "key":
                out[-1][2].append(text)
    return out


def test_a_field_repeated_back_to_back_stays_a_field() -> None:
    """The case that used to need a hand-kept list: an extract with a field
    that legitimately appears twice in a row."""
    blob = (
        entity("ADMITTED PATIENT CARE")
        + field("Contract serial no")
        + field("Contract serial no")
        + field("Contract line number")
    )
    assert parse(blob) == [
        (
            "ADMITTED PATIENT CARE",
            ["Contract serial no", "Contract serial no", "Contract line number"],
            [],
        )
    ]


def test_nested_entities_split_and_keys_are_flagged() -> None:
    blob = (
        entity("Party")
        + field("Person ID", key=True)
        + entity("Organisation")
        + field("Organisation ID")
    )
    assert parse(blob) == [
        ("Party", ["Person ID"], ["Person ID"]),
        ("Organisation", ["Organisation ID"], []),
    ]


def test_non_ascii_labels_and_unrelated_strings() -> None:
    blob = entity("AE") + field("A+E Diagnosis \u2013 Second") + cs("has") + cs("}{ywusq")
    assert parse(blob) == [("AE", ["A+E Diagnosis \u2013 Second"], [])]
