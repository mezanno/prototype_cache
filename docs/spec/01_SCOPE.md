# 01 - Scope

> Terms and acronyms: [`00B_GLOSSARY_AND_ACRONYMS.md`](00B_GLOSSARY_AND_ACRONYMS.md)

## At a glance

| Module | Responsibility |
|--------|----------------|
| **asset-store** | Store bytes, aliases, lifecycle, capabilities, audit |
| **fetcher-service** | Fetch remote URLs → write `cache` or `tmp` ([`07_FETCHER_SERVICE.md`](07_FETCHER_SERVICE.md)) |
| **upload-api** | User uploads → `users` (and staging in `tmp`) |
| **workers** | Read by alias; write results → `results` |

**asset-store does not perform outbound HTTP.** Remote ingestion is fetcher's job.

**Four MinIO buckets (MVP):** `cache`, `tmp`, `users`, `results`. Optional `iiif_server_cache` is owned by the IIIF server, not asset-store.

---

## Problem Statement

Heritage- and document-processing services need a single durable pivot for all binary content flowing through the platform: images fetched from heritage institutions, end-user uploads, and worker artifacts (intermediate and final). The current ad-hoc storage approach mixes concerns (fetching, caching, processing, serving) and prevents fine-grained access control, audit, and quota management. The `asset-store` module solves this by providing a multi-tenant blob store with logical aliases, lifecycle management, and short-lived prefix-scoped access tokens, so that every other module (upload API, fetcher, workers, future IIIF server, future task API) can rely on a single contract for storing and retrieving content.

## In Scope (MVP)

- **Object storage** of binary payloads (any MIME type) on an S3-compatible distributed backend with **four buckets**: `cache`, `tmp`, `users`, `results` (see [`03_ARCHITECTURE_AND_DECISIONS.md`](03_ARCHITECTURE_AND_DECISIONS.md)).
- **Asset registry**: unique `asset_id`, one or more **aliases** per asset, metadata including `space` (bucket), `partition_id`, MIME, size, checksum, lifecycle state (`pending`, `available`, `expired`, `deleted`).
- **Alias namespace** per bucket (`space`); qualified alias `{space}/{partition_id}/…`; unique within `space`.
- **Multipart / resumable upload** for payloads up to 5 GB.
- **Storage guard**: service-identity auth; bucket allowlists ([`FR-015`](02_REQUIREMENTS.md)); prefix-scoped capabilities; per-partition quota hooks ([`Q-004`](05_BACKLOG_AND_OPEN_QUESTIONS.md)).
- **Audit log**, **admin UI/API**, **bulk-loader**, **worker-sim**, **observability**, **deployment** (Compose + Swarm), **backup hook** (design).

## Out Of Scope (Explicit)

- **Image processing** of any kind.
- **Remote URL fetching by asset-store** — delegated to **fetcher-service** ([`07_FETCHER_SERVICE.md`](07_FETCHER_SERVICE.md)).
- **IIIF Image API or Presentation API serving** — separate IIIF-server module.
- **IIIF manifest composition** — future `manifest-service`.
- **`iiif_server_cache` bucket** — tile/cache storage managed by IIIF server directly, not via asset-store APIs.
- **End-user authentication** — upstream APIs; asset-store sees service identities only.
- **Task orchestration**, **billing**, **virus scanning** (caller's duty), **format conversion**, **cross-region replication**, **encryption at rest** in MVP (`R-*`).

## Users And Integrators

### Service identities (asset-store MVP)

| Service | Typical buckets | Role |
|---------|-----------------|------|
| **fetcher** | read/write `cache`, `tmp` | Materialize remote URLs ([`07_FETCHER_SERVICE.md`](07_FETCHER_SERVICE.md)) |
| **upload-api** | read/write `users`, `tmp` | End-user uploads |
| **bulk-loader** | read/write `cache` | Bulk preload |
| **worker** | read `cache`, `users`, `tmp`; write `results` | Process tasks |
| **task-api** | read `cache`, `users`, `tmp`; write `tmp` | Task defs; calls fetcher for URLs |
| **admin** | all MVP buckets | Operations |

### Surveyed for later

- **IIIF server** — read `cache`, `users`; own `iiif_server_cache` bucket.
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
