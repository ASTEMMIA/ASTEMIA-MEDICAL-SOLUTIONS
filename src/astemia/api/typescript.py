"""TypeScript types for the staff web app, generated from the API's OpenAPI
schema so the screens and the API cannot drift apart (checked by a test).

uv run python tools/web_types.py
"""

from typing import Any

HEADER = (
    "// Generated from the API's OpenAPI schema by tools/web_types.py. Do not edit:\n"
    "// change the Pydantic models and regenerate.\n"
)
SCALARS = {"string": "string", "integer": "number", "number": "number", "boolean": "boolean"}


def ts_type(schema: dict[str, Any]) -> str:
    """The TypeScript type for one JSON Schema, as FastAPI writes them."""
    if "$ref" in schema:
        return str(schema["$ref"]).rsplit("/", 1)[-1]
    if "anyOf" in schema:
        return " | ".join(dict.fromkeys(ts_type(s) for s in schema["anyOf"]))
    if "const" in schema:
        return _literal(schema["const"])
    if "enum" in schema:
        return " | ".join(_literal(v) for v in schema["enum"])
    kind = schema.get("type")
    if kind == "null":
        return "null"
    if kind == "array":
        inner = ts_type(schema.get("items", {}))
        return f"({inner})[]" if " " in inner else f"{inner}[]"
    if kind == "object" or "properties" in schema:
        if "properties" in schema:
            return _object(schema)
        return "Record<string, unknown>"
    if isinstance(kind, str) and kind in SCALARS:
        return SCALARS[kind]
    return "unknown"


def _literal(value: Any) -> str:
    return f'"{value}"' if isinstance(value, str) else str(value).lower()


def _object(schema: dict[str, Any], indent: str = "") -> str:
    required = set(schema.get("required", []))
    lines = ["{"]
    for name, prop in schema["properties"].items():
        if "description" in prop:
            lines.append(f"{indent}  /** {prop['description']} */")
        optional = "" if name in required else "?"
        lines.append(f"{indent}  {name}{optional}: {ts_type(prop)};")
    lines.append(f"{indent}}}")
    return "\n".join(lines)


def render(spec: dict[str, Any]) -> str:
    """Every component schema as an exported TypeScript type, sorted by name."""
    out = [HEADER]
    for name in sorted(spec["components"]["schemas"]):
        schema = spec["components"]["schemas"][name]
        doc = schema.get("description")
        if doc:
            out.append("/** " + " ".join(str(doc).split()) + " */")
        out.append(f"export type {name} = {ts_type(schema)};\n")
    return "\n".join(out)
