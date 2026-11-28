# ASTEMIA Intelligence Health Platform

Reference implementation of **AMS-002 Canonical Enterprise Data Architecture
(CEDA)**: one Python codebase organised by subject area, on **MySQL 26.10**
(InnoDB, utf8mb4, strict SQL mode, UTC). The database schema is built from
CEDA section 3 and the five AMS ERDs. See
[docs/erd-schema-mapping.md](docs/erd-schema-mapping.md).

The source documents (the CEDA document and the five Visio ERDs) are stored
in [docs/source](docs/source). A test fails if an ERD and its committed
extraction disagree.

## Stack (CEDA 10.1)

| Concern | Choice |
|---|---|
| Runtime | CPython 3.14 (exact patch fixed at platform qualification) |
| API | FastAPI, versioned under `/v1` |
| Validation | Pydantic for every input and output |
| Persistence | SQLAlchemy 2.1 + MySQL Connector/Python 26.10, Alembic migrations |
| Database | MySQL 26.10 |
| Messaging | Transactional outbox + relay; consumers deduplicate by event ID |
| Staff web app | React 19, React Router, Vite, TypeScript (strict), served by the API at `/app/` |
| Quality gates | Ruff, mypy (strict), pytest on a real MySQL, `alembic check` schema diff; for the web app tsc, Vitest, and Playwright with axe-core against the real API |

## Layout (CEDA 10.2)

```
src/astemia/
  domain/        pure state transitions and invariants (no HTTP, DB or vendor imports; enforced by a test)
  application/   commands, queries, access policy, the write path
  adapters/db/   SQLAlchemy models, types, ERD-generated staging, extracted ERDs (erd/*.json)
  adapters/identity/  token verification and tenant membership (API-01)
  adapters/broker/    broker port
  api/           FastAPI app and error mapping
  workers/       outbox relay, Daybook reminders
web/             staff web app (src/ screens and API client, e2e/ browser checks)
  migrations/    Alembic (expand, backfill, verify, contract)
tools/           ERD extractor and inventory generator
tests/           unit, db_integration, e2e (synthetic fixtures only)
```

## What is built

* **Schema:** 128 tables with 173 foreign keys. Every foreign key between tenant-owned tables includes `tenant_id`.
  That is 62 canonical, catalogue and platform tables and 66 verbatim staging tables. A
  national-extract dictionary holds 1,705 fields across 8 extracts.
* **Write path** (CEDA 10.3): identity, then policy, then Idempotency-Key,
  then expected version, then domain transition. State, revision, audit and
  outbox are committed in one transaction.
* **API-03 vertical slice:**

  | Endpoint | Purpose |
  |---|---|
  | `POST /v1/patients` | Register a patient |
  | `POST /v1/encounters` | Admit, with optional A&E detail |
  | `GET /v1/patients/{id}/chart` | Read the chart: masked, audited before return, concealed 404 without a legitimate relationship |
  | `POST /v1/orders` | Place an order |
  | `POST /v1/slots` | Create a run of slots for a clinician, service and site (scheduler) |
  | `GET /v1/slots` | Search by `facility_id`, `service`, `practitioner_id`, `slot_type`, `from`, `to`; `available_only=true` |
  | `POST /v1/slots/{id}/hold` | Hold a slot for 5 minutes; returns the hold token |
  | `POST /v1/appointments` | Book with a live hold, optionally against an accepted referral |
  | `POST /v1/appointments/{id}/reschedule` | Move to a newly held slot; the original stands if that fails. Needs `If-Match` |
  | `POST /v1/appointments/{id}/cancel` | Cancel and free the slot. Needs `If-Match` |
  | `POST /v1/appointments/{id}/attendance` | Attended (opens the visit), no-show or failed connection. Needs `If-Match` |
  | `POST /v1/referrals` | Refer a patient from one facility to another. The patient's historical records are attached automatically; refused when there are none |
  | `GET /v1/referrals/{id}/records` | The historical records that came with a referral, for the receiving triage team and the referrer, masked and audited |
  | `GET /v1/referrals` | Triage worklist by `status` and `receiving_service`, urgent first (scheduler) |
  | `POST /v1/referrals/{id}/decision` | Accept, or reject with a reason. Needs `If-Match` |
  | `POST /v1/encounters/{id}/entries` | Draft a clinical note on an encounter |
  | `GET /v1/entries/{id}` | A note with its signed revisions (and your own draft) |
  | `POST /v1/entries/{id}/draft` | Edit your draft. Needs `If-Match` |
  | `POST /v1/entries/{id}/sign` | Sign your draft; it can never change after this. Needs `If-Match` |
  | `POST /v1/entries/{id}/amendments` | Start a correction: a new revision that references the signed one. Needs `If-Match` |
  | `POST /v1/documents` | Receive inbound correspondence (base64 content); quarantined, checked and matched (records clerk) |
  | `GET /v1/documents` | Records clerk worklist by `status` (quarantined by default) |
  | `GET /v1/documents/{id}` | A document with its versions (and match candidates while quarantined) |
  | `GET /v1/documents/{id}/content` | The original bytes; never for a file that failed its checks |
  | `POST /v1/documents/{id}/file` | File to a patient and route to a reviewer; `adjudication` needed for an ambiguous match. Needs `If-Match` |
  | `POST /v1/documents/{id}/reindex` | Correct the indexing; the original digest is kept. Needs `If-Match` |
  | `POST /v1/documents/{id}/review` | The named reviewer signs the document off. Needs `If-Match` |
  | `POST /v1/encounters/{id}/discharge-summary` | Draft or redraft the discharge summary (`If-Match` when redrafting) |
  | `POST /v1/encounters/{id}/discharge` | Sign off the discharge: summary signed, encounter finished, an owned task for every outstanding item. Needs `If-Match` (encounter version) |
  | `POST /v1/patients/{id}/conditions` | Record a coded condition, optionally on a condition register |
  | `POST /v1/care-plans` | Create a care plan with its first revision and scheduled sessions |
  | `GET /v1/care-plans/{id}` | A plan with its revisions and sessions |
  | `POST /v1/care-plans/{id}/revisions` | Revise from an effective time; later sessions are rescheduled, completed ones keep their revision. Needs `If-Match` |
  | `POST /v1/care-plans/{id}/discontinue` | End the plan and its remaining sessions. Needs `If-Match` |
  | `POST /v1/plan-cycles/{id}/complete` | Record a delivered session. Needs `If-Match` |
  | `POST /v1/plan-cycles/{id}/release` | The plan owner resolves a held clash. Needs `If-Match` |
  | `POST /v1/tasks` | Create a Daybook task for a named owner or a queue (a role) |
  | `GET /v1/tasks` | `view=mine` (mine and my queues) or `view=all` (team supervisor), earliest due first |
  | `POST /v1/tasks/{id}/acknowledge` | Acknowledge; claims a queue task. Needs `If-Match` |
  | `POST /v1/tasks/{id}/complete` | Complete, recording who and when. Needs `If-Match` |
  | `POST /v1/tasks/{id}/cancel` | Cancel with a reason. Needs `If-Match` |
  | `POST /v1/tasks/{id}/reassign` | Reassign; the deadline does not move. Needs `If-Match` |
  | `POST /v1/restrictive-interventions` | Log a restraint, seclusion or rapid tranquillisation (care team) |
  | `POST /v1/restrictive-interventions/{id}/end` | Record the end time, debrief and any injury, once. Needs `If-Match` |
  | `GET /v1/restrictive-interventions` | Review queue, oldest deadline first; `reviewed=true` for the history (safeguarding lead) |
  | `POST /v1/restrictive-interventions/{id}/review` | Independent review by a lead who took no part. Needs `If-Match` |
  | `GET /v1/patients/{id}/restrictive-interventions` | The patient's log (care team, safeguarding lead, appointed advocate) |
  | `POST /v1/patients/{id}/legal-status` | Record a new legal status; the previous one ends |
  | `GET /v1/patients/{id}/legal-status` | Legal status history, newest first |
  | `GET /v1/legal-status/expiring` | Compulsory powers expiring within 72 hours or lapsed (safeguarding lead) |
  | `POST /v1/safeguarding-concerns` | Raise a concern for a patient, family member, advocate or staff |
  | `GET /v1/safeguarding-concerns` | Concerns by `status`, earliest deadline first (safeguarding lead) |
  | `POST /v1/safeguarding-concerns/{id}/outcome` | Upheld or not upheld, by a lead who is not its subject. Needs `If-Match` |
  | `POST /v1/patients/{id}/advocates` | Appoint an independent advocate to a patient (safeguarding lead) |
  | `GET /v1/patients/{id}/access-report` | Everyone who read or changed the record, flagged (safeguarding lead or the patient's advocate) |
  | `POST /v1/emergency-grants` | Emergency access: state a purpose, get read-only chart access to one patient for 30 minutes (clinician) |
  | `GET /v1/emergency-grants` | Privacy review queue, oldest deadline first; `reviewed=true` for the history (privacy officer) |
  | `POST /v1/emergency-grants/{id}/review` | Record whether the access was appropriate. Needs `If-Match` |
  | `POST /v1/diagnostic-reports` | Release a result. A second release is an amendment that reopens exactly one review |
  | `POST /v1/result-reviews/{id}/acknowledge` | Acknowledge a result. Needs `If-Match` |

* **Patient index** (ICRS module 102). Registration also returns
  `possible_duplicates`, an alert that never blocks:

  | Endpoint | Purpose |
  |---|---|
  | `GET /v1/patient-index` | Search by `nin`, or by `family_name` (prefix) with optional `given_name` and `birth_date` |
  | `GET /v1/patient-index/duplicates` | Housekeeping list of probable duplicates (identity steward) |
  | `POST /v1/patient-index/match` | Scored, explained near-match search before registering (demographics in the body), masked and audited |
  | `GET /v1/identity-review-tasks` | Open (or, with `resolved=true`, closed) identity review tasks (identity steward) |
  | `POST /v1/identity-review-tasks/{id}/resolve` | Record that a pair are different people. Needs `If-Match`; a merge resolves the pair's task itself |
  | `POST /v1/patients/{id}/merge` | Merge this record into `survivor_id`. Needs `If-Match` |
  | `POST /v1/merge-links/{id}/unmerge` | Reverse a merge |
  | `POST /v1/patients/{id}/close` | Close for death, moving away or discharge. Needs `If-Match` |
  | `POST /v1/patient-index/closures` | Close a batch, for example death registrations; reports each item |

## Integrated Care Records Service build

The owner's scope is modules 101 to 120 of the Integrated Care Records Service
specification (`docs/source/ASTEMIA_CONSULTATION.docx`) and the components
listed with them. [docs/icrs-traceability.md](docs/icrs-traceability.md) shows,
per module, how many of the 971 numbered requirements it owns and how many are
delivered, each with the test that proves it.

## Hospital service catalogue

50 department groups and 359 services. The full list, with both directory
crosswalks, is in [docs/service-catalogue.md](docs/service-catalogue.md).

Both directories are the services A to Z of the Astemia Medical Solutions for
Integrated Care Records Service:

* **Directory A:** all 281 listings map to a specific service. D01-D36 follow
  AMS-002 Annex A15.
* **Directory B:** all 170 listings map to a specific service (two listings were
  removed on 27 November 2026). That includes non-clinical listings such as chaplaincy,
  interpreting, patient transport and visitor amenities, which go to D50
  Patient, family and visitor support.
* **D37-D50 ASTEMIA extensions,** confirmed in pilot scope on 23 November
  2026. Each service is still activated per facility with a named owner and
  an approval reference (CAT-05):
  * ENT and audiology
  * burns and plastics
  * mental health and addiction
  * tropical and communicable diseases (malaria, TB, Lassa fever)
  * child nutrition
  * clinical genetics
  * radiotherapy
  * pre-hospital EMS
  * mortuary and medico-legal
  * occupational health
  * blood donor services
  * orthotics and prosthetics
  * virtual wards
  * patient, family and visitor support

Tests fail if any directory listing is unmapped. Listing names such as
"The Havens", "SACU", "T1DE" and "WestMARC" become search aliases.

Tenants provision the catalogue as drafts and activate services per facility
with a named owner, an approval reference and a work queue (CAT-01/05).
Admissions must name an active service offered at that facility, and unknown
or retired codes are refused (CAT-03/04).

| Endpoint | Purpose |
|---|---|
| `POST /v1/control/catalogue/provision` | Instantiate the catalogue as drafts (tenant admin) |
| `POST /v1/control/services/{id}/activate` | Activate a service at a facility. Needs `If-Match` |
| `POST /v1/control/services/{id}/retire` | Retire a service. Needs `If-Match` |
| `GET /v1/services` | Search by name or alias, with `facility_id`, `age` and `care_setting` filters |

## Run it

Start MySQL 26.10, migrate, and serve:

```bash
docker compose up --build
```

Or run against a local MySQL 26.10:

```bash
uv sync --all-groups
```

```bash
uv run alembic upgrade head
```

```bash
uv run astemia seed-dev
```

```bash
uv run uvicorn astemia.api.main:app --reload
```

```bash
uv run astemia token clinician@pilot.astemia.local
```

To use the staff web app, build it and let the API serve it with development
sign-in (never available when `ASTEMIA_ENVIRONMENT=production`):

```bash
(cd web && npm ci && npx vite build)
```

```bash
ASTEMIA_WEB_DIR=web/dist ASTEMIA_DEV_SIGN_IN=true uv run uvicorn astemia.api.main:app
```

Then open http://127.0.0.1:8000/app/ and pick a seeded account. While working
on the screens, `cd web && npm run dev` serves them with hot reload on port
5173 and forwards `/v1` to the API.

`ASTEMIA_DATABASE_URL` selects the database
(`mysql+mysqlconnector://user:pass@host:3306/astemia`). Development tokens
use HS256 with `ASTEMIA_JWT_KEY` and are refused when
`ASTEMIA_ENVIRONMENT=production`.

## Test

The tests need a MySQL 26.10 database (default
`mysql+mysqlconnector://astemia:astemia@127.0.0.1:3306/astemia_test`, or set
`ASTEMIA_TEST_DATABASE_URL`):

```bash
uv run pytest
```

```bash
uv run ruff check src tests tools && uv run mypy && uv run alembic check
```

The web app's TypeScript types are generated from the API's OpenAPI schema; a
test fails when they are stale. After changing a Pydantic model:

```bash
uv run python tools/web_types.py
```

The web app's types, unit tests and build:

```bash
cd web && npx tsc -p . && npx vitest run && npx vite build
```

The browser checks wipe and seed their own database, whose name must contain
`e2e`, then drive every seeded role through the app in Chromium with axe-core
accessibility scans:

```bash
ASTEMIA_E2E_DATABASE_URL=mysql+mysqlconnector://astemia:astemia@127.0.0.1:3306/astemia_e2e web/e2e/run.sh
```

## Regenerating the schema from an ERD

```bash
uv run python tools/extract_vsdx_erd.py path/to/ERD.vsdx src/astemia/adapters/db/erd/<name>.json
```

```bash
uv run python tools/erd_inventory.py
```

```bash
uv run alembic revision --autogenerate -m "describe the change"
```

Review the generated migration before committing it. Migrations must be
expand-only within a release (CEDA 11.3).
