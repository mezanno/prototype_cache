# asset-store

The single deployable for the `asset-store` module ([`ADR-002`](../../docs/spec/03_ARCHITECTURE.md#adr-log)): one Python/FastAPI service composing three **internal modules**, not separate deployables:

- **`registry`** — assets, aliases, lifecycle (`FR-001..FR-008`, `FR-040..FR-042`).
- **`capabilities`** (the storage-guard) — service-identity auth, bucket allowlist, capability minting, audit log (`FR-010..FR-016`).
- **`storage`** — pluggable S3 backend adapter (OVH S3 hosted; Garage self-hosted — [`ADR-001`](../../docs/spec/03_ARCHITECTURE.md#adr-log)).

The implementation lives in [`src/asset_store_core/`](../../src/asset_store_core/): the domain core (`registry`, `capabilities`/`guard`, `storage` seam) plus a FastAPI app under [`src/asset_store_core/api/`](../../src/asset_store_core/api/). The backend is in-memory; the Postgres and real S3 adapters are deferred behind the existing seams. See [`docs/IMPLEMENTATION_NOTES.md`](../../docs/IMPLEMENTATION_NOTES.md).

**Future seam:** the `capabilities` module may be split into its own deployable later if the read hot path needs independent scaling ([`ADR-002`](../../docs/spec/03_ARCHITECTURE.md#adr-log)).
