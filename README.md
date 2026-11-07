# Collection publishing and Gallica Image proxy pilot

**We have pivoted.** Deliver restricted collection upload/admin/storage, local
IIIF publication usable by Corpusense/current workers, then an Image-only Gallica
proxy/cache. The existing job submission and processing system stays unchanged.
Public reads are accepted for approved published test material; administrative
writes stay restricted. Corpusense fetches Gallica manifests directly and routes
Image API requests through the proxy. Authentication/metering of proxy users is later.

Start with the **[workplan](docs/WORKPLAN.md)**, [active specification](docs/spec/README.md)
and [M-002 release plan](docs/milestones/COLLECTIONS_AND_IMAGE_PROXY_PILOT.md).
[Architecture/status](docs/OVERVIEW.md) distinguishes target services from existing code.

The existing FastAPI asset-store, Postgres/S3 adapters, guards/admin/lifecycle,
fetcher, bulk-loader and worker simulator remain available for selective reuse.
They do not yet implement the new collection service or full IIIF Image serving.
The generic asset-store roadmap is frozen; no storage-provider switch, universal
alias/capability layer or job-engine rewrite is required to ship this pilot.
No code/runtime behavior was changed by the documentation pivot.

## Existing implementation — development commands

The commands below exercise the existing prototype, not completed M-002 services.
See [legacy implementation notes](docs/IMPLEMENTATION_NOTES.md) for its limitations.

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
- Editor context: `.github/instructions/`
- Historical programme/evidence: `docs/history/asset-store/`

## Legacy pilot deployment and task workflow

See the short [pilot quickstart](docs/PILOT_QUICKSTART.md) for the previous deployment contract,
authenticated caching, worker input reads and manifest-last result publication.
Do not assume a running deployment exists on this machine.
The recorded legacy local pilot supports the current BnF v3 API and mapped legacy
full-image URLs. Task scheduling/processing code remains external.
