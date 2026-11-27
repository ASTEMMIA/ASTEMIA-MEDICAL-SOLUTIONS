# Build status

What is complete (built, tested at 100% coverage on MySQL 26.10, pushed, CI
green) and what is planned but not started. Nothing is in between. Plan
references are to AMS-002 CEDA section 11.2.

## Complete

| Area | What works | Evidence |
|---|---|---|
| Platform | FastAPI service, versioned `/v1` API, structured errors with correlation IDs, liveness and readiness (503 when the database is down) | `tests/e2e/test_security_and_errors.py` |
| Identity (API-01) | Bearer tokens verified (signature, issuer, audience, expiry); tenant and roles from active membership only | same |
| Write path (DATA-02, API-02) | Policy, Idempotency-Key with replay and concurrent-race replay, expected version, one transaction for state, audit and outbox | `tests/db_integration/test_runtime.py`, `tests/e2e/test_api03_vertical_slice.py` |
| Access control | Role capabilities, legitimate relationships (direct and workgroup), concealed 404s, identifier masking, sensitive-record withholding, audited denials | `tests/e2e/` |
| API-03 vertical slice | Register, admit (with A&E detail), chart read, order, result release and amendment, acknowledgement by owner or backup | `tests/e2e/test_api03_vertical_slice.py` |
| Medicare to NIN | NIN binds; Medicare kept only as previous identifier | same |
| Outbox (DATA-03) | Relay with backoff on broker failure; consumer deduplication | `tests/db_integration/` |
| Database schema | 128 tables from CEDA section 3 and the five ERDs; migrations 0001-0010 apply, reverse and match the models | `alembic check`, migration tests |
| Migration staging (MIG-01 tables) | 66 verbatim `stg_*` tables with lineage; a re-run batch adds zero duplicates | `tests/db_integration/test_integrity.py` |
| Service catalogue (CAT-01..05) | 50 groups, 359 services; provision, activate, retire, search; admissions bound to active services per facility | `tests/e2e/test_service_catalogue.py` |
| Directory coverage | All 281 directory A and 170 directory B listings mapped to a service | `tests/unit/test_service_catalogue.py` |
| Operations | CLI (`seed-dev`, `token`, `relay`), Docker image (non-root), Compose stack | `tests/db_integration/test_runtime.py`, CI `container` job |

## Planned, not started

Tables for some of these exist in the schema (created from the ERDs) but no
code reads or writes them yet. They are not features until listed above.

| Area | CEDA reference | Schema present |
|---|---|---|
| Legacy migration loaders and reconciliation | MIG-01 to MIG-03, weeks 17-20 | Yes (`stg_*`, `stg_extract_record`) |
| National returns (APC, Outpatients, A&E, MHMDS) | section 9.3 | Yes (`national_extract_record`) |
| Identity stewardship: duplicates, merge and unmerge | WF01, E3 | Yes |
| Consent, guardians, alternative contacts, addresses, telecoms API | AM-PDI, CD-COV | Yes |
| Scheduling, referral and correspondence | UG01-UG05, weeks 13-16 | No |
| Prescribing, dispensing, administration | HS08, WF04 | No |
| Specimen receipt and rejection | API-04 | No |
| HL7 v2 and FHIR interfaces, terminology | section 6 | No |
| Patient portal, billing, inventory, workforce | HS16-HS18 | Partly (directory) |
| Warehouse, dashboards, intelligence engine | section 9 | No |
| Multilingual patient voice | section 12 | No |
| Production identity provider (OIDC), KMS, WORM audit storage | section 7-8 | No |
