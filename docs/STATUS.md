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
| Emergency access (SEC-04, WF02 step 4) | A clinician with no care relationship states a purpose and gets read-only chart access to one patient for 30 minutes; identifiers masked; orders still refused; one live grant at a time; re-checked at every read, so the first read after expiry is refused; emergency reads audited as such; a privacy alert event per grant; a privacy officer's review queue due within one working day, with overdue flags and no self-review. Step-up authentication is recorded as `not_available` until the production identity provider exists | `tests/e2e/test_emergency_access.py`, `tests/unit/test_emergency_access_rules.py` |
| API-03 vertical slice | Register, admit (with A&E detail), chart read, order, result release and amendment, acknowledgement by owner or backup | `tests/e2e/test_api03_vertical_slice.py` |
| Medicare to NIN | NIN binds; Medicare kept only as previous identifier | same |
| Outbox (DATA-03) | Relay with backoff on broker failure; consumer deduplication | `tests/db_integration/` |
| Database schema | 128 tables from CEDA section 3 and the five ERDs; migrations 0001-0012 apply, reverse and match the models | `alembic check`, migration tests |
| Migration staging (MIG-01 tables) | 66 verbatim `stg_*` tables with lineage; a re-run batch adds zero duplicates | `tests/db_integration/test_integrity.py` |
| Service catalogue (CAT-01..05) | 50 groups, 359 services; provision, activate, retire, search; admissions bound to active services per facility | `tests/e2e/test_service_catalogue.py` |
| Directory coverage | All 281 directory A and 170 directory B listings mapped to a service | `tests/unit/test_service_catalogue.py` |
| Patient index (ICRS module 102) | Search by NIN or by name with optional given name and date of birth (masked identifiers for roles without `identifier:read`); duplicate alerts at registration and a housekeeping list; merge and unmerge by an identity steward, with identifiers moving across and back and the survivor's chart combining merged records, chains included; closure for death, moving away or discharge, singly or in batches, with date and user recorded. ICRS 3.2.8, 3.2.12, 3.2.18-3.2.20, 3.2.33, 3.2.34 | `tests/e2e/test_patient_index.py` |
| Identity review (UG02, WF01 steps 1 and 4, E3, HS02) | Explained near-match search (Soundex names, year-only birth dates, mother's name; a different verified number counts against), masked and audited; near matches at registration open review tasks (registration still goes ahead), which a steward resolves as different people or by merging; a merge keeps the prior names as aliases (removed on unmerge) and identifier copies keep their original author and source; the access check and orders follow merges, and an order stays with its encounter's record | `tests/e2e/test_identity_review.py`, `tests/unit/test_identity_matching.py` |
| ICRS traceability | All 971 numbered requirements of `docs/source/ASTEMIA_CONSULTATION.docx` assigned to modules 101-120 or cross-cutting areas X1-X6; 41 components assigned to modules; delivered requirements name their test. Generated page: [docs/icrs-traceability.md](icrs-traceability.md) | `tests/unit/test_icrs_traceability.py` |
| Operations | CLI (`seed-dev`, `token`, `relay`), Docker image (non-root), Compose stack | `tests/db_integration/test_runtime.py`, CI `container` job |

## Planned, not started

Tables for some of these exist in the schema (created from the ERDs) but no
code reads or writes them yet. They are not features until listed above.

| Area | CEDA reference | Schema present |
|---|---|---|
| Legacy migration loaders and reconciliation | MIG-01 to MIG-03, weeks 17-20 | Yes (`stg_*`, `stg_extract_record`) |
| National returns (APC, Outpatients, A&E, MHMDS) | section 9.3 | Yes (`national_extract_record`) |
| Patient index, rest of ICRS 3.2: demographic amendment and deletion with history (3.2.11), automatic closure of open activity on death (3.2.21), departmental identifier search (3.2.3), letters, external tracing interfaces, address gazetteer | ICRS 3.2, WF01 | Partly |
| ICRS modules 101, 103-120 (see [docs/icrs-traceability.md](icrs-traceability.md)) | ICRS sections 3-6 | Partly |
| Consent, guardians, alternative contacts, addresses, telecoms API | AM-PDI, CD-COV | Yes |
| Scheduling, referral and correspondence | UG01-UG05, weeks 13-16 | No |
| Prescribing, dispensing, administration | HS08, WF04 | No |
| Specimen receipt and rejection | API-04 | No |
| HL7 v2 and FHIR interfaces, terminology | section 6 | No |
| Patient portal, billing, inventory, workforce | HS16-HS18 | Partly (directory) |
| Warehouse, dashboards, intelligence engine | section 9 | No |
| Multilingual patient voice | section 12 | No |
| Production identity provider (OIDC) with MFA and step-up (including for emergency access), KMS, WORM audit storage | section 7-8 | No |
