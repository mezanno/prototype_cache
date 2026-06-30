# 02 - Requirements

> Terms and acronyms: [`README.md` glossary](README.md#glossary-and-acronyms)

## At a glance

| Layer | Key requirements |
|-------|------------------|
| Registry | FR-001..008, FR-063..069 — assets, aliases, lifecycle, eviction policy, quota |
| Guard | FR-010..016 — capabilities, service auth, **bucket allowlist**, **bucket provisioning only at init** |
| Data plane | FR-020..022 — PUT, multipart, commit + checksum |
| Workers | FR-030..031 — resolve by alias only |
| Admin | FR-040..042 |
| Storage layout | NFR-012 — `{partition_id}/assets/{asset_id}`; `space` = bucket name |

**New in this revision:** **FR-015** — each service identity may only issue capabilities for buckets it is allowed to use.

**New in this revision (2026-05-20):** **FR-063..069** — eviction policy flag, capacity soft gate, batch partition policy reset, partition and bucket quota enforcement, and `results` housekeeping contract. `results` `partition_id` changed from `{taskid}` to `{userid}` (anonymous tasks use reserved `partition_id = anon`); Q-004, Q-006, Q-020, Q-029 resolved.

Priority codes: **M** = must, **S** = should, **C** = could, **W** = won't. P0 = M; P1 = S; P2 = C; P3 = W.

## Functional Requirements

### Asset and alias model

- **FR-001 (M)** Create an asset by submitting a payload, one or more aliases, a **`space`** (storage bucket: `cache`, `tmp`, `users`, or `results`), a **`partition_id`** (e.g. mirror id, user id; for `results` always `{userid}` — task identity lives in the alias path; anonymous tasks use the reserved value `anon`), an optional TTL (seconds), and an optional declared MIME. Each alias may carry an explicit `mutable` boolean flag (default `false`, see FR-008). The server returns an opaque `asset_id` and the canonical list of aliases. Each alias is unique within its space namespace; conflict yields `409 Conflict` without overwriting the existing binding. The registry assigns `storage_key` = `{partition_id}/assets/{asset_id}` in the target bucket ([`ADR-007`](03_ARCHITECTURE.md)).
- **FR-002 (M)** Resolve an alias to an `asset_id` and to a redirect or signed URL for download. Deny if the alias is unknown, `pending`, `expired`, or `deleted`.
- **FR-003 (M)** Add a *new* alias to an existing asset (subject to namespace uniqueness; new alias inherits `mutable=false` unless explicitly set). Detach an alias from its asset: for immutable aliases (the default), detach permanently destroys the alias; the name is reserved for a grace period (default 7 days) before it can be reused. For mutable aliases (FR-008), detach is the prerequisite to rebind. An asset with zero remaining aliases is automatically marked for garbage collection.
- **FR-004 (M)** Reserve an alias before its payload exists (state `pending`) so an uploader can stream the payload via a signed URL and commit afterwards.
- **FR-005 (S)** Update annotation fields of an asset (free-form key/value map) without rewriting the payload. The payload itself is write-once. The alias binding is governed by FR-003 / FR-008, not by this requirement.
- **FR-006 (S)** Expire an asset (admin or owner): transitions state to `expired`; resolve returns 410; payload is preserved until garbage collection runs.
- **FR-007 (S)** Delete an asset (admin): transitions state to `deleted`; payload removed from `object-store`; record retained in audit log.
- **FR-008 (S)** *Mutable alias opt-in.* An alias created with `mutable: true` MAY be rebound to a different `asset_id` via `POST /aliases/{alias}/rebind`. Each rebind emits an `alias.rebind` audit event with `before`/`after` asset ids and caller identity. The `mutable` flag is set at create time and is itself immutable. **Default for every alias is `mutable: false`** - rebind is rejected with `409 Conflict` for immutable aliases. Versioning, history, and structural-vs-descriptive composition for IIIF manifests and similar documents are explicitly *not* in scope here and are delegated to a future `manifest-service` (see [`01_SCOPE.md`](01_SCOPE.md)).

### Capability and authorization model

- **FR-010 (M)** Issue a read capability for a single alias or an alias prefix; capability has a TTL between 60 s and 24 h (configurable). Capability returned as either a direct signed URL on the `object-store` or an opaque token validated by a proxy endpoint (mode controlled by `ADR-003`).
- **FR-011 (M)** Issue a write capability for a single alias (existing or to-be-created) or for a write-only alias prefix; same TTL bounds as FR-010.
- **FR-012 (M)** Reject any operation whose alias is outside the capability's declared scope; return `403 Forbidden`. Enforcement verified by the test suite covering S-4.
- **FR-013 (S)** Issue a "single-use" write capability that is invalidated after one successful PUT.
- **FR-014 (M)** Authenticate calling services via static service credentials (shared secret or mTLS, choice in `ADR-006`); user-level authentication is delegated to upstream APIs.
- **FR-015 (M)** Enforce a **bucket allowlist** per service identity on every capability issue and registry write. A caller authenticated as `upload-api` cannot obtain write capabilities for `results`; a caller as `fetcher` cannot write `users`. Cross-bucket attempts return `403 Forbidden`. The allowlist is defined in [`03_ARCHITECTURE.md`](03_ARCHITECTURE.md). Verified together with S-4 and FR-012.
- **FR-016 (M)** *Buckets are provisioned only at initialization.* The fixed set of category buckets (`cache`, `tmp`, `users`, `results`) is created by an administrator during system bootstrap with the correct policies and retention; **no service identity may create or delete buckets during normal operation**. Any runtime bucket-creation/deletion attempt is rejected and audited. This bounds the blast radius of a compromised or mis-scoped service to existing buckets with known policies.

### Upload path

- **FR-020 (M)** Accept payload uploads via S3-style PUT to a signed URL.
- **FR-021 (M)** Accept multipart / resumable uploads for payloads up to 5 GB (object-store native multipart protocol).
- **FR-022 (M)** Upon commit, the registry records `size_bytes`, `mime` (declared or sniffed), and the **server-side checksum** computed by the `object-store`. The caller may submit a client-side checksum; mismatch yields `409 Conflict` and the upload is rolled back.

### Read path

- **FR-030 (M)** Worker fetches assets exclusively by alias (never by raw object key). The `storage-guard` is the sole authority on whether an alias is currently resolvable for the caller.
- **FR-031 (S)** Provide a batch alias-resolution endpoint to amortize round-trips when a worker has many inputs.

### Admin path

- **FR-040 (M)** List assets with filters (`space`, `state`, `created_at` range, alias prefix). Cursor-based pagination. When a `partition_id` filter is present, the response includes current quota usage (`used_bytes`, `quota_bytes`, `used_asset_count`, `quota_asset_count`) from `PartitionQuota`.
- **FR-041 (M)** Inspect a single asset: full metadata, alias list, recent audit events, current state.
- **FR-042 (M)** Lifecycle actions: set/extend TTL, force `expire`, force `delete`, attach/detach alias; set/update per-partition quota (`quota_bytes`, `quota_asset_count`, `eviction_sweep_enabled`) via `PartitionQuota`; bulk-expire-by-prefix (`POST /admin/aliases/expire?prefix=<prefix>`) to support task-engine housekeeping of result sets.

### Audit and observability

- **FR-050 (M)** Emit an audit event for every capability issuance (caller identity, scope, TTL, granted/denied).
- **FR-051 (M)** Emit an audit event for every alias mutation (create, attach, detach, rename) and lifecycle transition.
- **FR-052 (M)** Emit an audit event for every admin action.
- **FR-053 (S)** Aggregate per-asset access counters (read hits, last-read timestamp); exposed via admin API and used to identify least-frequently-accessed assets.

### Backup and lifecycle

- **FR-060 (S)** Configurable background job removes payloads of assets in `expired` state after a grace period (default 7 days), transitioning them to `deleted`.
- **FR-061 (C)** Incremental snapshot of `object-store` to a second, possibly slower, S3-compatible backend; runs on a schedule.

### Eviction policy and quota

- **FR-063 (M)** *Eviction policy flag.* Every asset carries an `eviction_policy` field: `inherit` (default) or `exempt`. `inherit`: asset follows the per-space eviction sweep policy. `exempt`: asset is excluded from all capacity-triggered and quota-triggered eviction sweeps; TTL expiry (FR-006, FR-060) still applies normally. The field may be set by the creating service at write time and updated by admin at any time; every change emits an `asset.eviction_policy_set` audit event. Must be present in the data model from the registry MVP (B-009).
- **FR-064 (S)** *Bucket-level capacity soft gate.* Each `space` has three configurable capacity thresholds: high-water (default 80%), soft-ceiling (90%), hard-ceiling (95%). Above high-water: metric `storage_space_used_ratio{space}` > 0.80 and a Prometheus alert fires; no write blocking. Above soft-ceiling: the lifecycle worker schedules an async eviction sweep (LFU+age order, `exempt` assets skipped). Above hard-ceiling: new commit requests return `503 Service Unavailable` with `Retry-After`; `pending` alias reservations are still accepted to avoid deadlocking in-progress uploads. If the sweep exhausts all non-`exempt` candidates without reaching the low-water mark (default 70%), the worker emits `gc_eviction_exhausted{space}` and stops — it never auto-escalates to `exempt` assets (Q-027 resolved: alert-only for MVP).
- **FR-065 (C)** *Batch partition eviction-policy reset.* Admin can set or clear `eviction_policy` on all assets in a given `(space, partition_id)` in one call. Emits one `asset.eviction_policy_set` audit event per affected asset. Implementation detail (synchronous vs. async with status endpoint) is deferred as Q-028.
- **FR-066 (S)** *Per-partition quota enforcement at commit.* At commit time the registry checks `PartitionQuota.used_bytes + new_size_bytes` against `PartitionQuota.quota_bytes` (when set). Thresholds: ≥ 80% → emit warn metric `quota_used_ratio{space,partition_id}` > 0.80; ≥ 90% → trigger async eviction sweep if `PartitionQuota.eviction_sweep_enabled = true`; ≥ 105% → reject with `413 Partition Quota Exceeded` + `Retry-After`. The 105% ceiling absorbs concurrent in-flight uploads that pre-checked quota before committing. `PartitionQuota.used_bytes` is updated atomically via Postgres `UPDATE … RETURNING` on every commit and every `→ deleted` transition; never via read-modify-write.
- **FR-067 (S)** *Quota-triggered eviction sweep.* When a partition crosses the 90% quota trigger, the lifecycle worker sweeps `available` assets with `eviction_policy = inherit` in that partition, ordered by `last_read_at_age_days × size_bytes` descending (favouring large stale assets), until `used_bytes` falls to or below a configurable low-water mark (default 75% of `quota_bytes`). Applies only to partitions where `PartitionQuota.eviction_sweep_enabled = true` (default `true` for `cache` and `tmp`; `false` for `users` and `results`). Evicted assets transition to `expired`; normal TTL GC (FR-060) handles the subsequent `expired → deleted` transition.
- **FR-068 (S)** *Global bucket quota enforcement at commit.* In addition to per-partition checks (FR-066), the registry checks `BucketQuota.used_bytes + new_size_bytes` against `BucketQuota.quota_bytes` (when set). Thresholds: ≥ 80% → warn metric; ≥ 100% → reject with `413 Bucket Quota Exceeded`. The response body distinguishes which limit was hit (partition vs. bucket). `BucketQuota.used_bytes` is maintained atomically alongside per-partition updates.
- **FR-069 (S)** *Results housekeeping contract.* The `results` space is not subject to LFU eviction sweeps (`PartitionQuota.eviction_sweep_enabled = false` for all `results` partitions). Instead: (a) task-api **should** set a `ttl_seconds` hint on every result alias reservation (FR-004); (b) the registry **should** enforce a configurable maximum TTL for `results` writes (operator-set default: 365 days) to prevent indefinite accumulation; (c) the task engine is the primary driver of explicit expiry via the bulk-expire-by-prefix admin action (FR-042); (d) TTL GC (FR-060) is the fallback for abandoned tasks.

### Operational

- **FR-070 (M)** Health endpoints (`/healthz`, `/readyz`) on every service.
- **FR-071 (M)** Configuration via environment variables and/or files; secrets via a secret manager (final mechanism in `ADR-006`).
- **FR-072 (M)** Single-machine dev mode (`docker compose up`) brings up `object-store`, `asset-registry`, `storage-guard`, `admin-ui`, observability stack.

## Non-Functional Requirements

### NFR-001 - Capacity

- **Category**: Scalability
- **Requirement**: hold at least 1 TB of payloads across at least 100 000 assets on the dev stack without operator intervention.
- **Target**: 1 TB, 1e5 assets, 30 days steady-state.

### NFR-002 - Read latency

- **Category**: Performance
- **Requirement**: p95 latency for an authorized GET of a payload up to 5 MB.
- **Target**: under 200 ms in-cluster, under 500 ms cross-host on the dev stack.

### NFR-003 - Capability mint latency

- **Category**: Performance
- **Requirement**: p95 latency for `storage-guard` to mint a capability given a valid caller.
- **Target**: under 50 ms.

### NFR-004 - Concurrency

- **Category**: Performance
- **Requirement**: sustain 30 concurrent worker readers and 10 concurrent users with the latency targets above.
- **Target**: 5-minute steady-state load; zero capability-issuance errors; read-error rate under 0.1%.

### NFR-005 - Durability

- **Category**: Durability
- **Requirement**: no silent data loss; checksum verified on write (server-side) and re-verified on read at least sample-based.
- **Target**: read-checksum sampling at >= 1% of reads; mismatch raises an alert with severity SEV-1.

### NFR-006 - Availability

- **Category**: Availability
- **Requirement**: read-path SLO.
- **Target**: 99.9% successful reads over a rolling 30-day window once Phase 4 is complete; not enforced before pilot.

### NFR-007 - Security (in transit)

- **Category**: Security
- **Requirement**: all external traffic over HTTPS/TLS; mTLS optional within the cluster (`ADR-006`).
- **Target**: TLS 1.2+; no plaintext credentials in logs (redaction policy in [`04_OPERATIONS.md`](04_OPERATIONS.md)).

### NFR-008 - Capability scoping (least privilege)

- **Category**: Security
- **Requirement**: capabilities are prefix-scoped and time-bounded; default deny outside scope.
- **Target**: a capability for prefix `<space>/<partition>/…` cannot access anything outside that prefix (path-segment aware); verified by the test suite covering S-4.

### NFR-009 - Audit retention

- **Category**: Auditability
- **Requirement**: audit events retained on local storage for at least 30 days; export hook for longer retention.
- **Target**: structured JSON; one event per record; tamper-evident (append-only file or DB table, no in-place delete).

### NFR-010 - Cost

- **Category**: Cost
- **Requirement**: storage and compute cost remain within commodity-server budget; no hard SLO yet.
- **Target**: dev stack runs on one developer workstation with under 8 GB RAM and under 4 CPU cores while idling.

### NFR-011 - Deployability

- **Category**: Operability
- **Requirement**: prototype is deployable to Docker Swarm using a published stack file; same definitions exercised locally via Docker Compose.
- **Target**: `docker compose up` returns healthy in under 2 minutes; Swarm rolling update of any service does not drop any in-flight read.

### NFR-012 - Backward-compatibility-friendly identifiers

- **Category**: Maintainability
- **Requirement**: `asset_id`, alias, and object keys must allow renaming a service or moving to a different `object-store` in the future without rewriting payloads.
- **Target**: opaque `asset_id`; object key = `{partition_id}/assets/{asset_id}` where `partition_id` is an opaque tenant id (userid, taskid, mirror id)—not filenames, MIME types, or URL paths. Bucket name (`space`) carries storage class, not the object key tail.

## API Requirements

- **Idempotency** - all write endpoints accept an `Idempotency-Key` header; duplicate requests with the same key within 24 h yield the original response. Reservation of an alias (FR-004) is the canonical idempotency anchor.
- **Error model** - JSON Problem Details (RFC 7807); machine-readable `type` URIs documented in the OpenAPI spec.
- **AuthN/AuthZ** - service identities authenticate to the `storage-guard` (FR-014); all data-plane reads/writes happen via short-lived capabilities (FR-010..FR-013).
- **Versioning strategy** - URL-versioned (`/v1/...`); breaking changes require a new major segment; deprecation window of at least 6 months once the module exits the prototype phase.

## Data Requirements

- **Metadata fields (minimum, per asset)**: `asset_id`, `space` (bucket name), `partition_id`, `storage_key`, `aliases[]`, `mime`, `size_bytes`, `checksum_algo`, `checksum`, `state`, `created_at`, `updated_at`, `expires_at`, `annotations` (free-form map), `owner_service_id`.
- **Indexing / search**: alias is the primary lookup (unique within space). Secondary lookups by `space`, `partition_id`, `state`, `created_at` range, alias prefix. No full-text search in MVP.
- **Retention / deletion policy**: assets with TTL transition to `expired` automatically; grace period (default 7 days) before garbage collection. Deleted assets keep audit history for at least 30 days.
- **PII / sensitive data handling**: no PII stored by `asset-store` itself; callers must not put PII in alias names. Documented in security guidance.

## Compliance And Security Requirements

- **Regulatory constraints**: none binding in MVP; GDPR considerations tracked as `Q-*` rows.
- **Encryption requirements**: TLS in transit (NFR-007). Encryption at rest deferred (`R-*` risk row).
- **Audit trail requirements**: per FR-050..FR-053 and NFR-009.
- **Key management constraints**: TBD by `ADR-006` (service credentials) - revisit when storage-guard auth is finalized.

## Acceptance Criteria

P0 requirements must have an objective test or measurement that proves the target was met. The mapping below is the canonical link; individual tests live in the test code under each service.

- **FR-001 (Create asset)** - integration test creates an asset with two aliases and verifies that resolving each alias returns the same `asset_id`; conflict test attempts a duplicate alias and expects `409`.
- **FR-002 (Resolve alias)** - integration test resolves alias to signed URL, downloads payload, verifies checksum; negative tests cover unknown / pending / expired / deleted aliases.
- **FR-008 (Mutable alias)** - test creates an alias with `mutable: false`, attempts a rebind, expects `409`; creates an alias with `mutable: true`, performs a rebind, expects `200` plus an `alias.rebind` audit entry containing the before/after asset ids; immutable alias detach + name reuse before grace period expires expects `409`.
- **FR-010..012 (Capabilities + scoping)** - dedicated test suite per S-4: a capability for prefix `users/42/uploads/` is exercised against 10 in-scope and 10 out-of-scope aliases; all 10 in-scope succeed, all 10 out-of-scope fail with 403.
- **FR-015 (Bucket allowlist)** - `upload-api` credential cannot mint write capability for `results/`; `fetcher` cannot mint for `users/`; expects `403`.
- **FR-021 (Multipart upload)** - integration test uploads a 1 GB payload in multipart and verifies end-to-end checksum.
- **FR-022 (Server-side checksum)** - integration test forces a body bit-flip via a test hook and expects `409` with rollback.
- **FR-050..052 (Audit)** - test grep audit log after a scripted scenario covering create / capability mint / lifecycle / admin; all expected events present.
- **NFR-001 (Capacity)** - load test ingests 100 000 small files plus padding to reach 1 TB; storage backend reports OK, registry queries respond within latency targets.
- **NFR-002 (Read latency)** - load test under S-2 reports p95 latency.
- **NFR-003 (Mint latency)** - load test on the `storage-guard` reports p95 latency.
- **NFR-004 (Concurrency)** - load test runs S-2 scenario with 30 concurrent workers; assertion on error rate and latency.
- **NFR-005 (Durability)** - chaos test deletes one storage-backend node (where applicable); writes and reads continue or fail gracefully; checksum verification on a 1% read sample passes for all retained data.
- **NFR-008 (Scoping)** - identical test suite as for FR-010..012; here measured per scope of the issued credential.
- **NFR-011 (Deployability)** - CI job runs `docker compose up`, asserts all services report healthy within 2 minutes, then runs the smoke tests.
