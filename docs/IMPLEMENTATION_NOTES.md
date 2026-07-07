# Implementation Notes

How the **current code** relates to the spec, and deliberate shortcuts for the prototype phase.

## What is implemented today

| Layer | Status |
|-------|--------|
| `asset_store_core` | In-memory registry, paths, buckets/partitions, object keys, capabilities, service policy, object-store seam (`LocalObjectStore`), `StorageGuard` facade |
| storage-guard | **Implemented** as an in-process facade (`guard.py`) + HTTP guarded data plane (`PUT`/`GET /objects/{alias}`) |
| HTTP API (`asset_store_core.api`) | **Implemented** — FastAPI app: `/healthz`, `/readyz`, `/metrics`, reserve/commit/resolve, capability mint, guarded data plane; RFC 7807 errors; metrics + JSON logs + correlation ids |
| Object store (real S3) | **First backend landed** — `s3_object_store.py` `S3ObjectStore` (boto3, optional `s3` extra) implements the `ObjectStoreBackend` seam against any S3-compatible service; **certified on Garage v1.0.1** for PUT/GET/stat/delete + server-side `sha256` on PUT + presigned-GET + the full guarded HTTP data plane (`tests/test_s3_garage_integration.py`, skipped unless `deploy/compose/.env.garage` is exported) |
| Postgres registry | **Full durable adapter landed (B-009)** — `pg_registry.py` `PostgresAssetRegistry` (psycopg 3, optional `pg` extra) implements the complete `AssetRegistry` protocol at parity with the in-memory registry: reserve/commit/resolve, lifecycle (expire/delete/annotations), alias detach/detach-mutable/rebind with tombstone grace, two-tier partition/bucket quotas, eviction policy, and the transactional audit trail. Certified against Postgres 16 (`tests/test_pg_registry.py`, skipped unless `ASSET_STORE_PG_DSN` is set). The app factory selects it when `ASSET_STORE_PG_DSN` is set; durability across app restart is proven on the unified compose stack. Schema is owned by an Alembic migration history under `migrations/` (`alembic upgrade head`; `tests/test_migrations.py` certifies upgrade/downgrade + a registry round-trip on the migrated schema), with the runtime `CREATE TABLE IF NOT EXISTS` bootstrap retained as a dev/test convenience. A SQLAlchemy ORM layer is intentionally *not* adopted — the registry's explicit `FOR UPDATE`/upsert SQL is hand-written for concurrency correctness |

Run tests:

```bash
uv run pytest -q
```

### Spec alignment (ADR-007)

- Registry `space` = object-store bucket (`cache`, `tmp`, `users`, `results`).
- `partition_id` on every asset; `storage_key` = `{partition_id}/assets/{asset_id}`.
- Qualified aliases: `{bucket}/{partition_id}/…` (e.g. `users/42/uploads/photo.jpg`).
- `service_policy` encodes FR-015 bucket allowlists (enforced inside `StorageGuard` and at capability mint).

## storage-guard build order (done)

The phased order below was followed; the guard is no longer deferred.

1. **Registry + object-store adapter** (reserve / PUT / commit / resolve) with direct calls in integration tests. **Done.**
2. **Thin guard facade** (`guard.py`) composing `service_policy` + capability checks + registry/object-store. **Done.**
3. **HTTP server** exposing the registry ops, capability mint, and a capability-guarded data plane. **Done.**

FR-010–FR-015 remain the production contract; auth lives in one place (`StorageGuard`) rather than spread across callers. Capabilities are still **unsigned** in this slice — minted ids act as opaque bearer tokens held in an in-process store (ADR-003 proxy mode); presigned URLs and signed tokens are deferred.

## Object-store backends behind the seam

The `ObjectStoreBackend` protocol has two implementations, swappable via
`create_app(store=...)`:

| Implementation | Use | Notes |
|----------------|-----|-------|
| `LocalObjectStore` | Default / unit tests | In-memory dict; infrastructure-free, fast |
| `S3ObjectStore` | Real durable storage | boto3, path-style + SigV4; computes the canonical `sha256:<hex>` on PUT (FR-022, never the S3 ETag) and stores it in object metadata for `stat`; **transparent multipart** upload above `multipart_threshold` (abort-on-failure); `NoSuchKey`/404 → `ObjectNotFoundError`; idempotent delete |

`S3ObjectStore` is **certified on Garage** (ADR-001, S-004 in progress): PUT/GET/
stat/delete, multipart round-trip, and presigned-GET all pass; the hosted OVH S3
tier and backend-native lifecycle remain on the S-001 to-do list. See
[`deploy/compose/README.md`](../deploy/compose/README.md) for the local run recipe.

## “Are we just building a filesystem on S3?”

**Partly — and that is intentional, but it is not only paths on disk.**

| Layer | Off-the-shelf? | What we use |
|-------|----------------|-------------|
| Raw blob store | **Yes** | Object store: Garage / OVH S3 ([`ADR-001`](spec/03_ARCHITECTURE.md), [`A_OSS_SURVEY.md`](spec/A_OSS_SURVEY.md)) |
| Aliases + lifecycle + multi-name + audit | **No single match** | Custom registry (ADR-002 rejected InvenioRDM etc. as overshoot) |
| Prefix-scoped, short-lived credentials | **Partial** | S3 presigned URLs + our guard semantics |
| Heritage-specific fetch + cache policy | **No** | Planned fetcher-service |

Products that look similar and why we did not adopt them as the whole stack:

| Product | Overlap | Gap vs our spec |
|---------|---------|-----------------|
| **Plain object store (Garage / OVH / AWS S3) alone** | Buckets + keys | No alias layer, no `pending→available`, no per-task capabilities |
| **Nextcloud / Seafile** | User files | User-sync model, not service identities + worker aliases |
| **InvenioRDM / Fedora** | Repository + files | Record/RDF centric; heavy deps; wrong mutability model |
| **rclone / s3fs / goofys** | Mount S3 as filesystem | No alias immutability, audit, or capability broker |
| **LakeFS** | Versioned object branches | Git-like branching, not citation-stable aliases |

So: **we are not replacing S3** — we are adding a **thin control plane** (registry + guard) for things S3 does not standardize: multiple stable names per blob, lifecycle states, service-scoped access, and audit. That is smaller than a full DAM or institutional repository.

If requirements shrink to “store files per user with ACLs only,” revisiting **Nextcloud** or **Garage + a tiny metadata DB** could be worth a spike ([`Q-009`](spec/05_BACKLOG_AND_OPEN_QUESTIONS.md)). The current spec (immutable assets, alias grace, fetcher, worker results) justifies the custom layer.

## Related spec docs

- Storage layout: [`spec/03_ARCHITECTURE.md`](spec/03_ARCHITECTURE.md)
- Jargon: [`spec/README.md` glossary](spec/README.md#glossary-and-acronyms)
- OSS survey: [`spec/A_OSS_SURVEY.md`](spec/A_OSS_SURVEY.md)
