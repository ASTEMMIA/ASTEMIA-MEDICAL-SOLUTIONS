# Build once, promote the same digest (CEDA 10.1). Pin the base by digest at
# platform qualification.
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
RUN npx tsc -p . && npx vite build

FROM python:3.14-slim AS build
RUN pip install --no-cache-dir "uv==0.11.32"
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

FROM python:3.14-slim
RUN useradd --system --uid 10001 astemia
WORKDIR /app
COPY --from=build --chown=astemia /app /app
COPY --from=web --chown=astemia /web/dist /app/web
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 ASTEMIA_WEB_DIR=/app/web
USER astemia
EXPOSE 8000
CMD ["uvicorn", "astemia.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
