# 02 - Requirements

Priority codes use MoSCoW: **M** = must, **S** = should, **C** = could, **W** = won't (this iteration).
P0 = MoSCoW M; P1 = MoSCoW S; P2 = MoSCoW C; P3 = MoSCoW W.

## Functional Requirements

### Asset and alias model

- **FR-001 (M)** Create an asset by submitting a payload, one or more aliases, an optional TTL (seconds), and an optional declared MIME. Each alias may carry an explicit `mutable` boolean flag (default `false`, see FR-008). The server returns an opaque `asset_id` and the canonical list of aliases. Each alias is unique within its space namespace; conflict yields `409 Conflict` without overwriting the existing binding.
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

### Upload path

- **FR-020 (M)** Accept payload uploads via S3-style PUT to a signed URL.
- **FR-021 (M)** Accept multipart / resumable uploads for payloads up to 5 GB (object-store native multipart protocol).
- **FR-022 (M)** Upon commit, the registry records `size_bytes`, `mime` (declared or sniffed), and the **server-side checksum** computed by the `object-store`. The caller may submit a client-side checksum; mismatch yields `409 Conflict` and the upload is rolled back.

### Read path

- **FR-030 (M)** Worker fetches assets exclusively by alias (never by raw object key). The `storage-guard` is the sole authority on whether an alias is currently resolvable for the caller.
- **FR-031 (S)** Provide a batch alias-resolution endpoint to amortize round-trips when a worker has many inputs.

### Admin path

- **FR-040 (M)** List assets with filters (`space`, `state`, `created_at` range, alias prefix). Cursor-based pagination.
- **FR-041 (M)** Inspect a single asset: full metadata, alias list, recent audit events, current state.
- **FR-042 (M)** Lifecycle actions: set/extend TTL, force `expire`, force `delete`, attach/detach alias.

### Audit and observability

- **FR-050 (M)** Emit an audit event for every capability issuance (caller identity, scope, TTL, granted/denied).
- **FR-051 (M)** Emit an audit event for every alias mutation (create, attach, detach, rename) and lifecycle transition.
- **FR-052 (M)** Emit an audit event for every admin action.
- **FR-053 (S)** Aggregate per-asset access counters (read hits, last-read timestamp); exposed via admin API and used to identify least-frequently-accessed assets.

### Backup and lifecycle

- **FR-060 (S)** Configurable background job removes payloads of assets in `expired` state after a grace period (default 7 days), transitioning them to `deleted`.
- **FR-061 (C)** Incremental snapshot of `object-store` to a second, possibly slower, S3-compatible backend; runs on a schedule.

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
- **Target**: TLS 1.2+; no plaintext credentials in logs (redaction policy in [`04_OPERATIONS_AND_READINESS.md`](04_OPERATIONS_AND_READINESS.md)).

### NFR-008 - Capability scoping (least privilege)

- **Category**: Security
- **Requirement**: capabilities are prefix-scoped and time-bounded; default deny outside scope.
- **Target**: a capability for prefix `<space>/<prefix>/` cannot access anything outside that prefix; verified by the test suite covering S-4.

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
- **Target**: opaque IDs; object keys derived from `asset_id` only; no semantic info in the object key.

## API Requirements

- **Idempotency** - all write endpoints accept an `Idempotency-Key` header; duplicate requests with the same key within 24 h yield the original response. Reservation of an alias (FR-004) is the canonical idempotency anchor.
- **Error model** - JSON Problem Details (RFC 7807); machine-readable `type` URIs documented in the OpenAPI spec.
- **AuthN/AuthZ** - service identities authenticate to the `storage-guard` (FR-014); all data-plane reads/writes happen via short-lived capabilities (FR-010..FR-013).
- **Versioning strategy** - URL-versioned (`/v1/...`); breaking changes require a new major segment; deprecation window of at least 6 months once the module exits the prototype phase.

## Data Requirements

- **Metadata fields (minimum, per asset)**: `asset_id`, `space`, `aliases[]`, `mime`, `size_bytes`, `checksum_algo`, `checksum`, `state`, `created_at`, `updated_at`, `expires_at`, `annotations` (free-form map), `owner_service_id`.
- **Indexing / search**: alias is the primary lookup (unique within space). Secondary lookups by `space`, `state`, `created_at` range, alias prefix. No full-text search in MVP.
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
- **FR-010..012 (Capabilities + scoping)** - dedicated test suite per S-4: a capability for prefix `u-42/uploads/` is exercised against 10 in-scope and 10 out-of-scope aliases; all 10 in-scope succeed, all 10 out-of-scope fail with 403.
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
