# Global Workplan

## Objective

Deliver a deployable, testable, monitored prototype of the **`asset-store`** module along the "compose" architecture recommended in [`spec/A_OSS_SURVEY.md`](spec/A_OSS_SURVEY.md), with a clear path from prototype to production.

The plan below is aligned with `ADR-001 = OVH S3 (hosted) + Garage (self-hosted), MinIO disqualified`, `ADR-002 = compose`, `ADR-003 = hybrid capability mode` (all provisional pending Phase 0 spikes). If a spike reverses one of these ADRs, the Phase 1+ tasks adapt but the phase boundaries do not.

Each phase has explicit exit criteria mapped to `FR-*`/`NFR-*`/`S-*` IDs from [`spec/01_SCOPE.md`](spec/01_SCOPE.md) and [`spec/02_REQUIREMENTS.md`](spec/02_REQUIREMENTS.md). Backlog IDs (`B-*`) come from [`spec/05_BACKLOG_AND_OPEN_QUESTIONS.md`](spec/05_BACKLOG_AND_OPEN_QUESTIONS.md).

## Current milestone — M-001 private Gallica IIIF cache pilot

The current delivery goal is a **Gallica IIIF image cache on asset-store, deployed privately
on one host with one process per application service**. Follow the
[practical pilot plan](milestones/PRIVATE_CACHE_PILOT.md): SEC-05 → resource bounds
→ preload/read cache API → private Compose deployment → recovery/operations → pilot
acceptance. Existing core implementations are reused. This sequence takes priority
over the broad phases below for this milestone; their production requirements
remain on the backlog. Full Swarm/HA and full-scale load certification are deferred,
not marked complete. Separate preload/cache-only reads are confirmed; read-through
on a miss is explicitly deferred as **B-025**. P1 / SEC-05 is implemented and reviewed. P2 implementation is complete. P3 implementation and local origin/smoke evidence are complete. Next: P4 local deployment is running; remaining acceptance and P5 operations are next.

## Current state (2026-10-01)

- B-009/B-010: durable Postgres registry, migrations, authenticated capabilities,
  guarded uploads and presigned reads are implemented, with Garage/S3 storage.
- B-011: bulk-loader CLI is implemented.
- B-020: fetcher MVP is complete: real HTTP with SSRF checks, TOML alias rules,
  cache/tmp ingestion, and forced-refetch checksum detection. Matching bytes reuse
  the asset; mismatches return 409 without changing stored data. A Prometheus
  counter and structured warning expose mismatches (ADR-018, R-011, FR-022).
- `tests/test_fetcher_garage.py` exercises a real local HTTP origin, Garage bytes,
  and an isolated Postgres schema through the HTTP app contracts. It checks cache
  hits, equal/changed refetches, origin failure, quota/audit preservation and a
  reopened registry. HTTP app calls use TestClient; this is not a deployment test.
- Quality tooling and CI are configured; backend tests remain environment-gated.
- B-012: worker-sim is complete; verified reads, result copies and manifest-last
  publication pass against both in-memory and Garage/Postgres adapters (ADR-019).
- B-014: lifecycle sweeps, TTL defaults/hints, access tracking and physical-capacity
  gating are implemented. Dry-run is the default; explicit apply uses deletion
  fencing and retryable payload cleanup (ADR-020, migration 0002).
- B-013: admin console and authenticated API are implemented (ADR-021);
  browser acceptance found a disconnect cleanup defect, now fixed and verified in
  the workspace preview (2026-10-05). The owner approved this commit; pilot image update/recheck
  remain. See [acceptance evidence](acceptance/ADMIN_UI_LOCAL.md).
- B-018: [security review performed](security/B018_REVIEW.md); confirmed blockers
  and [bounded fixes completed](security/B018_CLOSEOUT.md), with remaining work
  tracked in the closeout backlog. SEC-01 / R-014 and SEC-02 / R-015 are closed
  for the reviewed defects. No risk acceptance or release sign-off.
- SEC-02: [pooled transaction isolation](security/SEC02_TRANSACTION_ISOLATION.md)
  implemented (ADR-023); 354 tests pass with Garage/Postgres, including concurrent
  HTTP rollback, quota, saturation and shutdown tests.
- SEC-05: [validated outbound transport](security/SEC05_OUTBOUND_CONNECTIONS.md)
  implemented (ADR-025); full baseline 366 tests plus three additional focused
  transport regressions accepted.
- ADR-026: bounded local capability storage, expiry retirement, retryable overload
  and audit-before-publication are implemented. Atomic single-use consumption
  remains open; issuance rate admission is delivered by ADR-030.
- ADR-031 / B-024: authenticated Gallica preload and cache-only reads are implemented,
  with exact-rendition aliases, redirect policy, scoped read-token renewal and telemetry.
  Local HTTPS origin tests cover Garage/Postgres and reopened applications; the
  HTTP smoke script verifies hashes and repeated preload reuse over a real socket.
- Current combined checkpoint: **519 tests pass**, none skipped, with Garage/Postgres;
  lint, formatting and strict typing checks pass.
- ADR-032: separate private Compose package and protected configuration preflight
  are implemented. The owner selected this machine. ADR-033 immutable local-image
  support and ADR-034 BnF v3/WebP are implemented; live HTTP smoke, container
  persistence and capability renewal pass. ADR-035 maps the owner-approved legacy
  full-image form to the current v3 canonical JPEG resource; other renditions stay
  independent. Local downloaded files differ slightly, so byte equivalence is not
  claimed. The [quickstart](PILOT_QUICKSTART.md) task/result example passed against
  deployed APIs with a scoped worker identity and 64 MiB local results budget.
  The owner assisted browser acceptance on 2026-10-05; the disconnect fix awaits
  pilot image update/recheck after this approved commit. Scheduled cleanup is disabled; admin,
  scanning, host disk controls and recovery/soak acceptance remain open.
  See [local deployment evidence](../deploy/pilot/LOCAL_DEPLOYMENT.md).
- **Next: M-001/P4 remaining acceptance and P5 operational recovery.** Swarm,
  operational dashboards, security hardening and load certification remain open.

### P2 incremental checkpoint (2026-10-01)

Failed proxy-upload cleanup is implemented (ADR-027): commit a deletion fence
before reclaiming bytes, preserve successful assets, and retry cleanup failures
through the existing lifecycle worker. Aggregate upload/fetch job admission is
implemented (ADR-028), with no-wait overload responses and cancellation-safe
worker completion. Durable exact-size upload reservations are implemented
(ADR-029, migration 0003), including retained physical estimates on failed cleanup.
Capability issuance rate admission is implemented (ADR-030), with bounded
per-identity token buckets and 429/refill responses. P2 engineering slices are
complete; P4/P5 resource/ingress configuration and pilot acceptance remain.

## Engineering quality bar

Non-negotiable for every PR, in service of a simple, clean, stable, well-tested
prototype:

- **Deeply tested:** every behaviour change ships with unit tests; every new
  control-plane path ships with an integration test. Keep the domain core
  infrastructure-free so it stays fast to test.
- **Simple:** prefer the smallest design that satisfies the linked `FR-*`/`NFR-*`.
  No speculative abstractions; one obvious way to do each operation.
- **Documented:** public functions and endpoints carry docstrings linking the
  requirement id; [`docs/IMPLEMENTATION_NOTES.md`](IMPLEMENTATION_NOTES.md) tracks
  code-vs-spec status.
- **Clean + stable:** `ruff`, `mypy --strict`, and the full test suite must pass
  locally and in CI before merge; no skipped tests on the base branch.

## Phase 0 - Spec & survey close-out

**Goal:** lock unknowns blocking the build; validate `ADR-001`/`ADR-002`/`ADR-003` via time-boxed spikes.

**Work items:**

- B-001 - assign owners/dates to Q-001..017; resolve Q-001/Q-002/Q-009/Q-013/Q-016.
- B-005 - Spike S-001: object-store baseline on Garage / OVH S3 (PUT/GET/multipart/presigned URLs/lifecycle). **In progress:** `S3ObjectStore` certified on Garage for PUT/GET/stat/delete + server-side `sha256` on PUT + transparent multipart upload (>= threshold, abort-on-failure) + presigned-GET; backend-native lifecycle still to exercise; OVH S3 tier pending real credentials.
- B-006 - Spike S-002: minimal `asset-registry` against the object store (Garage); SCN-001 dry-run with 1k assets. **Done (registry seam):** `PostgresAssetRegistry` (psycopg 3) now implements the full lifecycle/quota port at parity with the in-memory registry and is certified on Postgres 16 (cross-connection + across app restart). SCN-001 1k-asset dry-run remains.
- B-007 - Spike S-003: InvenioRDM compare; confirm compose path is the right choice for our requirements.
- B-008 - Spike S-004: Garage certified as the self-hosted backend. **In progress:** Garage v1.0.1 dev stack stood up and the `S3ObjectStore` adapter + full guarded HTTP data plane pass against it (`tests/test_s3_garage_integration.py`).

**Exit criteria:**

- All `Q-*` rows have owner + due date.
- Q-001, Q-002, Q-009, Q-013, Q-016 marked Resolved.
- ADR-001, ADR-002, ADR-003 status changed from Proposed to Accepted (or revised) in `spec/03_ARCHITECTURE.md`.
- Spike notes appended to `spec/A_OSS_SURVEY.md` section 7.

## Phase 1 - Foundations

**Goal:** create a minimal but production-shaped service skeleton matching the chosen architecture.

**Work items:**

- B-002 - Repository scaffold:
  - `services/asset-store/` (single Python/FastAPI deployable; internal `registry`, `capabilities`, `storage` modules; async, alembic migrations) per ADR-002.
  - `tools/bulk-loader/` (Python click CLI).
  - `tools/worker-sim/` (Python click CLI).
  - `tools/admin-ui/` (static SPA or HTMX; final pick at code time).
  - `deploy/compose/` (dev stack: object store (Garage) + Postgres + asset-store + admin-ui + observability sidecars).
  - `deploy/swarm/` (target Swarm stack file; mirrors compose with replica counts and Swarm secrets).
- B-003 - CI baseline (ruff, mypy, pytest, build, trivy image scan).
- B-004 - Observability skeleton (structured JSON logs, OpenTelemetry, Prometheus `/metrics`, sample Grafana dashboard).

**Exit criteria:**

- Green CI on the base branch.
- `docker compose up` in `deploy/compose/` brings up the local stack in under 2 minutes (target FR-072 / NFR-011); all services pass `/healthz` and `/readyz`.
- A no-op request can be traced end-to-end (logs, metric, trace span) in the local stack.

## Phase 2 - Core ingestion + retrieval (MVP write/read happy path)

**Goal:** deliver the end-to-end happy path for SCN-001, SCN-002, SCN-003 against the local stack.

**Work items:**

- B-009 - `asset-registry` MVP: extend the existing [`src/asset_store_core/`](../src/asset_store_core/) domain core with a Postgres-backed adapter + Alembic migrations + endpoints implementing FR-001..007; add the `eviction_policy`, `PartitionQuota`, and `BucketQuota` entities (FR-063..069) and close the known core gaps listed under "Current state". **Mostly done:** the durable `PostgresAssetRegistry` implements the full seam (reserve/commit/resolve, lifecycle, alias detach/rebind, two-tier quotas, eviction policy, audit) at parity with the in-memory registry, wired into the app factory via `ASSET_STORE_PG_DSN` and proven durable across an app restart on the compose stack. Schema is owned by an Alembic migration history under [`migrations/`](../migrations/) (`alembic upgrade head`), with runtime `CREATE TABLE IF NOT EXISTS` retained only as a dev/test convenience. Remaining (optional): SQLAlchemy ORM models — deliberately deferred, as the registry's explicit `FOR UPDATE`/upsert SQL is intentionally hand-written for concurrency correctness.
- B-010 - `storage-guard` MVP: service-identity auth + FR-010..014 + audit log + presigned URL minting. **Complete:** the capability broker now authenticates the calling service before minting (FR-014) via an `Authorization: Service <id>:<secret>` header backed by a `ServiceCredentialStore` (`ASSET_STORE_SERVICE_CREDENTIALS`; dev defaults require explicit `ASSET_STORE_DEV_MODE=1`, ADR-022), derives `caller_service_id` from that identity instead of the request body, and audits every issuance decision (`capability.issue`, granted/denied) in both registry backends (FR-050). Bucket allowlist (FR-015) and capability-guarded data plane (FR-010..013) already ship from B-002. **Presigned mode delivered (ADR-003):** `GET /objects/{alias}?mode=presign[&expires_in=…]` mints a short-lived presigned GET URL via `StorageGuard.presign_read` — TTL is capped by `min(request, 1h, capability remaining)`, single-use capabilities are refused (a presigned URL cannot be single-use), and the in-memory `LocalObjectStore` returns `PresignNotSupportedError → 501` (presign requires an S3 backend, certified on Garage). B-010 is complete.
- B-011 - `bulk-loader` CLI implementing SCN-001 against 10k assets. **Done:** a `click` CLI (`tools/bulk-loader/`) that authenticates as the `bulk-loader` service, mints one **write** capability scoped to `cache/{mirror_id}` (the capability model requires a bucket plus at least one segment, so a bare-bucket `cache/` scope is not representable; per-mirror still covers a whole run and FR-015 confines the service to `cache`), and streams each manifest row (`alias,mime,path` CSV) through the guarded `PUT /objects/{alias}` (server-side reserve->PUT->commit). Batch semantics are **best-effort per row** (Q-001 resolved): good rows commit and become resolvable, failed rows are reported (`alias,path,error`) with a non-zero exit; `--fail-fast` opts into stop-on-first-failure. The alias is the stable citation name `cache/{mirror_id}/{row-alias}` with **no batch-id in the path** (a per-run batch-id is only a correlation label, so re-runs resolve identically). Deviates from the SCN-001 sketch, which scoped the capability to `cache/{mirror}/{batch-id}/` — that prefix would not cover `cache/{mirror}/...` aliases. Covered by in-memory unit/contract tests plus a Garage-gated end-to-end test (bytes land in S3 and read back). Future admin/user attribution on top of the service identity is tracked as Q-030.
- **B-020 - `fetcher-service` (cache service) MVP** (SCN-007) — **Done (2026-09-25)**; previously prioritized ahead of B-012. `ensure_url`: given a remote URL, apply the URL->alias rewrite-rule set / cache allowlist (ADR-014, Q-021/Q-022), resolve the canonical `cache/{mirror_id}/…` alias if already present, otherwise fetch and ingest into `cache` (via the same write-capability + guarded data-plane path as the bulk-loader), and return the stable alias. Uses `tmp` for staging where needed. See [`services/fetcher-service.md`](services/fetcher-service.md). **Phasing (Q-023) resolved: in-repo service, HTTP+JSON to asset-store (ADR-017).** Delivered in two steps:
  - **Step 1 — fetcher stub (Done, 2026-07-09):** `ensure_url` control flow (normalize → rewrite rules incl. IIIF dedup → cache lookup → store), the `POST /v1/ensure-url` FastAPI app, and a no-network `SyntheticFetcher` (deterministic URL-derived JSON). `cache` hit/miss idempotency and `tmp` staging over the guarded proxy PUT. Code in [`src/fetcher_service/`](../src/fetcher_service/); tests in [`tests/test_fetcher_service.py`](../tests/test_fetcher_service.py).
  - **Step 2 — the cache (Done, 2026-09-25):** a **declarative rule-config language** (TOML `[[rule]]` array → `RuleSet`; `type` ∈ `iiif`/`passthrough`/`regex`, with a **safe-regex subset** — anchored named-group match/extract only, no backreferences/lookaround; semantic normalization stays in code) — **Done (2026-07-09)**, loaded via `FETCHER_RULES_FILE`. A real **`HttpFetcher`** (connect/read timeouts, max-body cap, redirect limit with per-hop SSRF re-validation, default-deny of private/loopback/reserved addresses; env-overridable via `FETCHER_HTTP_*` / `FETCHER_ALLOW_PRIVATE_HOSTS`; `FETCHER_SYNTHETIC` selects the stub) tested against a threaded loopback origin — **Done (2026-07-09)**. Delivered: checksum-mismatch **correctness detector** (R-011, ADR-018; fresh vs stored `sha256` on `no_cache`), and a Garage/Postgres-gated e2e. Background audit scheduling remains outside this slice. **Content-addressed (byte-identity) storage dedup dropped** — dedup is by canonical alias (name), so it adds little on top; full blob-level dedup is deferred, per-space opt-in (`Q-035`). **Multi-alias attachment dropped** — cross-URL dedup is achieved by canonical normalization to a **single** alias (ADR-014 amendment 2026-07-09); multi-alias binding deferred to the access-control use case (`Q-034`).
- B-012 - **Done (2026-09-25):** `worker-sim` Click CLI with JSON tasks, worker-scoped capabilities, SHA-256 verified proxy reads, deterministic result copies and manifest-last publication. Structured events and JSON counters/timing share a correlation id with asset-store. Failure tests cover partial outputs, missing/expired/denied reads, quotas, conflicting attempts, checksum/transport errors and manifest failure. See [`services/worker-sim.md`](services/worker-sim.md), ADR-019, and `tests/test_worker_sim.py`. Full suite: 272 passed with Garage/Postgres enabled; lint, format and strict typing pass. TTL enforcement is now delivered by B-014; performance certification remains B-015.
- B-014 - **Done (2026-09-26):** dry-run-first lifecycle CLI; pending-orphan fencing, TTL expiry, grace-period deletion, admin-deleted payload cleanup, quota/pressure sweeps using size-times-age scoring, exempt/user/results protections, metrics and audit. Asset TTL hints/defaults and bounded presigned URLs are implemented; expired/deleted reads return 410/404. Migration 0002 adds lifecycle/access metadata and repairs legacy orphan quota accounting. See [`services/lifecycle-worker.md`](services/lifecycle-worker.md), ADR-020, and `tests/test_lifecycle_worker.py`. Validation: 303 tests passed with Garage/Postgres, none skipped; lint/format and strict mypy pass. Admin TTL extension and bulk-expire-by-prefix are delivered by B-013; per-partition tmp TTL overrides remain a separate policy follow-up (Q-036), and independent alias deadlines remain deferred.

**Exit criteria:**

- SCN-001, SCN-002, SCN-003, SCN-005 acceptance tests green in CI on every PR.
- Capability scoping test suite (S-4) green - no cross-prefix access possible.
- Audit log entries present for all expected events (FR-050..052 acceptance).
- Read path returns p95 latency under 200 ms in-cluster on the local stack with one worker (NFR-002 sample).

## Phase 3 - Admin path, reliability, security

**Goal:** make the prototype operationally credible and safe.

**Work items:**

- B-013 - **Implemented; browser-tested 2026-10-05, fix awaiting deployment:** console at `/admin`,
  authenticated cursor listings/inspection/audit, revision-checked lifecycle and
  TTL restoration, aliases, annotations, quotas and bounded bulk expiry. Both
  registry adapters are covered. See [admin contract](services/admin-ui.md), ADR-021.
- B-018 - **Review performed (2026-09-26), remediation open:** STRIDE, isolated
  exploit probes, 3,600 generated capability/path checks and runtime dependency audit.
  SEC-01 and bounded hardening are complete (2026-09-27); SEC-02 pooled
  transaction isolation is complete (2026-09-28, ADR-023). See [closeout and follow-ups](security/B018_CLOSEOUT.md);
  readiness exit criteria remain open.
- Lifecycle hardening: capability issuance admission rate limits delivered (ADR-030); idempotency-key replay protection across services remains open.
- Backup hook for Postgres + a second S3 target (B-017) - design and basic implementation.
- Resolve Q-003, Q-005, Q-006, Q-010, Q-014, Q-017 (the Phase 2/3 batch of open questions).

**Exit criteria:**

- SCN-004 acceptance test green.
- All P0 alerts in `spec/04_OPERATIONS.md` configured against the local stack and firing on synthetic faults.
- Security-review findings either fixed or accepted with a `R-*` risk row.
- Backup of Postgres + object-store snapshot exercised; restore drill documented.

## Phase 4 - Load test, capacity, SLO baseline

**Goal:** measure against the non-functional targets and prove the SLO is achievable.

**Work items:**

- B-015 - Locust/k6 load tests for S-2 (30 concurrent readers) and S-3 (10k assets ingest).
- B-016 - Chaos suite: kill-one of each service; kill one object-store node.
- Capacity baseline run: ingest 100k assets to ~1 TB; measure read latencies, registry query times, object-store disk usage.

**Exit criteria:**

- SLO dashboard exists; error-budget burn-rate alerts configured.
- NFR-001 (capacity), NFR-002 (read latency p95), NFR-003 (mint latency p95), NFR-004 (concurrency), NFR-005 (durability canary) measured and within targets.
- Chaos suite passes: zero failed user-visible requests after retry.

## Phase 5 - Pilot readiness

**Goal:** validate the prototype in a controlled real workflow.

**Work items:**

- B-019 - Pilot plan + rollback rehearsal; success metrics defined.
- Documentation pass: runbooks `RUNBOOK-001..006` finalised in `docs/runbooks/`.
- Cost and performance report based on Phase 4 numbers.
- Go-live checklist sweep (from `spec/04_OPERATIONS.md`).

**Exit criteria:**

- Pilot sign-off checklist complete.
- Go/No-Go decision documented; remaining risks accepted in writing.

## Cadence And Governance

- Weekly architecture review: ADR changes, open questions, risk register.
- Twice-weekly delivery sync: backlog progress, blockers, risks.
- Single source of truth: `docs/spec/` and the ADR table.

## Owner-requested sequential acceptance work

Work one task at a time; commit and pause for owner resume between tasks.
For desktop/session reset, start with [the handoff](SESSION_HANDOFF.md).
Task 1: [browser acceptance and disconnect fix](acceptance/ADMIN_UI_LOCAL.md)
have been verified against the dedicated disposable fixture. The corrected UI was
verified in a temporary workspace preview against the pilot API; the running pilot
image remains unchanged. The owner approved this commit; deploy/recheck the
reviewed fix before closing task 1. No push; backup/restore has not started.

## Backup/restore follow-up (2026-10-05)

Owner resumed task 2; coherent cold backup and isolated restore passed (ADR-037).
All seven tables and six retained payloads match baseline; restored/original HTTP
cache-hit smoke passed. Original pilot is healthy; restore stack is stopped,
backup and restore volumes retained. See [evidence](BACKUP_RESTORE_REHEARSAL.md).
Daily/off-host backup operation, retention, rollback and browser recheck remain
open. Owner approved the evidence commit and requested a pause on 2026-10-06;
do not start task 3 until explicitly resumed.

## CLI deployment follow-up (2026-10-05)

The approved B-013 fix (`4bf46ba`) is now deployed through an immutable image
update. Preflight/migration/readiness, source identity, 10 Node regressions on
HTTP-downloaded client code and authenticated cache-hit smoke passed. See
[deployment evidence](../deploy/pilot/LOCAL_DEPLOYMENT.md#cli-image-update--2026-10-05).
The browser disconnect recheck remains pending; task 1 remains open. Pause before
backup/restore until explicit owner resume. Earlier undeployed status describes
the checkpoint before this update. Evidence changes are uncommitted; no push.

## Immediate next actions (2026-10-05)

1. **B-013 acceptance follow-up:** the owner approved committing the tested disconnect
   cleanup fix and browser evidence; apply via immutable pilot image update and
   recheck disconnect. Pause before task 2 until explicitly resumed by the owner.
2. **M-001/P4–P5:** review scans and remaining UI/operating controls, then rehearse
   backup/restore and rollback on the running local
   [Compose package](../deploy/pilot/README.md); follow
   the [closeout backlog](security/B018_CLOSEOUT.md) for deployment, DNS/egress,
   resource cleanup and capability concurrency work.
3. Operational deployment, alert wiring and B-015 performance certification remain;
   completed prototype milestones do not imply production readiness.

## Phase Dependency Diagram

```mermaid
flowchart LR
    P0[Phase 0<br/>Spec & spikes]
    P1[Phase 1<br/>Foundations]
    P2[Phase 2<br/>Core MVP]
    P3[Phase 3<br/>Admin + security]
    P4[Phase 4<br/>Load + SLO]
    P5[Phase 5<br/>Pilot]

    P0 --> P1
    P1 --> P2
    P2 --> P3
    P3 --> P4
    P4 --> P5
```

## Task 3 CLI follow-up — 2026-10-06

Owner resumed monitoring/retention/cleanup in CLI, leaving browser recheck pending.
Live dry-run found zero candidates/errors; existing lifecycle schedule enabled.
Private minute CLI health monitor and conservative retention policy implemented
(ADR-038). See [task 3 operations/evidence](TASK3_OPERATIONS.md). Docker filesystem
is near 10% free-space warning; disk, off-host backup and remote-alert gates remain
open. No audit/backup purge. Review/commit this task, then pause before task 4;
no push.

## Task 4 CLI follow-up — 2026-10-06

Owner resumed task 4. Deployed/current/prior image scans reviewed (Trivy 0.75.0),
exact app-runtime pip-audit performed, application-only rollback/return rehearsal
passed (ADR-039). All six retained payloads and stable metadata match; backend
containers/schema unchanged, lifecycle resumed and monitor healthy. See [task 4](TASK4_SECURITY_ROLLBACK.md).
High/Critical findings and Garage build-inventory coverage remain security gates;
no dependency/backend upgrades or risk acceptance inferred. No commit/push yet.
Pause before task 5; explicit owner approval required.
