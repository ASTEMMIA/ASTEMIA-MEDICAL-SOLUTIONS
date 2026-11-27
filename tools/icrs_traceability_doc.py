"""Regenerate the ICRS requirement catalogue and docs/icrs-traceability.md.

uv run python tools/icrs_traceability_doc.py
"""

import json
import pathlib

from astemia import icrs

ROOT = pathlib.Path(__file__).parents[1]


def main() -> None:
    reqs = icrs.extract(ROOT / "docs" / "source" / "ASTEMIA_CONSULTATION.docx")
    data = ROOT / "src" / "astemia" / "icrs" / "data" / "requirements.json"
    data.write_text(json.dumps(reqs, indent=1, ensure_ascii=False) + "\n")
    icrs.requirements.cache_clear()
    out = ROOT / "docs" / "icrs-traceability.md"
    out.write_text(icrs.render_markdown())
    print(f"wrote {data} and {out}")


if __name__ == "__main__":
    main()
