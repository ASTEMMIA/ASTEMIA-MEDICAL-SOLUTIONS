"""Regenerate web/src/api-types.ts from the API's OpenAPI schema.

uv run python tools/web_types.py
"""

import pathlib

from astemia.api.app import create_app
from astemia.api.typescript import render

ROOT = pathlib.Path(__file__).parents[1]


def main() -> None:
    out = ROOT / "web" / "src" / "api-types.ts"
    out.write_text(render(create_app().openapi()))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
