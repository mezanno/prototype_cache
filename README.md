# asset-store prototype

Prototype for the `asset-store` module: immutable asset storage, alias registry,
and scoped capability checks for async workers and future IIIF/cache consumers.

## Goal

Define and validate a production-grade design for a deployable, testable, observable storage subsystem before selecting final technologies.

## Current implementation slice

The slice is infrastructure-free (in-memory backend; no Postgres or real S3 yet) but
now spans the full request path end to end:

- `src/asset_store_core/` — registry, **four storage buckets** (`cache`, `tmp`,
  `users`, `results`), `partition_id`, object keys `{partition}/assets/{asset_id}`,
  an object-store backend seam (`ObjectStoreBackend` + in-memory `LocalObjectStore`),
  prefix-scoped capabilities, **service→bucket policy** (FR-015), and a `StorageGuard`
  facade composing capability + policy + registry/object-store calls.
- `src/asset_store_core/api/` — a FastAPI app (single process, ADR-002):
  `/healthz`, `/readyz`, `/metrics`, reserve/commit/resolve, capability mint, and a
  capability-guarded data plane (`PUT`/`GET /objects/{alias}`, FR-010..015) using
  `Authorization: Capability <id>` bearer tokens. Errors use RFC 7807
  `application/problem+json`; observability (ADR-013) adds Prometheus metrics,
  structured JSON logs, and an `X-Correlation-Id` per request.
- `tests/` — 72 unit/integration/contract tests, all green.
- `services/`, `tools/`, `deploy/` — placeholders per `docs/WORKPLAN.md`.

Run the tests and the API locally (uv-managed env):

```bash
uv run pytest -q
uv run uvicorn asset_store_core.api:create_app --factory --reload
```

The app is exposed as a factory at `asset_store_core.api:create_app`; the in-memory
backend means it starts with no external dependencies.

## Running the full test suite

The default run is **Docker-free**: infrastructure-backed tests skip unless their
backend is reachable.

```bash
# Lint, type-check, and the fast (in-memory) suite — what CI runs.
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -q
```

Gated suites (opt in by starting the backend and exporting its env):

```bash
# Garage-backed S3 tests (object store + data plane + bulk-loader e2e).
docker compose -f deploy/compose/docker-compose.garage.yml up -d
./deploy/compose/garage-init.sh
set -a && source deploy/compose/.env.garage && set +a
uv run pytest -q                       # now includes the Garage-gated tests
docker compose -f deploy/compose/docker-compose.garage.yml down

# Postgres-backed registry + migration tests.
docker compose -f deploy/compose/docker-compose.postgres.yml up -d
export ASSET_STORE_PG_DSN=postgresql://asset:asset@127.0.0.1:5432/asset_store
uv run pytest -q                       # now includes the Postgres-gated tests
```

With both Garage and Postgres up and their env exported, `uv run pytest -q` runs
the entire suite with nothing skipped.


## Documentation

- Implementation status & design FAQ: `docs/IMPLEMENTATION_NOTES.md`
- Project architecture: `docs/spec/03_ARCHITECTURE.md`
- Spec: `docs/spec/` (glossary at the end of `docs/spec/README.md`)
- Global execution plan: `docs/WORKPLAN.md`
- Agent operating guide: `AGENTS.md`
- Cursor rules for agents: `.cursor/rules/`
