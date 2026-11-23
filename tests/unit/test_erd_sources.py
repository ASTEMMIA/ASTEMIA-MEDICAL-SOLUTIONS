"""The stored ERD originals and the committed extractions must agree."""

import importlib.util
import json
import pathlib

import pytest

pytest.importorskip("olefile")
ROOT = pathlib.Path(__file__).parents[2]
_spec = importlib.util.spec_from_file_location(
    "extract_vsdx_erd", ROOT / "tools" / "extract_vsdx_erd.py"
)
assert _spec and _spec.loader
erd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(erd)

SOURCES = {
    "AMS_MASTER_SCHEMA_WIP_ERP.vsdx": "ams_master_schema_wip_erp.json",
    "ZETTER_AMS_SCHEMA_ERD.vsdx": "zetter_ams_erd.json",
    "PDi_AMS_SCHEMA_ERP.vsdx": "pdi_ams_schema_erp.json",
    "AHIS_MASTER_ERD.vsdx": "ahis_master_erd.json",
    "AE_AMS_SCHEMA_ERD.vsdx": "ae_ams_erd.json",
}


@pytest.mark.parametrize(("vsdx", "extracted"), SOURCES.items())
def test_committed_extraction_matches_the_stored_erd(vsdx: str, extracted: str) -> None:
    fresh = erd.extract(str(ROOT / "docs" / "source" / "erd" / vsdx))["entities"]
    committed = json.loads(
        (ROOT / "src" / "astemia" / "adapters" / "db" / "erd" / extracted).read_text()
    )["entities"]
    assert fresh == committed, f"re-run tools/extract_vsdx_erd.py for {vsdx}"


def test_every_committed_extraction_has_its_source() -> None:
    committed = {
        p.name for p in (ROOT / "src" / "astemia" / "adapters" / "db" / "erd").glob("*.json")
    }
    assert committed == set(SOURCES.values())
