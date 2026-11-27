# Working on ASTEMIA

## Definition of done (owner's rule, 24 November 2026)

Every piece of work is completed, fully tested and pushed. Nothing is left
half-built. Before reporting work as finished:

1. **Complete:** no stub, placeholder, unused code or schema without the code
   that uses it, unless `docs/STATUS.md` lists it as planned and not started.
2. **Tested:** every new line and branch is exercised by a test against a real
   MySQL 26.10. CI enforces 100% line coverage (`--cov-fail-under=100`).
   `# pragma: no cover` only for a provably unreachable defensive branch, with
   the reason on the same line.
3. **Checked:** all of these pass locally:
   `uv run ruff check src tests tools`, `uv run ruff format --check src tests tools`,
   `uv run mypy`, `uv run pytest --cov=astemia --cov-fail-under=100`,
   `uv run alembic check`.
4. **Pushed:** committed and pushed, and CI is green on GitHub (both the `test`
   and the `container` jobs).
5. **Recorded:** `docs/STATUS.md` updated when something moves from planned to
   complete.

## Ground rules from the specification

- Build from `docs/source/AMS-002_CEDA.docx` (CEDA). Its section 10 fixes the
  stack; section 3 the canonical record; section 11.2 the build sequence.
- Python 3.14, MySQL 26.10 (InnoDB, utf8mb4, strict mode, UTC).
- Naming, with no exceptions: the NHS number and NHS ID become NIN; every
  other NHS becomes Astemia Medical Solutions; GP becomes medical doctor.
  Original ERD labels survive only in `source_label` for lineage.
- `medicare_number` is retired in favour of the NIN.
- Every tenant-owned foreign key includes `tenant_id`. The domain layer has no
  HTTP, database or vendor imports (enforced by a test).
- Migrations are expand-first. Never rewrite a migration that has been pushed;
  add a new one.

## Local database

```bash
docker start astemia-mysql
```

If the Docker daemon is not running in this environment, start it first with
`dockerd > /tmp/dockerd.log 2>&1 &`.
