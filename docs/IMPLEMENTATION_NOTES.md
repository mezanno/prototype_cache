# Implementation Notes

How the **current code** relates to the spec, and deliberate shortcuts for the prototype phase.

## Private pilot Compose package (ADR-032, 2026-10-01)

M-001/P4 / B-003/B-019 / FR-050/064/068: a separate private project packages
Garage, Postgres, asset-store, real pilot-mode fetcher, migration and scheduled
lifecycle. API ports bind loopback; backends publish none. Protected operator
runtime files supply provisioned secrets and digest-pinned images. Application
containers are read-only with bounded scratch, no added capabilities and one
ASGI process. CPU/memory/PIDs, byte/job/pool/token admission and rotating logs
are explicit. API startup waits for migration success. Scheduled apply is an
opt-in profile after dry-run review, sharing API budgets and existing logs/metrics.

[Preflight and runbook](../deploy/pilot/README.md) check actual Compose rendering,
secret-file permissions, matching non-development service/database credentials,
image digests, origin enforcement and limits. Secret-bearing Compose output is
captured rather than printed. Runtime files are ignored and excluded from builds.
Docker administrators can inspect environment credentials and are trusted.
Named volumes do not impose disk quotas: host allocation, audit retention,
monitoring and backup remain operational gates. No data migration/schema change
is introduced by this packaging slice; it uses existing migration 0003.

Validation: **499 tests pass, none skipped**, with Garage/Postgres; 18 preflight
regressions, Ruff lint/format, strict mypy (86 files) and whitespace checks pass.
Installed Garage v1.0.1 CLI help confirms key/bucket provisioning syntax. Default
tests now require Compose CLI parsing without daemon access; CI checks tooling.
No pilot containers were started and no images published. Next: reviewed image
and host selections, real deployment smoke/restart/private access and admin
browser acceptance; P5/P6 recovery/soak gates remain open.

## Gallica origin and smoke evidence (2026-10-01)

M-001/P3 / B-024 / SCN-010 / FR-010–015 / FR-020–022: a generated JPEG is served
by a local HTTPS origin with a Gallica hostname certificate. Test-only DNS/port
mapping and private-address permission retain hostname/SNI verification and the
production image policy. Garage bytes and isolated Postgres metadata survive
registry/app reopen; cached reads work during origin errors, repeated reads and
preloads do not contact origin, and lost capabilities remint. No live Gallica
requests or confidential/third-party fixture content.

The [HTTP smoke artifact](../tools/cache-pilot/README.md) validates preload,
two capped downloads with matching ETags/hashes and repeated preload reuse.
It requires explicit endpoint/origin/service credentials, verifies TLS, disables
environment proxies and redirects, and prints only hashes/counts/hit flags or
sanitized failures. Tests exercise a real cache HTTP socket and negative response,
checksum, byte-limit and credential-output cases. This is an operator check,
not a new ingestion CLI or background job API. No production code or migration
changes in this slice; no new technical ADR beyond ADR-031 is needed.

Validation: **481 tests pass, none skipped**, with Garage/Postgres; Ruff
lint/format, strict mypy (84 files) and whitespace checks pass. P3 implementation
and local evidence are complete. Next: P4 private Compose packaging, secrets,
resource configuration and deployment acceptance. Fresh-host/container restart,
admin browser acceptance, live corpus, backup/restore and soak remain open.

## Gallica cache API checkpoint (ADR-031, 2026-10-01)

B-024 / SCN-010 / FR-010–015 / FR-020–022: authenticated preload and cache-only
host-prefixed reads now share an exact Gallica image policy. Separate
`gallica-pilot` aliases preserve renditions without inheriting legacy quality
merging. Queries and ambiguous encodings are rejected. Real HTTP redirects are
policy checked before contact, in addition to connection-bound SSRF/TLS checks.
Reads validate size/checksum, share bounded jobs and remint scoped internal
capabilities once after 403. Backend errors are sanitized and capacity/rate
rejections retain retry guidance. `FETCHER_PILOT_MODE=true` disables generic
ensure-url; deployment must enable it. No migration.

Cache operation counters and structured logs expose hit/stored/miss/error;
forced-refetch counters cover matches and conflicts. No caller-visible tokens,
raw keys or source queries. Tests use an in-memory store and approved URL/image
fixtures, with mocked redirect transport; existing full regression includes
Garage/Postgres. This does not certify a live Gallica corpus or deployment.

Validation: **474 passed, none skipped**, Ruff lint/format, strict mypy (81 files)
and whitespace checks pass. Next slice: approved-origin integration fixture and
HTTP smoke script, then private Compose configuration and restart acceptance.
P3 remains open until its remaining evidence is delivered.

## Capability issuance admission rate (ADR-030, 2026-10-01)

M-001/P2 / FR-010/014/050: a lock-protected token bucket per configured service
identity admits mint attempts before policy, token capacity or issuance audit.
`ASSET_STORE_CAPABILITY_RATE_PER_MINUTE=120` refills credit; the initial/maximum
burst is `ASSET_STORE_CAPABILITY_RATE_BURST=20` (positive integers). Saturation
returns 429 with computed `Retry-After`. Failed admitted attempts are charged;
invalid credentials consume no credit. Existing grants remain usable. Limiter
state is fixed to configured identities; process restart restores burst credit.

Rate admission rejections increment capability issuance outcome `rate_denied`
and emit `capability.rate_denied` logs with the verified identity. They create no
capability/audit row. Admitted grant/policy-denial auditing remains after rate
admission, including audit-before-publication. This bounds audit work per identity
rather than lifetime audit size; ingress controls/log and audit retention remain
P4/P5 operations work. No migration. Single-process pilot only.

Validation: **448 tests passed, none skipped**, with Garage/Postgres enabled;
43 focused capability/Postgres regressions pass. Ruff lint/format, strict mypy
(78 files) and whitespace checks pass. Two existing upstream deprecation warnings
remain.

P2 implementation slices are complete (ADRs 026–030); next is **P3 / B-024**,
the Gallica preload and cache-only read API. Deployment/resource configuration,
scans and acceptance evidence remain before inviting testers.

## Durable upload byte reservations (ADR-029, 2026-10-01)

M-001/P2 / SEC-06 / FR-022/064/066/068: guarded writes persist exact-size
`reserved_bytes` before PUT. Pending reservations participate in logical byte and
asset-count admission; unpurged estimates also participate in physical capacity,
including failed/deleted uploads. Commit excludes its own estimate, requires
matching size, clears the estimate and acquires available usage once. Failed
cleanup keeps its physical estimate until purge. Lifecycle physical occupancy
includes retained estimates. Quota rejection before PUT creates no alias/payload.

**Upgrade:** run `alembic upgrade head` (migration `0003_upload_reservations`)
before starting updated durable services. Historical reservations remain NULL:
unknown-size orphan payloads need the existing sweep; configure
`ASSET_STORE_CAPACITY_BYTES` for bounded pilot storage. Raw metadata reservations
keep legacy unknown-size behavior. Downgrade removes estimates and requires
quiescing/reclaiming pending uploads first; it is not an online application rollback.

Postgres uses partition then bucket admission locks, creating quota rows when
absent. TTL restoration uses the same order and excludes already stored bytes
from prospective capacity. `asset.upload_reserve` audits record the owner and
size. `asset_store_upload_reservations_total{space,outcome}` and
`upload.reserve_denied` logs cover admission; `asset_store_reserved_upload_bytes`
shows unpurged estimates, including failed writes. Postgres metric checkout is
bounded to 10ms per bucket and returns NaN when unavailable without incrementing
registry overload counters or failing the entire metrics response.

Validation (2026-10-01): **432 tests passed, none skipped**, with Garage/Postgres;
Ruff lint/format, strict mypy (76 files), and whitespace checks pass. The focused
reservation/cleanup/concurrency/migration suite passes 58 tests. Two existing
upstream deprecation warnings remain.

Next P2 item: capability issuance rate limits.

## Aggregate work admission (ADR-028, 2026-09-30)

M-001/P2 / SEC-06 / NFR-004: per-process no-wait upload and ensure-url gates
(default 4 each), configurable with `ASSET_STORE_MAX_INFLIGHT_UPLOADS` and
`FETCHER_MAX_INFLIGHT_JOBS`. Saturation returns 503 / `Retry-After: 1` before
upload body buffering or origin work. Upload slots cover body reads through
commit/cleanup; fetcher slots cover the entire ensure-url job, including hits.
Blocking work runs in threads; cancelled requests retain their lease until the
worker exits. Authentication remains before admission. Inflight gauges,
admission outcome counters and structured overload logs expose pressure.

No migration. Bounds multiply across processes; use one process per service for
M-001. Existing per-body limits apply, but copied payloads/server buffers are not
a process RSS guarantee. Ingress timeouts remain P4 deployment work. Durable
pending-byte accounting and capability issuance rate remain the next P2 slice.

Validation: **409 tests passed, none skipped**, with Garage/Postgres enabled.
Ruff lint/format, strict mypy (75 files) and whitespace checks pass. Two existing
upstream deprecation warnings remain; this is not load/deployment certification.

## Failed proxy-upload cleanup (ADR-027, 2026-09-30)

M-001/P2 / SEC-06, FR-022/050..052/060: failed PUT/commit now triggers immediate
best-effort cleanup. Separate committed deletion fencing precedes byte removal;
state rechecks preserve successful assets. Failed fencing leaves pending-orphan
maintenance eligible; failed deletion leaves a deleted asset for the next sweep.
The original upload error is preserved and failed single-use writes remain unused.
`asset_store_failed_upload_cleanup_total{space,outcome}` counts `reclaimed`,
`deferred`, and `preserved`; `upload.cleanup` logs contain no bearer or error text.
Lifecycle audit records carry reason `upload_failed` and the existing
`lifecycle-worker` maintenance actor. Process kills still need orphan sweeping;
failed alias reservations keep existing retention/reuse behavior. Aggregate
admission, pending-byte accounting and issuance rate remain the next P2 slice.

Validation: full Garage/Postgres suite **395 passed, none skipped**; after adding
two HTTP contract cases, focused cleanup suite **18 passed**. Ruff lint/format,
strict mypy and whitespace checks pass. Existing upstream deprecation warnings
remain. No commit or deployment approval is implied.

## Bounded capability state (ADR-026, 2026-09-29)

FR-010..013/FR-050: a locked process-local store admits at most
`ASSET_STORE_MAX_CAPABILITIES` live tokens (default 10,000). Expired tokens and
consumed identifiers are retired lazily. A full store returns 503 without
evicting live grants; an audit failure publishes no bearer or granted metric.
The active-token gauge and capacity-denial counter expose saturation.
This bounds retained state, not issuance rate or audit growth. Restart still
invalidates tokens; atomic single-use check/use and replica support remain open.
M-001/P2 also still needs failed-write cleanup and aggregate admission limits.

Checkpoint validation: **379 tests passed, none skipped**, with local Postgres
and Garage; Ruff lint/format, strict mypy (72 files) and whitespace checks pass.
Two upstream TestClient deprecation warnings remain. The lead reviewed atomic
capacity admission, no eviction of live grants, expiry denial and audit-failure
publication safety. No deployment or broader security release approval is claimed.

## Outbound connection validation (SEC-05, 2026-09-29)

[Design and evidence](security/SEC05_OUTBOUND_CONNECTIONS.md): validated numeric
connections preserve origin Host/TLS identity, reject mixed/private/translation
answers and revalidate new redirect connections. Baseline full suite: 366 passed;
three further delegated transport regressions pass. DNS race closed; M-001/P2
resource bounds and the pilot facade remain outstanding.

## Postgres transaction isolation (SEC-02, 2026-09-28)

[Design, configuration and acceptance evidence](security/SEC02_TRANSACTION_ISOLATION.md):
bounded psycopg pool, synchronous units of work, reentrant asset locks, retryable
checkout overload, transaction metrics and app-owned shutdown (ADR-023). Concurrent
HTTP rollback isolation is verified for durable asset, quota and audit state.
Full suite: **354 passed** with Garage/Postgres; lint, types, locked image build
and runtime vulnerability scan pass. Next security target: SEC-05 DNS/egress.

## Security checkpoint (B-018, 2026-09-27)

[Bounded fixes and remaining work](security/B018_CLOSEOUT.md): authenticated raw
registry routes and verified commits, explicit development credentials, fetcher
ingress authentication, non-public IP rejection, bounded upload bodies, bearer
redaction and patched locked dependencies are implemented (ADR-022, commit `acc445e`). The subsequent ADR-023 change closes shared Postgres transactions; ADR-025 closes the DNS race; resource limits and atomic single-use consumption remain open. This is a stable prototype checkpoint, not release approval.

### Historical review (2026-09-26)

[Review and remediation plan](security/B018_REVIEW.md) against `9640116`:
STRIDE, code/configuration review, 3,600 generated scope/path checks, isolated
HTTP/Postgres/Garage probes, and a locked-runtime dependency audit. Confirmed
anonymous registry mutation/actor spoofing, acknowledged changes lost through
shared-connection rollback, predictable default admin credentials, unauthenticated
fetcher writes, retained bytes after quota rejection, live bearer audit storage
and still-valid presigned reads after registry expiry. SSRF transport/predicate
gaps and process-local capability limits are also recorded with evidence limits.

The dependency audit reports three advisories for AnyIO 4.14.1 (patched in
4.14.2); vulnerable API use was not demonstrated in this application. No code or
dependency fix was made during the review. Operator documentation now qualifies
presigned-URL revocation. Review performed does **not** mean security-ready:
At that baseline SEC-01..10 were open; the checkpoint above supersedes their
status. No risk acceptance was granted.

## Admin milestone (B-013, 2026-09-26)

The [admin console](services/admin-ui.md) is served at `/admin` by the existing
FastAPI process. Its authenticated API supports keyset-paginated, filtered asset
listings (including purged metadata), partition quota usage, metadata inspection,
bounded recent audit queries, revision-checked lifecycle/annotation/alias changes,
TTL restoration with quota checks and bounded bulk-expiry preview/apply. Quota
configuration emits before/after audit. PostgreSQL filters/paginates in SQL.

Legacy administrative routes now also require the admin service credential and
reject spoofed body caller identities. Credentials stay in page memory, rendering
uses text nodes (no HTML injection), and the page has a restrictive CSP. This does
not complete B-018: user→prefix trust, per-human attribution and deployment
posture remain open after the subsequent control-plane hardening. The in-memory adapter and process-local capability concurrency limits
remain; Postgres transactions are isolated by ADR-023. No production scale claim is made.

New critical paths emit admin action counters and structured action/outcome logs.
Mutations use registry transactions and existing asset row locks. Alias changes
now advance Postgres asset revisions consistently; an in-memory alias metadata
bug that doubled an already supplied partition prefix is fixed.

Validation: **326 tests passed**, none skipped, with Garage/Postgres enabled;
Ruff lint/format, strict mypy and JavaScript syntax checks pass. Wheel packaging
was checked to include all three console static assets. Browser visual
and interaction acceptance remains **pending**: the available browser tool
reported no connected browsers. HTTP tests verify static delivery, auth, CSP,
SCN-004 actions, stale revisions, quota restoration, durable history and bounded
bulk expiry. No operator data was changed by tests.

No new migration is required beyond B-014's migration 0002. Per-partition tmp
TTL defaults are explicitly tracked under Q-036, rather than silently added to
the quota model. Browser QA should be completed before closing B-013 acceptance.

## Lifecycle milestone (B-014, 2026-09-26)

The [lifecycle worker](services/lifecycle-worker.md) now previews or applies
TTL expiry, pending-orphan cleanup, expired payload deletion after grace, and
size/age-based pressure/quota eviction. It preserves exemptions and protects
users/results from automatic capacity eviction. It also collects payloads of
administratively deleted assets. Retention metadata survives restarts; new tmp
and results assets receive bounded default deadlines, with per-reservation hints.

Safety: cleanup commits a deleted-state fence before deleting bytes, then records
a purge marker; retries are safe after storage failure or interrupted metadata
updates. Postgres row locks coordinate cleanup with guarded uploads. Tests verify
cross-connection lock/recheck behavior. A zero-alias expiry accounting bug is fixed
and migration 0002 repairs existing counters. Expired reads now return 410,
deleted reads 404; new presigned URLs are capped by asset lifetime. Direct S3
reads are approximated by presigned issuance in access statistics.

Configuration and the migration/runbook are in the lifecycle contract. Dry-run is
the default; tests applied cleanup only to isolated/disposable data. Metrics and
JSON logs are implemented; Prometheus alert rules are supplied but must be wired
into the deployment. This trusted worker has direct database/S3 access; no public
cleanup endpoint or new caller capability was added. Existing control-plane
security hardening remains B-018. The in-memory adapter remains single-threaded.

Validation: **303 tests passed, none skipped** with Garage/Postgres enabled,
including migration backfill/downgrade, actual CLI dry-run/apply and metrics,
access/TTL behavior, exemption/scoring, stale candidates and failed-delete retries.
Ruff lint/format and strict mypy pass. Existing Starlette/httpx test deprecation
warning remains. Capacity is an estimate over registered committed bytes; pending
bytes/unregistered objects are excluded. Scale/load certification remains B-015.

## Worker simulator milestone (B-012, 2026-09-25)

The [worker-sim CLI](../tools/worker-sim/README.md) implements SCN-002/005 with
trusted JSON task inputs, checksum-verified reads, deterministic result copies,
and a completion manifest uploaded last (ADR-019). The simulator mints scoped
capabilities as the worker service to model dispatch; it does not implement a task
engine. JSON events and summary counters/latencies include a correlation id that
is propagated to asset-store; existing service metrics and audit cover the calls.

Security review: only worker identity is used, inputs are verified against task
SHA-256 values, writes are confined to a validated result prefix, and secrets are
read from the environment. CLI logs omit tokens, aliases and response bodies.
The existing service policy limits buckets but does not authenticate an end-user
partition owner; trusted task dispatch remains an upstream responsibility.

Validation: **272 tests passed, none skipped**, with Garage/Postgres enabled,
including 39 worker test cases; Ruff lint/format and strict mypy passed. Real
backends use isolated test schemas; HTTP app calls use TestClient. This validates
behavior, not deployment topology or NFR load/latency targets (B-015). The existing
Starlette/httpx deprecation warning remains.

Known limits: 50 MiB per input; no automatic write retry or capability refresh;
partial outputs remain after failure. B-014 now provides result TTL defaults and
API hints, cleanup, and the specified 410 expired-read response. The simulator
uses the service default result TTL; its task format has no separate TTL option.

## Fetcher milestone (B-020, 2026-09-25)

Real outbound HTTP, TOML URL rules and cache/tmp ingestion are implemented.
Forced refetch compares SHA-256 before any write: equal bytes reuse the existing
asset; different bytes return 409 and emit `fetch.checksum_mismatch` plus
`fetcher_refetch_checks_total{bucket,outcome}` at `/metrics` (ADR-018, R-011,
FR-022). Existing aliases, bytes, quota usage and registry audit remain unchanged.
The client percent-encodes alias paths, including query-derived alias characters.
`httpx` is now a runtime dependency, so the installed fetcher works without dev extras.

Security review for this slice: no additional capability permissions or mutable
alias operations; mismatch warnings omit origin URLs/credentials/alias text.
The existing prototype DNS-rebinding limitation and service-auth posture remain.
No background audit scheduler or automatic cache refresh is introduced.

Validation on 2026-09-25 (Python 3.13.2): **233 tests passed, none skipped** with
Garage and Postgres enabled; Ruff lint/format and strict mypy passed. The suite
reports an existing Starlette/httpx deprecation warning. See the
[integration recipe](../deploy/compose/README.md#fetcher-integration-test-b-020).

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

FR-010–FR-015 remain the production contract; capability checks live in `StorageGuard`, while raw registry routes enforce service identity, bucket permissions and commit ownership (ADR-022). Capabilities are still **unsigned** in this slice — minted ids act as opaque bearer tokens held in an in-process store (ADR-003 proxy mode). A **presigned mode** is also available for reads: `GET /objects/{alias}?mode=presign` returns a short-lived S3 presigned GET URL instead of proxying bytes (see below). Signed capability tokens remain deferred.

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
  `min(expires_in, 3600, capability remaining lifetime, asset remaining lifetime if set)` so a URL never outlives the
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
  when the env var is unset, explicit `ASSET_STORE_DEV_MODE=1` enables a
  **dev-default** store mapping known ids to `dev-secret:<id>` (`dev_secret(id)`).
  Compose and tests enable this mode; other unconfigured startup fails.
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
| Heritage-specific fetch + cache policy | **No** | Implemented fetcher-service |

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
