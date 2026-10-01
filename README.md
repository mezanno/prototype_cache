# asset-store prototype

Prototype for the `asset-store` module: immutable asset storage, alias registry,
and scoped capability checks for async workers and future IIIF/cache consumers.

## Goal

Define and validate a production-grade design for a deployable, testable, observable storage subsystem before selecting final technologies.

## Current implementation slice

Start with the **[visual architecture and progress overview](docs/OVERVIEW.md)**
for component responsibilities and implementation status. The current milestone is
a [private, single-instance cache pilot](docs/milestones/PRIVATE_CACHE_PILOT.md)
on top of asset-store and fetcher-service.

The prototype includes a FastAPI service, durable Postgres registry, Garage/S3
storage adapter, scoped capabilities, fetcher, bulk-loader, worker simulator and
lifecycle cleanup worker, and an [admin console](docs/services/admin-ui.md) at `/admin`.
In-memory adapters remain available for local tests. Browser acceptance, security
hardening and production readiness remain open;
see the [workplan](docs/WORKPLAN.md) for remaining work.

Run the tests and the API locally (uv-managed env):

```bash
uv run pytest -q
ASSET_STORE_DEV_MODE=1 uv run uvicorn asset_store_core.api:create_app --factory --reload
```

The app is exposed as a factory at `asset_store_core.api:create_app`; the in-memory
backend means it starts with no external dependencies. Development credentials
require the explicit opt-in above. For configured credentials, API authentication
and upload limits, see the [security checkpoint](docs/security/B018_CLOSEOUT.md).

## Running the full test suite

The default run starts no containers. Private-pilot configuration tests require
the Docker Compose CLI (no daemon access); infrastructure-backed tests skip unless their
backend is reachable. The local HTTPS transport tests require the `openssl` CLI
to generate a temporary test certificate.

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

## Local pilot deployment and task workflow

See the short [pilot quickstart](docs/PILOT_QUICKSTART.md) for deployment,
authenticated caching, worker input reads and manifest-last result publication.
The running local pilot supports the current BnF v3 API and mapped legacy
full-image URLs. Task scheduling/processing code remains external.
