# compose

Local development stack:

| Component | Role |
|-----------|------|
| Object store (Garage) | Buckets: `cache`, `tmp`, `users`, `results` ([`docs/spec/03_ARCHITECTURE.md`](../../docs/spec/03_ARCHITECTURE.md)) |
| Postgres | Registry + audit |
| asset-store | Single FastAPI service (internal `registry` / `capabilities` / `storage` modules, ADR-002) |
| fetcher (optional) | Remote URL ingestion ([`docs/services/fetcher-service.md`](../../docs/services/fetcher-service.md)) |

## Unified dev stack (B-002)

[`docker-compose.yml`](docker-compose.yml) brings up Garage + Postgres + the
`asset-store` FastAPI service (built from [`deploy/Dockerfile`](../Dockerfile))
wired to those backends. The service selects its object-store backend from the
environment via the `create_app_from_env` ASGI factory.

```bash
cd deploy/compose

# 1. Build the service image and start the whole stack.
docker compose up -d --build

# 2. Provision Garage buckets + the fixed DEV key (idempotent; needed once).
./garage-init.sh

# 3. Hit the service (bound to 127.0.0.1:8000).
curl -s http://127.0.0.1:8000/healthz
curl -s http://127.0.0.1:8000/readyz
curl -s http://127.0.0.1:8000/metrics | head

# 4. Stop (named volumes persist).
docker compose down
```

The registry is in-memory in this slice; `ASSET_STORE_PG_DSN` is plumbed into the
service for the durable Postgres-backed registry tracked as B-009. The Garage S3
key/secret in [`docker-compose.yml`](docker-compose.yml) are the same fixed
**DEV-ONLY** values `garage-init.sh` imports.

The single-tier stacks below stay useful for the gated backend test suites.

## Garage dev stack (S-001 / S-004)

A single-node [Garage](https://garagehq.deuxfleurs.fr/) v1.0.1 instance for
exercising the real S3 data path behind the `ObjectStoreBackend` seam
([`S3ObjectStore`](../../src/asset_store_core/s3_object_store.py)).

```bash
cd deploy/compose

# 1. Start Garage (S3 API on :3900, admin on :3903; both bound to 127.0.0.1).
docker compose -f docker-compose.garage.yml up -d

# 2. Provision buckets + a fixed DEV-ONLY key; writes gitignored .env.garage.
#    Idempotent: safe to re-run.
./garage-init.sh

# 3. Export the credentials and run the Garage-gated integration tests.
set -a && source .env.garage && set +a
uv run pytest tests/test_s3_garage_integration.py -q

# 4. Stop (named volumes persist; re-run steps 1–2 to resume instantly).
docker compose -f docker-compose.garage.yml down
```

Without `.env.garage` exported, the integration tests **skip**, so the default
`uv run pytest` run stays Docker-free.

> The credentials in [`garage.toml`](garage/garage.toml) and
> [`garage-init.sh`](garage-init.sh) are **DEV-ONLY** and intentionally
> committed; `.env.garage` is gitignored and real secrets are never committed.

## Postgres dev stack (S-002)

A Postgres 16 instance for the durable registry spike
([`PostgresAssetRegistry`](../../src/asset_store_core/pg_registry.py)).

```bash
cd deploy/compose

# 1. Start Postgres (bound to 127.0.0.1:5432).
docker compose -f docker-compose.postgres.yml up -d

# 2. Point the gated registry tests at it and run them.
export ASSET_STORE_PG_DSN=postgresql://asset:asset@127.0.0.1:5432/asset_store
uv run pytest tests/test_pg_registry.py -q

# 3. Stop (named volume persists).
docker compose -f docker-compose.postgres.yml down
```

The `asset:asset` credentials are **DEV-ONLY**. Without `ASSET_STORE_PG_DSN` the
registry tests **skip**. The registry bootstraps its own tables
(`CREATE TABLE IF NOT EXISTS`) on first connect.
