# Source documents

The originals this codebase is built from. Change them here, then regenerate
what is derived from them.

| File | What it is | Derived in the code |
|---|---|---|
| `AMS-002_CEDA.docx` | AMS-002 Canonical Enterprise Data Architecture, with the ASTEMIA Health SaaS Functional Specification v1.2 merged in as Annex A. Revision 1.1 (27 November 2026) adds section 14, build status and decisions; revision 1.2 (27 November 2026) applies the Astemia Medical Solutions naming rule and records how the build applies it; revision 1.3 (27 November 2026) names the two services A to Z directories A and B of the Astemia Medical Solutions for Integrated Care Records Service; revision 1.4 (27 November 2026) removes two directory B listings, leaving 170; revision 1.5 (27 November 2026) makes the patient's historical records mandatory on every referral, from a primary health centre or any provider to a general, teaching or specialist hospital, refuses a referral for a patient with no care records (HS05), and updates the build status; revision 1.6 (27 November 2026) adds mental health safeguards against the abuse of patients: restrictive practice logged and independently reviewed, legal status with history and expiry, independent handling of concerns, and access reports (HS13); revision 1.7 (27 November 2026) records the weeks 13 to 16 backend as built: signed clinical notes, correspondence, Daybook tasks, discharge and care plans | Architecture, write path, API-03 slice, service catalogue D01-D36 (Annex A15-A16) |
| `ASTEMIA_CONSULTATION.docx` | Integrated Care Records Service output-based specification (971 numbered requirements), as supplied on 27 November 2026 | `src/astemia/icrs/data/requirements.json` (GP becomes medical doctor in the extracted text); module plan in `src/astemia/icrs/data/modules.json`; [docs/icrs-traceability.md](../icrs-traceability.md) |
| `erd/AMS_MASTER_SCHEMA_WIP_ERP.vsdx` | AMS master schema ERD | `src/astemia/adapters/db/erd/ams_master_schema_wip_erp.json` |
| `erd/ZETTER_AMS_SCHEMA_ERD.vsdx` | ZETTER AMS schema ERD | `.../erd/zetter_ams_erd.json` |
| `erd/PDi_AMS_SCHEMA_ERP.vsdx` | Patient demographics (PDi) schema ERD | `.../erd/pdi_ams_schema_erp.json` |
| `erd/AHIS_MASTER_ERD.vsdx` | AHIS master ERD | `.../erd/ahis_master_erd.json` |
| `erd/AE_AMS_SCHEMA_ERD.vsdx` | A&E AMS schema ERD | `.../erd/ae_ams_erd.json` |

`tests/unit/test_erd_sources.py` re-extracts every ERD here and fails if the
committed JSON no longer matches. After editing an ERD, regenerate its JSON:

```bash
uv run python tools/extract_vsdx_erd.py docs/source/erd/AHIS_MASTER_ERD.vsdx src/astemia/adapters/db/erd/ahis_master_erd.json
```

After changing `ASTEMIA_CONSULTATION.docx` or the module plan, regenerate the
requirement catalogue and the traceability page
(`tests/unit/test_icrs_traceability.py` fails until you do):

```bash
uv run python tools/icrs_traceability_doc.py
```

Then regenerate the inventory and create a migration for the schema change:

```bash
uv run python tools/erd_inventory.py
```

```bash
uv run alembic revision --autogenerate -m "describe the ERD change"
```
