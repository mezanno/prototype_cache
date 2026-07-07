# Implementation Notes

How the **current code** relates to the spec, and deliberate shortcuts for the prototype phase.

## What is implemented today

| Layer | Status |
|-------|--------|
| `asset_store_core` | In-memory registry, paths, buckets/partitions, object keys, capabilities, service policy, object-store seam (`LocalObjectStore`), `StorageGuard` facade |
| storage-guard | **Implemented** as an in-process facade (`guard.py`) + HTTP guarded data plane (`PUT`/`GET /objects/{alias}`); capability minting now **authenticates the calling service** (FR-014, ADR-016) and **audits every issuance decision** (FR-050, `capability.issue` granted/denied) |
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

FR-010–FR-015 remain the production contract; auth lives in one place (`StorageGuard`) rather than spread across callers. Capabilities are still **unsigned** in this slice — minted ids act as opaque bearer tokens held in an in-process store (ADR-003 proxy mode). A **presigned mode** is also available for reads: `GET /objects/{alias}?mode=presign` returns a short-lived S3 presigned GET URL instead of proxying bytes (see below). Signed capability tokens remain deferred.

### Presigned reads (B-010, ADR-003 presigned mode)

Workers that want to stream bytes directly from the object store (no proxy hop) can
request a presigned URL:

- **Endpoint:** `GET /objects/{alias}?mode=presign[&expires_in=<1..3600>]`, authorized
  by the same `Authorization: Capability <id>` read grant as proxy mode
  (`mode=proxy`, the default, still streams bytes). Returns JSON
  (`PresignedUrlOut`: `url`, `method`, `expires_in`, `expires_at`, `asset_id`,
  `size_bytes`, `checksum`).
- **Authorization:** `StorageGuard.presign_read` runs the full read authorization
  (`resolve_for_read`: capability scope/operation/expiry + FR-015 bucket allowlist +
  alias resolve), then asks the object store to sign the URL. The effective TTL is
  `min(expires_in, 3600, capability remaining lifetime)` so a URL never outlives the
  grant that minted it.
- **Single-use is refused:** a presigned URL is fetched outside the guard, so
  single-use (FR-013) cannot be enforced on it — `presign_read` rejects single-use
  capabilities with `CapabilityDeniedError`.
- **Backend support:** the seam gains `ObjectStoreBackend.presign_get_url`. `S3ObjectStore`
  implements it via boto3 `generate_presigned_url` (SigV4, certified on Garage);
  `LocalObjectStore` has no reachable URL and raises `PresignNotSupportedError → 501`.

### Service-identity authentication + issuance audit (B-010, FR-014/FR-050)

`POST /capabilities` now requires the caller to authenticate as a service before a
capability is minted (ADR-016):

- **Wire format:** `Authorization: Service <service_id>:<secret>`. A missing or
  malformed header, an unknown id, or a wrong secret raises `ServiceAuthError → 401`
  (RFC 7807). Secret comparison is constant-time (`hmac.compare_digest`).
- **Credential store:** `service_identity.ServiceCredentialStore` holds the id→secret
  map. It is seeded from `ASSET_STORE_SERVICE_CREDENTIALS` (`id1:secret1,id2:secret2`);
  when the env var is unset a **dev-default** store maps every known service id to
  `dev-secret:<id>` (`dev_secret(id)`), so the compose stack and tests run zero-config.
  `create_app(credentials=…)` injects a custom store in tests.
- **Identity is derived, not declared:** the authenticated `service_id` becomes the
  capability's `caller_service_id`. The request body no longer carries
  `caller_service_id` — a service can no longer mint under another's identity, which is
  what makes the FR-015 bucket allowlist trustworthy.
- **Audit (FR-050):** both `record_capability_issue` implementations
  (`InMemoryAssetRegistry`, `PostgresAssetRegistry`) append a `capability.issue` audit
  event with `outcome` `granted` or `denied`; the policy-denial path emits **both** the
  Prometheus counter and the audit event. `after` carries `operation`, `ttl_seconds`,
  and (on grant) `capability_id`.

Rotation (multiple valid secrets per id, expiry) is out of scope for the prototype; the
env map is the rotation surface (ADR-016).

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
