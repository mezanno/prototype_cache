# compose

Future local development stack:

| Component | Role |
|-----------|------|
| Object store (Garage) | Buckets: `cache`, `tmp`, `users`, `results` ([`docs/spec/03_ARCHITECTURE.md`](../../docs/spec/03_ARCHITECTURE.md)) |
| Postgres | Registry + audit |
| asset-store | Single FastAPI service (internal `registry` / `capabilities` / `storage` modules, ADR-002) |
| fetcher (optional) | Remote URL ingestion ([`docs/services/fetcher-service.md`](../../docs/services/fetcher-service.md)) |

The full multi-service stack is documentation-only until the Phase 1 scaffold
lands. The **Garage object-store tier is real and runnable today** — see below.

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
