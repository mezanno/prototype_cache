# 00A - MVP Scenarios

> Terms and acronyms: [`00B_GLOSSARY_AND_ACRONYMS.md`](00B_GLOSSARY_AND_ACRONYMS.md)

## Scenario index

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

Remote URL flows use **fetcher-service** ([`07_FETCHER_SERVICE.md`](07_FETCHER_SERVICE.md)). asset-store never calls HTTP.

Out-of-scope scenarios (IIIF tile cache, visualization) remain in [`_archive/00A_USE_CASES_AND_SCENARIOS.md`](_archive/00A_USE_CASES_AND_SCENARIOS.md).

## Actor catalog (MVP)

- **Bulk-loader** - CLI; bulk-ingests into `cache/{mirror_id}/`.
- **Fetcher** - platform service; `ensure_url` → `cache` or `tmp`.
- **Upload API** - end-user uploads → `users/{userid}/`.
- **Task API** - task inputs; calls fetcher for URLs; may write `tmp/{tmpid}/`.
- **Worker** - reads by alias; writes `results/{taskid}/`.
- **Admin** - operator via admin-ui.
- **Storage-guard**, **Asset-registry**, **Object-store** - asset-store layers.

## Scenario template

```md
### SCN-XXX - <short title>

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

## Initial scenarios

### SCN-001 - Bulk preload image set

- **Priority:** P0
- **Actors:** Bulk-loader, storage-guard, asset-registry, object-store
- **Maps to:** FR-001, FR-004, FR-011, FR-015, FR-020, FR-021, FR-022, FR-050, NFR-001, NFR-005
- **Preconditions:** Manifest lists aliases under `cache/{mirror_id}/…`, MIME, local paths. Bulk-loader credential allows write `cache` only.
- **Trigger:** `bulk-loader --manifest=batch.csv --mirror-id=gallica`
- **Main flow:**
  1. Bulk-loader requests write capability scoped to `cache/gallica/{batch-id}/` (TTL 1 h).
  2. Guard authorizes (`FR-015`), reserves aliases `pending` (`FR-004`).
  3. Per item: PUT to MinIO bucket `cache`, key `{gallica}/assets/{asset_id}`; commit (`FR-022`).
  4. Summary: N ok, M failed, bytes, elapsed.
- **Expected result:** Assets `available`; aliases like `cache/gallica/bnf/ark-…/default.jpg` resolvable.
- **Error/failure paths:** bad manifest row; upload retry; capability re-issue; checksum mismatch → rollback.
- **Observability checks:** ingest counters, latency, bytes per `partition_id=gallica`.
- **Open questions:** Q-001, Q-002.

### SCN-002 - Worker reads an asset for processing

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

### SCN-003 - User upload through Upload API

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

### SCN-004 - Admin lifecycle operation

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

### SCN-005 - Worker writes result artifacts

- **Priority:** P1
- **Actors:** Worker, storage-guard, asset-registry, object-store
- **Maps to:** FR-001, FR-003, FR-004, FR-011, FR-013, FR-015, FR-021, FR-022, FR-050, NFR-005
- **Preconditions:** Write capability scoped to `results/987/attempt-1/worker-3/`.
- **Trigger:** Worker commit-results stage.
- **Main flow:**
  1. For each output: reserve alias under scope; PUT to bucket `results`, partition `987`.
  2. Commit each; upload manifest JSON last.
- **Expected result:** Bundle discoverable via manifest alias.
- **Error/failure paths:** partial upload; manifest marker pattern (`Q-008`).
- **Observability checks:** artifact + manifest success rates.
- **Open questions:** Q-008.

### SCN-006 - Task inline payload staged in tmp

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

### SCN-007 - Remote URL materialized by fetcher

- **Priority:** P0
- **Actors:** Task API, fetcher, storage-guard, asset-registry, object-store
- **Maps to:** FR-002, FR-010..015, FR-020, FR-022, FR-050; fetcher contract in [`07_FETCHER_SERVICE.md`](07_FETCHER_SERVICE.md)
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

### SCN-008 - IIIF server reads a stored asset

- **Priority:** P2 (future; IIIF server not in MVP)
- **Actors:** IIIF server, storage-guard, asset-registry, object-store
- **Maps to:** FR-002, FR-010, FR-012 (read path); IIIF server integration surveyed for later in [`01_SCOPE.md`](01_SCOPE.md)
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

## Cross-scenario decisions

- **Storage layout** — ADR-007; four buckets + `partition_id`.
- **Remote fetch** — ADR-008; fetcher only.
- **Identifiers** — ADR-004; opaque `asset_id` + aliases.
- **Mutability** — ADR-005; FR-008.
- **Capabilities** — ADR-003; FR-010..015.

## Acceptance mapping

- **SCN-001** → FR-001, FR-004, FR-011, FR-015, FR-020/021/022, FR-050, NFR-001, NFR-005
- **SCN-002** → FR-002, FR-010, FR-012, FR-030/031, FR-050, NFR-002, NFR-004, NFR-008
- **SCN-003** → FR-001, FR-004, FR-011, FR-013, FR-015, FR-020/021/022, FR-050, NFR-002
- **SCN-004** → FR-005..007, FR-040..042, FR-050..052, NFR-009
- **SCN-005** → FR-001, FR-003, FR-004, FR-011, FR-013, FR-015, FR-021/022, FR-050, NFR-005
- **SCN-006** → FR-001, FR-004, FR-011, FR-015, FR-020/022, FR-050
- **SCN-007** → FR-002, FR-010..015, FR-020, FR-022, FR-050 + fetcher spec
- **SCN-008** → FR-002, FR-010, FR-012 (read path; IIIF server future)
