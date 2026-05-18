# 01 - Scope

## Problem Statement

Heritage- and document-processing services need a single durable pivot for all binary content flowing through the platform: images fetched from heritage institutions, end-user uploads, and worker artifacts (intermediate and final). The current ad-hoc storage approach mixes concerns (fetching, caching, processing, serving) and prevents fine-grained access control, audit, and quota management. The `asset-store` module solves this by providing a multi-tenant blob store with logical aliases, lifecycle management, and short-lived prefix-scoped access tokens, so that every other module (upload API, workers, future IIIF server, future task API) can rely on a single contract for storing and retrieving content.

## In Scope (MVP)

- **Object storage** of binary payloads (any MIME type) on an S3-compatible distributed backend.
- **Asset registry**: unique `asset_id`, one or more **aliases** per asset, per-asset metadata (MIME, size, checksum, owner space, timestamps, custom annotations), lifecycle state (`pending`, `available`, `expired`, `deleted`).
- **Alias namespace** organised by **space** (e.g. `cache`, `u-<user_id>`, `proj-<project_id>`, `results-task-<task_id>`); aliases unique within a namespace; multiple aliases per asset allowed.
- **Multipart / resumable upload** for payloads up to 5 GB.
- **Storage guard** (capability broker): mint short-lived, prefix-scoped, read- or write-only capabilities (S3 presigned URLs and/or server-issued tokens) for service identities; rate-limit and quota enforcement at the space level.
- **Audit log** for capability issuance, alias mutations, lifecycle transitions, admin actions; structured, append-only.
- **Admin UI/API** to list, inspect, expire, delete assets and aliases; inspect audit entries.
- **Bulk-loader CLI** for high-volume ingestion (also serves as integration smoke test).
- **Worker-sim CLI** for the read path and write-of-results path.
- **Observability baseline**: structured logs, Prometheus-style metrics, OpenTelemetry traces, basic dashboards and alerts.
- **Deployment**: Docker Compose for local dev; Docker Swarm stack file for the target environment.
- **Backup hook**: ability to snapshot/replicate to a second object-store target (incremental preferred; full implementation deferred but design must not preclude it).

## Out Of Scope (Explicit)

- **Image processing** of any kind (resize, OCR, transcription, etc.).
- **Remote URL fetching** (handled by a separate "IIIF proxy" module; this module never reaches outbound to heritage institutions).
- **IIIF Image API or Presentation API serving** (handled by a separate IIIF-server module that will read from `asset-store` as a client).
- **IIIF manifest composition and descriptive-metadata editing.** A IIIF manifest is a structured document with two kinds of fields: citation-critical (image references, structure, ordering) and descriptive (label, attribution, key-value metadata). asset-store stores opaque immutable bytes; it does not parse JSON-LD, does not know what counts as a structural vs descriptive field, and does not host editable descriptive metadata. A future `manifest-service` (consumer of asset-store) owns descriptive-metadata editing and composes the final manifest JSON on demand by merging editable metadata with the (frozen-at-publication) list of image references. asset-store stores any finalized manifest JSON snapshots that need durable bytes exactly like any other immutable payload.
- **End-user authentication / identity management** (services authenticate to `storage-guard` as service identities; user authentication is delegated to upstream APIs).
- **End-user-facing access-control UI** (only space-level / prefix-level capabilities in MVP).
- **Task orchestration / job queue / worker scheduling**.
- **Billing and pricing logic.**
- **Virus / malware scanning** (must be performed at ingestion time by callers, before submission).
- **Image format conversion, thumbnailing, transformation** of any kind.
- **Cross-region replication** beyond the in-cluster durability guarantees of the chosen `object-store`.
- **Encryption at rest** in MVP (tracked as `R-*` risk).

## Users And Integrators

Service identities that talk to `asset-store` in MVP:

- **Upload API** - writes user-uploaded payloads on behalf of authenticated end users; calls `storage-guard` to obtain a single-use write capability scoped to the user's space.
- **Bulk-loader** - pre-loads known image batches; same write-capability pattern.
- **Workers** - read assets and write result artifact bundles; receive read- and write-capabilities scoped per task.
- **Admin UI/API** - operates with broad-scope capabilities; all actions audited.

Service identities surveyed for future integration (out of scope for MVP):

- **IIIF proxy** - mirrors remote heritage images into a `cache` space.
- **IIIF server** - reads user/project spaces to serve image tiles and manifests.
- **Manifest-service** - composes IIIF Presentation API manifests by merging editable descriptive metadata (kept in its own DB) with the immutable list of image references (frozen at publication). Stores any finalized JSON snapshots in asset-store as ordinary immutable assets.
- **Task API** - issues task definitions that include input aliases and output prefix.
- **Storage-guard policy provider** - external policy engine for fine-grained user-level access control.

## Inputs

Ingestion modes supported in MVP:

- **Direct payload submission** via signed-URL PUT (or, for small objects under a configurable threshold, via the API server itself).
- **Multipart / resumable upload** via the `object-store` native multipart protocol.
- **Bulk import** orchestrated by the `bulk-loader` CLI (each item still flows through the standard write capability).

Ingestion mode **not** supported in MVP:

- Remote URL fetching by `asset-store` itself.

Hard limits:

- **Max single-object size**: 5 GB (covers anticipated multi-GB PDFs).
- **Common image size**: 1-2 MB; up to 50 MB allowed.
- **Allowed MIME types**: any (the module is content-agnostic). Caller is responsible for validation and virus/malware scanning.
- **TTL**: per-alias; default infinite; admin or caller can set a value (seconds). Expiration moves state to `expired`; garbage collection runs out-of-band.

## Outputs

What this module returns and emits:

- **API responses** - JSON for the registry/guard API; signed URLs or opaque tokens for capabilities.
- **Stored object keys** - opaque, server-assigned; not exposed in user-facing surfaces (aliases are the user-facing names).
- **Asset identifiers** - opaque `asset_id` (UUID v7 or similar time-sortable scheme; final choice in `ADR-004`).
- **Metadata schema** - documented in [`03_ARCHITECTURE_AND_DECISIONS.md`](03_ARCHITECTURE_AND_DECISIONS.md); minimum fields are `asset_id`, `space`, `aliases[]`, `mime`, `size_bytes`, `checksum`, `state`, `created_at`, `updated_at`, `expires_at`.
- **Audit events** - append-only structured records; one event per capability issuance, alias mutation, lifecycle transition, admin action.
- **Metrics** - request counters, latency histograms, error rate by cause, per-space storage usage, per-asset access counters.

## Success Criteria (Measurable)

1. **S-1 Capacity**: the system holds 1 TB across at least 100 000 assets on the dev stack without operator intervention.
2. **S-2 Concurrency**: 30 worker processes can each fetch one 1-2 MB asset every second over a 5-minute window with zero read errors and p95 latency under 200 ms in-cluster.
3. **S-3 Ingestion**: the `bulk-loader` can ingest 10 000 assets of average 1 MB in under 30 minutes on the dev stack with zero data loss (checksums verified on read).
4. **S-4 Capability scoping**: a capability issued for prefix `u-42/uploads/` cannot read, write, list, or delete anything outside that prefix; enforcement validated by a dedicated test suite.
5. **S-5 Audit completeness**: every capability issuance, lifecycle transition, and admin action appears in the audit log with caller identity, timestamp, alias affected, and outcome.
6. **S-6 Observability**: the operator dashboard surfaces ingestion rate, read latency p50/p95/p99, error rate by cause, and per-space storage usage; at least one alert is configured per SLI.
7. **S-7 Deployability**: `docker compose up` brings the full stack on a single machine in under 2 minutes; the same stack runs on Docker Swarm via the published stack file.
8. **S-8 Recoverability**: a deliberate kill of any single non-storage service results in zero failed user-visible requests after retry; the storage backend's own redundancy guarantees the durability promise.

Each success criterion is linked to one or more `FR-*` / `NFR-*` rows in [`02_REQUIREMENTS.md`](02_REQUIREMENTS.md).
