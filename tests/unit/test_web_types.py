"""The web app's TypeScript types match the API (tools/web_types.py)."""

import pathlib

from astemia.api.app import create_app
from astemia.api.typescript import render, ts_type

ROOT = pathlib.Path(__file__).parents[2]


def test_the_web_app_types_are_current() -> None:
    generated = render(create_app().openapi())
    assert (ROOT / "web" / "src" / "api-types.ts").read_text() == generated, (
        "regenerate with: uv run python tools/web_types.py"
    )


def test_each_schema_construct() -> None:
    assert ts_type({"$ref": "#/components/schemas/PatientOut"}) == "PatientOut"
    assert ts_type({"anyOf": [{"type": "string"}, {"type": "string"}, {"type": "null"}]}) == (
        "string | null"
    )
    assert ts_type({"const": "home"}) == '"home"'
    assert ts_type({"enum": ["a", 1, True]}) == '"a" | 1 | true'
    assert ts_type({"type": "array", "items": {"type": "integer"}}) == "number[]"
    assert ts_type(
        {"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "null"}]}}
    ) == ("(string | null)[]")
    assert ts_type({"type": "object", "additionalProperties": True}) == "Record<string, unknown>"
    assert ts_type({"type": "string", "format": "date"}) == "string"
    assert ts_type({}) == "unknown"
    obj = ts_type(
        {
            "type": "object",
            "properties": {"a": {"type": "boolean", "description": "Yes or no"}, "b": {}},
            "required": ["a"],
        }
    )
    assert obj == "{\n  /** Yes or no */\n  a: boolean;\n  b?: unknown;\n}"


def test_described_schemas_keep_their_description() -> None:
    spec = {"components": {"schemas": {"X": {"type": "object", "description": "An\n  x."}}}}
    assert "/** An x. */\nexport type X = Record<string, unknown>;" in render(spec)
