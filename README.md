# asset-store prototype

Prototype for the `asset-store` module: immutable asset storage, alias registry,
and scoped capability checks for async workers and future IIIF/cache consumers.

## Goal

Define and validate a production-grade design for a deployable, testable, observable storage subsystem before selecting final technologies.

## Current implementation slice

Start with the **[visual architecture and progress overview](docs/OVERVIEW.md)**
for component responsibilities, implementation status and the next milestone.

The prototype includes a FastAPI service, durable Postgres registry, Garage/S3
storage adapter, scoped capabilities, fetcher, bulk-loader, worker simulator and
lifecycle cleanup worker. In-memory adapters remain available for local tests.
Admin tooling, security hardening and production readiness remain open;
see the [workplan](docs/WORKPLAN.md) for remaining work.

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
