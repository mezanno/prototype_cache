# 01 - Scope and Scenarios

> Terms and acronyms: [`README.md` glossary](README.md#glossary-and-acronyms)

## At a glance

| Module | Responsibility |
|--------|----------------|
| **asset-store** | Store bytes, aliases, lifecycle, capabilities, audit |
| **fetcher-service** | Fetch remote URLs → write `cache` or `tmp` ([`../services/fetcher-service.md`](../services/fetcher-service.md)) |
| **upload-api** | User uploads → `users` (and staging in `tmp`) |
| **workers** | Read by alias; write results → `results` |

**asset-store does not perform outbound HTTP.** Remote ingestion is fetcher's job.

**Four object-store buckets (MVP):** `cache`, `tmp`, `users`, `results`. Optional `iiif_server_cache` is owned by the IIIF server, not asset-store.

---

## Problem Statement

Heritage- and document-processing services need a single durable pivot for all binary content flowing through the platform: images fetched from heritage institutions, end-user uploads, and worker artifacts (intermediate and final). The current ad-hoc storage approach mixes concerns (fetching, caching, processing, serving) and prevents fine-grained access control, audit, and quota management. The `asset-store` module solves this by providing a multi-tenant blob store with logical aliases, lifecycle management, and short-lived prefix-scoped access tokens, so that every other module (upload API, fetcher, workers, future IIIF server, future task API) can rely on a single contract for storing and retrieving content.

## In Scope (MVP)

- **Object storage** of binary payloads (any MIME type) on an S3-compatible distributed backend with **four buckets**: `cache`, `tmp`, `users`, `results` (see [`03_ARCHITECTURE.md`](03_ARCHITECTURE.md)).
- **Asset registry**: unique `asset_id`, one or more **aliases** per asset, metadata including `space` (bucket), `partition_id`, MIME, size, checksum, lifecycle state (`pending`, `available`, `expired`, `deleted`).
- **Alias namespace** per bucket (`space`); qualified alias `{space}/{partition_id}/…`; unique within `space`.
- **Multipart / resumable upload** for payloads up to 5 GB.
- **Storage guard**: service-identity auth; bucket allowlists ([`FR-015`](02_REQUIREMENTS.md)); prefix-scoped capabilities; per-partition quota hooks ([`Q-004`](05_BACKLOG_AND_OPEN_QUESTIONS.md)).
- **Audit log**, **admin UI/API**, **bulk-loader**, **worker-sim**, **observability**, **deployment** (Compose + Swarm), **backup hook** (design).

## Out Of Scope (Explicit)

- **Image processing** of any kind.
- **Remote URL fetching by asset-store** — delegated to **fetcher-service** ([`../services/fetcher-service.md`](../services/fetcher-service.md)).
- **IIIF Image API or Presentation API serving** — separate IIIF-server module.
- **IIIF manifest composition** — future `manifest-service`.
- **`iiif_server_cache` bucket** — tile/cache storage managed by IIIF server directly, not via asset-store APIs.
- **IIIF manifest relaying or rewriting** — `iiif-image-mirror` covers IIIF Image API only and must not relay or rewrite Presentation manifests; this is a firm constraint.
- **End-user authentication** — upstream APIs; asset-store sees service identities only.
- **Task orchestration**, **billing**, **virus scanning** (caller's duty), **format conversion**, **cross-region replication**, **encryption at rest** in MVP (`R-*`).

## Users And Integrators

### Service identities (asset-store MVP)

| Service | Typical buckets | Role |
|---------|-----------------|------|
| **fetcher** | read/write `cache`, `tmp` | Materialize remote URLs ([`../services/fetcher-service.md`](../services/fetcher-service.md)) |
| **upload-api** | read/write `users`, `tmp` | End-user uploads |
| **bulk-loader** | read/write `cache` | Bulk preload |
| **worker** | read `cache`, `users`, `tmp`; write `results` | Process tasks |
| **task-api** | read `cache`, `users`, `tmp`; write `tmp` | Task defs; calls fetcher for URLs |
| **admin** | all MVP buckets | Operations |

### Surveyed for later

- **IIIF server** (`iiif-server`) — read `cache`, `users`; own `iiif_server_cache` tile bucket; no writes to asset-store. See [service identity table](03_ARCHITECTURE.md).
- **IIIF image mirror** (`iiif-image-mirror`) — future separate end-user-facing module; serves heritage images via IIIF Image API with its own access-control layer; delegates all cache writes to fetcher-service; reads `cache` only from asset-store; must not relay or rewrite Presentation manifests. Tracked as [`B-021`](05_BACKLOG_AND_OPEN_QUESTIONS.md).
- **manifest-service** — composes manifests; may store JSON snapshots as assets.
- **storage-guard policy provider** — external ABAC.

## Inputs

| Mode | Path into system |
|------|------------------|
| Direct PUT | Caller holds write capability → object-store → commit |
| Multipart | Same, native S3 multipart |
| Bulk import | bulk-loader → `cache/{mirror_id}/…` |
| Remote URL | task-api/orchestrator → **fetcher** → `cache` or `tmp` |
| User file | upload-api → `users/{userid}/…` |

**Not supported:** asset-store initiating HTTP to remote origins.

Hard limits: max object 5 GB; any MIME; per-alias TTL; default infinite except `tmp` ([`Q-020`](05_BACKLOG_AND_OPEN_QUESTIONS.md)).

## Outputs

- JSON API responses; signed URLs / tokens.
- Opaque `asset_id`; **aliases** as stable references (not object keys).
- Metadata minimum: `asset_id`, `space`, `partition_id`, `storage_key`, `aliases[]`, `mime`, `size_bytes`, `checksum`, `state`, timestamps, `annotations`, `owner_service_id`.
- Audit events; metrics (per bucket and per partition where applicable).

## Success Criteria (Measurable)

1. **S-1 Capacity**: 1 TB, ≥100 000 assets on dev stack.
2. **S-2 Concurrency**: 30 workers × 1–2 MB/s reads, p95 &lt; 200 ms, zero read errors (5 min).
3. **S-3 Ingestion**: bulk-loader 10k × 1 MB in &lt; 30 min, checksums verified.
4. **S-4 Capability scoping**: capability for `users/42/uploads/` cannot access `users/43/…` or other buckets; cross-bucket denied ([`FR-015`](02_REQUIREMENTS.md)).
5. **S-5 Audit completeness**: capabilities, lifecycle, admin actions logged.
6. **S-6 Observability**: dashboards per bucket/partition; alerts on SLIs.
7. **S-7 Deployability**: Compose up &lt; 2 min; Swarm stack works.
8. **S-8 Recoverability**: single service kill → retry succeeds.

Linked to `FR-*` / `NFR-*` in [`02_REQUIREMENTS.md`](02_REQUIREMENTS.md).

---

## Scenarios (SCN-*)

Remote URL flows use **fetcher-service** ([`services/fetcher-service.md`](../services/fetcher-service.md)). asset-store never calls HTTP. Out-of-scope scenarios (IIIF tile cache, visualization) remain in [`_archive/00A_USE_CASES_AND_SCENARIOS.md`](_archive/00A_USE_CASES_AND_SCENARIOS.md).

### Scenario index

| ID | Title | Priority | Buckets involved |
|----|-------|----------|------------------|
| SCN-001 | Bulk preload | P0 | `cache` |
| SCN-002 | Worker read | P0 | any (via alias) |
| SCN-003 | User upload | P1 | `users` |
| SCN-004 | Admin lifecycle | P1 | any |
| SCN-005 | Worker writes results | P1 | `results` |
| SCN-006 | Task inline payload to tmp | P1 | `tmp` |
| SCN-007 | Remote URL via fetcher | P0 | `cache` or `tmp` |
| SCN-008 | IIIF server reads asset | P2 (future) | `cache`, `users` |
| SCN-009 | OCR task: remote IIIF URLs → fetch → results | P2 (illustrative) | `cache`/`tmp` + `results` |

### Actor catalog (MVP)

- **Bulk-loader** - CLI; bulk-ingests into `cache/{mirror_id}/`.
- **Fetcher** - platform service; `ensure_url` → `cache` or `tmp`.
- **Upload API** - end-user uploads → `users/{userid}/`.
- **Task API** - task inputs; calls fetcher for URLs; may write `tmp/{tmpid}/`.
- **Worker** - reads by alias; writes `results/{taskid}/`.
- **Admin** - operator via admin-ui.
- **Storage-guard**, **Asset-registry**, **Object-store** - asset-store modules.

### Scenario template

```md
#### SCN-XXX - <short title>

- **Priority:** P0 / P1 / P2
- **Actors:** ...
- **Maps to:** FR-..., NFR-...
- **Preconditions:** ...
- **Trigger:** ...
- **Main flow:** ...
- **Expected result:** ...
- **Error/failure paths:** ...
- **Observability checks:** ...
- **Open questions:** Q-*
```

### Initial scenarios

#### SCN-001 - Bulk preload image set

- **Priority:** P0
- **Actors:** Bulk-loader, storage-guard, asset-registry, object-store
- **Maps to:** FR-001, FR-004, FR-011, FR-015, FR-020, FR-021, FR-022, FR-050, NFR-001, NFR-005
- **Preconditions:** Manifest lists aliases under `cache/{mirror_id}/…`, MIME, local paths. Bulk-loader credential allows write `cache` only.
- **Trigger:** `bulk-loader --manifest=batch.csv --mirror-id=gallica`
- **Main flow:**
  1. Bulk-loader requests write capability scoped to `cache/gallica/{batch-id}/` (TTL 1 h).
  2. Guard authorizes (`FR-015`), reserves aliases `pending` (`FR-004`).
  3. Per item: PUT to bucket `cache`, key `{gallica}/assets/{asset_id}`; commit (`FR-022`).
  4. Summary: N ok, M failed, bytes, elapsed.
- **Expected result:** Assets `available`; aliases like `cache/gallica/bnf/ark-…/default.jpg` resolvable.
- **Error/failure paths:** bad manifest row; upload retry; capability re-issue; checksum mismatch → rollback.
- **Observability checks:** ingest counters, latency, bytes per `partition_id=gallica`.
- **Open questions:** Q-001, Q-002.

#### SCN-002 - Worker reads an asset for processing

- **Priority:** P0
- **Actors:** Worker, storage-guard, asset-registry, object-store
- **Maps to:** FR-002, FR-010, FR-012, FR-030, FR-031, FR-050, NFR-002, NFR-004, NFR-008
- **Preconditions:** Asset `available`. Worker holds read capability for the task alias prefix.
- **Trigger:** Worker starts task.
- **Main flow:**
  1. `GET /resolve?alias=…` with capability.
  2. Guard validates scope (`FR-012`); registry resolves; presigned GET for correct bucket + key.
  3. Worker downloads payload.
- **Expected result:** Correct bytes; checksum sample (`NFR-005`); latency `NFR-002`.
- **Error/failure paths:** 404/410/403/5xx; capability refresh via orchestrator.
- **Observability checks:** read latency, error rate by cause.
- **Open questions:** Q-003.

#### SCN-003 - User upload through Upload API

- **Priority:** P1
- **Actors:** Upload API, storage-guard, asset-registry, object-store
- **Maps to:** FR-001, FR-004, FR-011, FR-013, FR-015, FR-020, FR-021, FR-022, FR-050, NFR-002
- **Preconditions:** User `42` authenticated upstream. Upload-api may write `users` and `tmp`.
- **Trigger:** User uploads file via web app.
- **Main flow:**
  1. Single-use write capability for `users/42/uploads/{suffix}` (`FR-013`).
  2. Reserve alias `pending`; PUT to bucket `users`, partition `42`.
  3. Commit with checksum/MIME; state `available`.
  4. Return `asset_id` + alias.
- **Expected result:** Immutable alias under `users/42/…` for downstream tasks.
- **Error/failure paths:** timeout; 413; checksum mismatch.
- **Observability checks:** upload throughput by `partition_id=42`.
- **Open questions:** Q-004, Q-005.

#### SCN-004 - Admin lifecycle operation

- **Priority:** P1
- **Actors:** Admin, admin-ui, storage-guard, asset-registry, object-store
- **Maps to:** FR-005, FR-006, FR-007, FR-040, FR-041, FR-042, FR-050, FR-051, FR-052, NFR-009
- **Preconditions:** Admin credential; target asset exists.
- **Trigger:** Admin expires/deletes asset or edits annotations in `admin-ui`.
- **Main flow:** List/filter by `space`, `partition_id`, alias prefix → inspect → lifecycle action → audit.
- **Expected result:** Durable state change; 410/404 on resolve as appropriate.
- **Error/failure paths:** optimistic conflict; 409 on duplicate alias attach.
- **Observability checks:** admin action counters.
- **Open questions:** Q-006, Q-007 (system `cache` bucket).

#### SCN-005 - Worker writes result artifacts

- **Priority:** P1
- **Actors:** Worker, storage-guard, asset-registry, object-store
- **Maps to:** FR-001, FR-003, FR-004, FR-011, FR-013, FR-015, FR-021, FR-022, FR-050, FR-069, NFR-005
- **Preconditions:** Write capability scoped to `results/42/987/attempt-1/worker-3/` (where `42` is the `userid`; task-api embeds this transparently; anonymous tasks use `anon` as `partition_id`).
- **Trigger:** Worker commit-results stage.
- **Main flow:**
  1. For each output: reserve alias under scope; PUT to bucket `results`, partition `42` (userid).
  2. Commit each; upload manifest JSON last.
- **Expected result:** Bundle discoverable via manifest alias.
- **Error/failure paths:** partial upload; manifest marker pattern (`Q-008`).
- **Observability checks:** artifact + manifest success rates.
- **Open questions:** Q-008.

#### SCN-006 - Task inline payload staged in tmp

- **Priority:** P1
- **Actors:** Task API, storage-guard, asset-registry, object-store
- **Maps to:** FR-001, FR-004, FR-011, FR-015, FR-020, FR-022, FR-050
- **Preconditions:** Task carries inline/base64 payload (not a cacheable URL). Task-api may write `tmp`.
- **Trigger:** Task registration stores input material before worker start.
- **Main flow:**
  1. Task-api obtains write capability for `tmp/{tmpid}/`.
  2. Reserve alias `tmp/{tmpid}/input-{n}`; PUT; commit with short TTL hint.
  3. Task definition references qualified alias for worker.
- **Expected result:** Worker reads via SCN-002; `tmp` GC reclaims after TTL (`Q-020`).
- **Error/failure paths:** same as upload path.
- **Observability checks:** `tmp` bucket growth rate.
- **Open questions:** Q-020, Q-024.

#### SCN-007 - Remote URL materialized by fetcher

- **Priority:** P0
- **Actors:** Task API, fetcher, storage-guard, asset-registry, object-store
- **Maps to:** FR-002, FR-010..015, FR-020, FR-022, FR-050; fetcher contract in [`services/fetcher-service.md`](../services/fetcher-service.md)
- **Preconditions:** Task includes remote URL. Fetcher credential allows `cache` + `tmp`. Domain policy configured (`Q-022`).
- **Trigger:** Orchestrator calls `POST /v1/ensure-url` on fetcher before worker dispatch.
- **Main flow:**
  1. Fetcher normalizes URL; derives cache alias candidates under `cache/{mirror_id}/`.
  2. **Cache hit** (and not `no_cache`): resolve existing alias → return `asset_id`, `cache_hit=true`.
  3. **Miss:** HTTP GET remote; if domain cacheable → write `cache/{mirror_id}/…`; else → `tmp/{tmpid}/…`; commit via guard.
  4. Return qualified alias to task-api for task definition.
  5. Worker later reads via SCN-002 (never hits remote origin).
- **Expected result:** Idempotent `ensure_url` for same URL returns same alias on second call (cache hit).
- **Error/failure paths:** upstream 502/504; SSRF blocked; guard 403 if fetcher misconfigured.
- **Observability checks:** `fetch_cache_hit`, `fetch_remote_errors`, bytes to `cache` vs `tmp`.
- **Open questions:** Q-021, Q-022, Q-023.

#### SCN-008 - IIIF server reads a stored asset

- **Priority:** P2 (future; IIIF server not in MVP)
- **Actors:** IIIF server, storage-guard, asset-registry, object-store
- **Maps to:** FR-002, FR-010, FR-012 (read path); IIIF server integration surveyed for later in this document (Users And Integrators)
- **Preconditions:** Asset `available` under `cache/{mirror_id}/…` or `users/{userid}/…`. IIIF server holds read capability for the relevant prefix.
- **Trigger:** IIIF client requests an image (IIIF Image API).
- **Main flow:**
  1. IIIF server resolves the alias via storage-guard (same read-capability flow as workers, SCN-002).
  2. Storage-guard validates scope; registry resolves; returns presigned GET for the correct bucket + key.
  3. IIIF server streams bytes to the IIIF client (tile generation is internal to the IIIF server).
  4. Derived tiles are written to `iiif_server_cache` — that bucket is owned by the IIIF server, not asset-store.
- **Expected result:** IIIF client receives image data; no writes to asset-store.
- **Error/failure paths:** 404/410 if asset not found or expired; 403 if capability does not cover the alias.
- **Observability checks:** read latency; error rate; no write audit events from `iiif-server` identity.
- **Open questions:** [`Q-025`](05_BACKLOG_AND_OPEN_QUESTIONS.md) (IIIF server integration phasing).

#### SCN-009 - OCR task submission with remote IIIF image URLs (end-to-end)

- **Priority:** P2 (illustrative; the task-api / processing steps are **out of asset-store scope** — this scenario shows how the asset-store is *used* end-to-end)
- **Actors:** Authenticated user, task-api (out of scope), fetcher, storage-guard, asset-registry, object-store, Worker
- **Maps to:** composite of SCN-007 (remote fetch), SCN-005 (results write), SCN-002 (worker read); FR-001..004, FR-010..015, FR-069
- **Preconditions:** User authenticated upstream; selects pages and an OCR endpoint without forward-auth credentials; domain policy configured (`Q-022`).
- **Trigger:** User runs "Run OCR" over N remote IIIF page URLs.
- **Main flow (asset-store touchpoints only):**
  1. Task-api validates the user/team/project token and the request payload (out of asset-store scope).
  2. For each remote page URL, task-api calls the fetcher (`SCN-007`): a **publicly-cacheable** domain lands in `cache/{mirror_id}/…`; a **non-cacheable** URL lands in the user's `tmp/{tmpid}/…` staging. Either way the worker later reads a local alias, never the origin.
  3. Task-api provisions a result prefix `results/{userid}/{taskid}/attempt-1/` with read-for-user / append-for-worker semantics (`SCN-005`, FR-069).
  4. Worker reads inputs by alias (`SCN-002`) and writes outputs under the result prefix (`SCN-005`).
- **Expected result:** Re-running with the same cacheable URLs reuses cached assets (idempotent `ensure_url`); the user can read results but not mutate them.
- **Error/failure paths:** fetch failure (`502`/`504`) aborts before worker dispatch; non-cacheable remote falls back to `tmp`; capability `403` if any identity is mis-scoped.
- **Observability checks:** `fetch_cache_hit`, bytes to `cache` vs `tmp`, result write success rate.
- **Open questions:** Q-021, Q-022, Q-030; capability verb granularity (`Q-032`).

### Cross-scenario decisions

- **Storage layout** — ADR-007; four buckets + `partition_id`.
- **Remote fetch** — ADR-008; fetcher only.
- **Identifiers** — ADR-004; opaque `asset_id` + aliases.
- **Mutability** — ADR-005; FR-008.
- **Capabilities** — ADR-003; FR-010..015.

### Acceptance mapping

- **SCN-001** → FR-001, FR-004, FR-011, FR-015, FR-020/021/022, FR-050, NFR-001, NFR-005
- **SCN-002** → FR-002, FR-010, FR-012, FR-030/031, FR-050, NFR-002, NFR-004, NFR-008
- **SCN-003** → FR-001, FR-004, FR-011, FR-013, FR-015, FR-020/021/022, FR-050, NFR-002
- **SCN-004** → FR-005..007, FR-040..042, FR-050..052, NFR-009
- **SCN-005** → FR-001, FR-003, FR-004, FR-011, FR-013, FR-015, FR-021/022, FR-050, FR-069, NFR-005
- **SCN-006** → FR-001, FR-004, FR-011, FR-015, FR-020/022, FR-050
- **SCN-007** → FR-002, FR-010..015, FR-020, FR-022, FR-050 + fetcher spec
- **SCN-008** → FR-002, FR-010, FR-012 (read path; IIIF server future)
- **SCN-009** → composite (SCN-007 + SCN-005 + SCN-002); FR-001..004, FR-010..015, FR-069 (task-api / processing steps out of scope)
