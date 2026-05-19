# compose

Future local development stack:

| Component | Role |
|-----------|------|
| MinIO | Buckets: `cache`, `tmp`, `users`, `results` ([`docs/spec/03_ARCHITECTURE_AND_DECISIONS.md`](../../docs/spec/03_ARCHITECTURE_AND_DECISIONS.md)) |
| Postgres | Registry + audit |
| asset-registry, storage-guard | asset-store services |
| fetcher (optional) | Remote URL ingestion ([`docs/spec/07_FETCHER_SERVICE.md`](../../docs/spec/07_FETCHER_SERVICE.md)) |

Documentation-only until Phase 1 scaffold lands.
