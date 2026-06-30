# compose

Future local development stack:

| Component | Role |
|-----------|------|
| Object store (Garage) | Buckets: `cache`, `tmp`, `users`, `results` ([`docs/spec/03_ARCHITECTURE.md`](../../docs/spec/03_ARCHITECTURE.md)) |
| Postgres | Registry + audit |
| asset-store | Single FastAPI service (internal `registry` / `capabilities` / `storage` modules, ADR-002) |
| fetcher (optional) | Remote URL ingestion ([`docs/services/fetcher-service.md`](../../docs/services/fetcher-service.md)) |

Documentation-only until Phase 1 scaffold lands.
