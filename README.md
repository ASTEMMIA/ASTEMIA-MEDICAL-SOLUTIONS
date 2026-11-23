# ASTEMIA Intelligence Health Platform

Reference implementation of **AMS-002 Canonical Enterprise Data Architecture
(CEDA)**: one Python codebase organised by subject area, on **MySQL 26.10**
(InnoDB, utf8mb4, strict SQL mode, UTC). The database schema is built from
CEDA section 3 and the five AMS ERDs. See
[docs/erd-schema-mapping.md](docs/erd-schema-mapping.md).

## Stack (CEDA 10.1)

| Concern | Choice |
|---|---|
| Runtime | CPython 3.14 (exact patch fixed at platform qualification) |
| API | FastAPI, versioned under `/v1` |
| Validation | Pydantic for every input and output |
| Persistence | SQLAlchemy 2.1 + MySQL Connector/Python 26.10, Alembic migrations |
| Database | MySQL 26.10 |
| Messaging | Transactional outbox + relay; consumers deduplicate by event ID |
| Quality gates | Ruff, mypy (strict), pytest on a real MySQL, `alembic check` schema diff |

## Layout (CEDA 10.2)

```
src/astemia/
  domain/        pure state transitions and invariants (no HTTP, DB or vendor imports; enforced by a test)
  application/   commands, queries, access policy, the write path
  adapters/db/   SQLAlchemy models, types, ERD-generated staging, extracted ERDs (erd/*.json)
  adapters/identity/  token verification and tenant membership (API-01)
  adapters/broker/    broker port
  api/           FastAPI app and error mapping
  workers/       outbox relay
  migrations/    Alembic (expand, backfill, verify, contract)
tools/           ERD extractor and inventory generator
tests/           unit, db_integration, e2e (synthetic fixtures only)
```

## What is built

* **Schema:** 119 tables with 159 foreign keys, each including `tenant_id`.
  That is 53 canonical and platform tables and 66 verbatim staging tables. A
  national-extract dictionary holds 1,708 fields across 8 extracts.
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
  | `POST /v1/diagnostic-reports` | Release a result. A second release is an amendment that reopens exactly one review |
  | `POST /v1/result-reviews/{id}/acknowledge` | Acknowledge a result. Needs `If-Match` |

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
