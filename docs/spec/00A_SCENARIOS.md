# 00A - MVP Scenarios

Concrete, testable scenarios for the `asset-store` MVP. Each scenario maps to one or more `FR-*` / `NFR-*` rows in [`02_REQUIREMENTS.md`](02_REQUIREMENTS.md).

Out-of-scope scenarios (IIIF serving, IIIF remote-fetch caching, user visualization, periodical garbage collection) live in [`_archive/00A_USE_CASES_AND_SCENARIOS.md`](_archive/00A_USE_CASES_AND_SCENARIOS.md) and will be revisited when the corresponding downstream modules are scoped.

## Actor catalog (MVP)

- **Bulk-loader** - CLI; bulk-ingests known image batches.
- **Upload API** - upstream service; writes end-user uploads on behalf of authenticated users.
- **Worker** - background processor; reads inputs and writes result artifact bundles.
- **Admin** - operator using the `admin-ui` or admin REST API.
- **Storage-guard** - layer 3 service; capability broker.
- **Asset-registry** - layer 2 service; aliases, metadata, lifecycle.
- **Object-store** - layer 1; S3-compatible blob store.

## Scenario template

```md
### SCN-XXX - <short title>

- **Priority:** P0 / P1 / P2
- **Actors:** ...
- **Maps to:** FR-..., NFR-...
- **Preconditions:** ...
- **Trigger:** ...
- **Main flow:**
  1. ...
  2. ...
- **Expected result:** ...
- **Error/failure paths:** ...
- **Observability checks:** metrics/logs/traces to verify
- **Open questions:** ... (Q-*)
```

## Initial scenarios

### SCN-001 - Bulk preload image set

- **Priority:** P0
- **Actors:** Bulk-loader, storage-guard, asset-registry, object-store
- **Maps to:** FR-001, FR-004, FR-011, FR-020, FR-021, FR-022, FR-050, NFR-001, NFR-005
- **Preconditions:** A source manifest (CSV/JSON) lists N items with declared alias, MIME, and local payload path. The bulk-loader holds a static service credential. The target `cache` space exists.
- **Trigger:** Operator runs `bulk-loader --manifest=batch.csv --space=cache`.
- **Main flow:**
  1. Bulk-loader asks the storage-guard for a single write capability scoped to prefix `cache/<batch-id>/` with TTL = 1 h.
  2. Storage-guard authorizes the bulk-loader, reserves all aliases listed in the batch in `pending` state (FR-004), and returns the capability.
  3. For each item, bulk-loader PUTs the payload to the object-store via the signed URL (or multipart if larger than threshold).
  4. After each successful upload, bulk-loader calls `POST /assets/commit` with the size and client-side checksum. Registry transitions the asset to `available` (FR-001, FR-022).
  5. Bulk-loader prints a summary: N succeeded, M failed, byte count, elapsed time.
- **Expected result:** N assets in state `available`, each resolvable by its declared alias; payloads readable by an authorized worker.
- **Error/failure paths:** invalid manifest row (skipped with log), upload error (retried with exponential backoff up to 3 times, then aborted for that item), capability expiry mid-batch (re-issued automatically), checksum mismatch on commit (item rolled back to no-record state).
- **Observability checks:** ingest success counter, per-item failure counter with cause, write latency histogram, total bytes ingested.
- **Open questions:** batch transactional semantics (Q-001), max batch size before re-issuing capability (Q-002).

### SCN-002 - Worker reads an asset for processing

- **Priority:** P0
- **Actors:** Worker, storage-guard, asset-registry, object-store
- **Maps to:** FR-002, FR-010, FR-012, FR-030, FR-031, FR-050, NFR-002, NFR-004, NFR-008
- **Preconditions:** Asset exists in state `available`. The worker has been issued a task definition that contains the alias to read and a short-lived read capability for that alias (issued by the task orchestrator after the orchestrator obtained one from the storage-guard on behalf of the requesting user). The worker holds no other access.
- **Trigger:** Worker starts processing its task.
- **Main flow:**
  1. Worker calls `GET /resolve?alias=<alias>` on the storage-guard, presenting its task capability.
  2. Storage-guard validates the capability scope against the requested alias (FR-012, NFR-008); on success, asset-registry resolves alias to `asset_id` and the storage-guard mints (or returns) a signed URL on the object-store with the matching TTL.
  3. Worker fetches the payload via the signed URL.
  4. Worker proceeds with its processing logic (out of scope for this module).
- **Expected result:** Worker retrieves the exact payload that was uploaded; checksum verified by the object-store on read (NFR-005 sampling); response time meets NFR-002 p95.
- **Error/failure paths:** alias unknown -> 404; alias expired / deleted -> 410; alias out of capability scope -> 403; object-store transient error -> worker retries with exponential backoff; capability expired mid-flight -> worker requests a new one from the orchestrator.
- **Observability checks:** read latency p50/p95/p99, read error rate by cause (404/410/403/5xx), audit event for capability use.
- **Open questions:** should the storage-guard proxy the GET in some deployment modes instead of issuing signed URLs (Q-003).

### SCN-003 - User upload through Upload API

- **Priority:** P1
- **Actors:** Upload API, storage-guard, asset-registry, object-store
- **Maps to:** FR-001, FR-004, FR-011, FR-013, FR-020, FR-021, FR-022, FR-050, NFR-002
- **Preconditions:** Upload API has authenticated the end user (user `u-42`); the Upload API holds a static service credential to call the storage-guard; the user's space `u-42` exists (auto-created on first use).
- **Trigger:** The end user submits a file (e.g. through the web app); Upload API receives the request. The aliases created here are *immutable* by default (FR-008): the bytes uploaded are bound to the alias for life. If the upstream feature requires editable descriptive metadata (e.g. for IIIF manifests), that descriptive layer lives in a future `manifest-service` and is out of scope here.
- **Main flow:**
  1. Upload API requests a single-use write capability (FR-013) for alias `u-42/uploads/<server-chosen-suffix>` with a 10-minute TTL.
  2. Storage-guard authorizes the Upload API, reserves the alias (state `pending`, FR-004), returns the capability.
  3. Upload API streams the user payload through to the object-store via the signed URL (or PUTs directly with multipart for large payloads, FR-021).
  4. Upload API calls `POST /assets/commit` with size, client-side checksum, declared MIME, and any user-supplied annotations.
  5. Storage-guard records the commit, registry transitions the asset to `available`, audit event written (FR-050).
  6. Upload API returns the canonical `asset_id` and alias to its caller.
- **Expected result:** Upload API can reference the stored asset (by alias) in subsequent business workflows.
- **Error/failure paths:** transfer timeout (the pending alias auto-expires after capability TTL; garbage collected later), invalid declared MIME (still accepted - module is content-agnostic), oversized payload (rejected by object-store with 413), checksum mismatch on commit (asset rolled back to no-record state).
- **Observability checks:** upload throughput by space, failed-upload causes counter, pending-to-available transition latency.
- **Open questions:** quota enforcement model (Q-004); MIME sniffing on commit vs trust declared (Q-005).

### SCN-004 - Admin lifecycle operation

- **Priority:** P1
- **Actors:** Admin, admin-ui, storage-guard, asset-registry, object-store
- **Maps to:** FR-005, FR-006, FR-007, FR-040, FR-041, FR-042, FR-050, FR-051, FR-052, NFR-009
- **Preconditions:** Admin holds an admin-scope service credential. Target asset exists.
- **Trigger:** Admin opens `admin-ui`, lists assets in a space, selects one, performs an action (set TTL / expire / delete / attach alias / detach alias / edit annotations).
- **Main flow:**
  1. Admin lists assets with filters (`space`, `state`, `created_at` range, alias prefix, FR-040).
  2. Admin opens the asset detail view (FR-041) to inspect metadata and recent audit events.
  3. Admin performs the action (FR-042): set TTL extends `expires_at`; expire transitions state to `expired`; delete enqueues a garbage-collection job that removes the payload and transitions to `deleted`; attach/detach alias updates the alias list.
  4. Asset-registry persists the state transition; audit event written; metrics updated.
- **Expected result:** State change is durable; resolving the affected alias reflects the new state (e.g. 410 after expire, 404 after delete-and-detach). Audit entry contains caller identity, target, before/after state, timestamp.
- **Error/failure paths:** concurrent update -> optimistic-locking conflict, surfaced to the admin with the latest state; delete on an asset with active aliases is allowed (each alias also becomes unresolvable); admin attempts to attach an alias that already exists -> 409.
- **Observability checks:** admin-action counter by action type, audit-write success rate, lifecycle state transition counters.
- **Open questions:** soft-delete vs hard-delete grace period (Q-006); admin override of TTL on system-managed spaces (Q-007).

### SCN-005 - Worker writes result artifacts

- **Priority:** P1
- **Actors:** Worker, storage-guard, asset-registry, object-store
- **Maps to:** FR-001, FR-003, FR-004, FR-011, FR-013, FR-021, FR-022, FR-050, NFR-005
- **Preconditions:** Worker has finished processing a task; worker holds a single write capability scoped to `results-task-<task_id>/attempt-<n>/worker-<w_id>/`.
- **Trigger:** Worker enters its "commit results" stage.
- **Main flow:**
  1. Worker enumerates its output files locally.
  2. For each output, worker reserves the alias under its scope (FR-004) and uploads the payload (FR-020 / FR-021).
  3. Worker commits each upload (FR-022); registry transitions each asset to `available`.
  4. Worker emits a summary "manifest" object (e.g. JSON listing all output aliases and their roles) and uploads it as the **final** artifact of the bundle; downstream consumers read the manifest to discover the rest.
- **Expected result:** All output aliases are readable by downstream consumers; the manifest enumerates them; if the worker dies before uploading the manifest, downstream consumers see an incomplete bundle and ignore it.
- **Error/failure paths:** partial group upload (manifest-as-commit-marker prevents partial reads in MVP; full atomic group operation is `Q-008`); checksum mismatch on any single item (item rolled back; manifest upload aborted by the worker).
- **Observability checks:** artifact write success rate, manifest-upload success rate (proxy for bundle completeness), grouped-write consistency counter.
- **Open questions:** atomicity required for grouped artifacts beyond the manifest-marker pattern (Q-008).

## Cross-scenario decisions to lock early

These decisions surface across multiple scenarios and are tracked in the ADR log:

- **Identifier model** - opaque server-assigned `asset_id` + zero-or-more aliases unique per space (`ADR-004`).
- **Mutability model** - payload write-once; annotations mutable; alias is single-binding-for-life by default, with an explicit `mutable: true` opt-in for rebind (`ADR-005`, FR-008).
- **Read interface** - signed-URL default, server-side proxy optional (`ADR-003`).
- **Retention model** - per-alias TTL; default infinite; grace period before garbage collection (`FR-006`, `FR-007`, `FR-060`).
- **Large-object strategy** - multipart / resumable transfer up to 5 GB (`FR-021`).
- **Scope boundary** - the module never makes outbound calls to fetch remote URLs; this is delegated (`01_SCOPE.md`).

## Acceptance mapping

- **SCN-001** -> FR-001, FR-004, FR-011, FR-020/021/022, FR-050, NFR-001, NFR-005 (Integration test, load test)
- **SCN-002** -> FR-002, FR-010, FR-012, FR-030/031, FR-050, NFR-002, NFR-004, NFR-008 (Integration test, load test)
- **SCN-003** -> FR-001, FR-004, FR-011, FR-013, FR-020/021/022, FR-050, NFR-002 (Integration test)
- **SCN-004** -> FR-005, FR-006, FR-007, FR-040..042, FR-050..052, NFR-009 (Integration test)
- **SCN-005** -> FR-001, FR-003, FR-004, FR-011, FR-013, FR-021/022, FR-050, NFR-005 (Integration test)
