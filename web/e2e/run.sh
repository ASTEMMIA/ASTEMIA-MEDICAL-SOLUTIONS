#!/bin/bash
# Reset a MySQL database, migrate and seed it, serve the API with the built app,
# walk through the app in Chromium, stop.
#   ASTEMIA_E2E_DATABASE_URL=mysql+mysqlconnector://... web/e2e/run.sh
# (from the repository root; needs uv, node, a running MySQL 26.10 and Playwright)
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${ASTEMIA_E2E_DATABASE_URL:?set ASTEMIA_E2E_DATABASE_URL to a database this run may wipe}"
case "$ASTEMIA_E2E_DATABASE_URL" in
  *e2e*) ;;
  *) echo "refusing: the e2e database name must contain 'e2e'" >&2; exit 2 ;;
esac
export ASTEMIA_DATABASE_URL=$ASTEMIA_E2E_DATABASE_URL
WORK=$(mktemp -d)
PORT=${PORT:-8078}

uv run python - <<'PY'
import os
from sqlalchemy import create_engine, inspect, text
engine = create_engine(os.environ["ASTEMIA_DATABASE_URL"])
with engine.begin() as c:
    c.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    for table in inspect(c).get_table_names():
        c.execute(text(f"DROP TABLE `{table}`"))
    c.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
PY
uv run alembic upgrade head >/dev/null
uv run astemia seed-dev >/dev/null
(cd web && npx vite build >/dev/null)

ASTEMIA_ENVIRONMENT=development ASTEMIA_DEV_SIGN_IN=true ASTEMIA_WEB_DIR=web/dist \
  uv run uvicorn astemia.api.main:app --port "$PORT" > "$WORK/server.log" 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
for _ in $(seq 60); do curl -sf "http://127.0.0.1:$PORT/app/" >/dev/null && break; sleep 0.5; done

for suite in web/e2e/*.e2e.mjs; do
  name=$(basename "$suite" .e2e.mjs)
  BASE=http://127.0.0.1:$PORT SHOTS=${SHOTS:+$SHOTS/$name} node "$suite" || { tail -40 "$WORK/server.log"; exit 1; }
done
