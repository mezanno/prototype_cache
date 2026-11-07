# 01 — Scope and release acceptance

**Active: M-002, accepted 2026-11-07.** [Architecture decisions](03_ARCHITECTURE.md)
and [workplan](../WORKPLAN.md) replace the asset-store-first programme. This is
an implementation plan, not a claim that the new services already exist.

## Goal

Let an operator publish custom/local collections, let users import and process
them in Corpusense with the current job system, then relieve Gallica image rate
limits through a dedicated Image API proxy/cache.

## Delivery order

| Release | In scope | Exit criterion |
|---|---|---|
| M-002/R1 — Collection import | Restricted admin tools and service API; local file upload/bulk import; explicit document/page order; metadata and raw data persistence; retry/status; draft/publish/unpublish | A representative collection imports, failed items can be retried without duplicating successful items, raw checksums match, and metadata/files survive restart. |
| M-002/R2 — Local IIIF publication | Generated Presentation manifests/collection index as needed by Corpusense; existing Image API server; browser access/CORS; worker access; provenance/coordinate mapping | Actual Corpusense imports/displays the material; the existing submission/processing system processes a page independently of the browser session; results are retrievable and an output can reference the source with correct coordinates. |
| M-002/R3 — Gallica Image proxy | Allowlisted info.json and image routes; request caching; bounded upstream demand; server-held BnF key when available; Corpusense routes image traffic | Corpusense fetches a manifest directly, image/info requests pass through the proxy, a repeated request hits cache, and throttling/errors recover within configured bounds. |

R1 and R2 are the first usable product increment. Keep admin tooling minimal;
do not polish it before R3. Prepare the independent R3 contract/fixtures during
R1/R2; the higher-limit API key is not required for isolated testing.

## Scenarios

| ID | Scenario | Requirements |
|---|---|---|
| SCN-101 | Operator creates/imports a collection, supplies explicit document/page identity and order, reviews failures and publishes approved material. | FR-100..103, FR-106, NFR-100..103 |
| SCN-102 | Corpusense imports a local manifest, displays pages and submits an existing processing job using reachable local image URLs. | FR-104..105, FR-107..108, NFR-104 |
| SCN-103 | Exported OCR/result identifies the actual input and canonical source when known, with a documented coordinate mapping. | FR-103, FR-108..109 |
| SCN-104 | Corpusense retrieves a Gallica manifest directly, routes Image API traffic through the proxy, then reuses cached image/info responses. | FR-120..124, NFR-101..102, NFR-105 |
| SCN-105 | Import/storage/origin failure is visible and bounded; retry/restart preserves published material and releases resources. | FR-101, FR-106, FR-122..124, NFR-100..105 |

## Accepted pilot simplifications

- Approved published material is publicly readable without end-user login. Only
  authorized operators can upload, mutate metadata, publish or unpublish. This is
  not a private-collection guarantee or a decision to publish raw storage buckets.
- Preloaded BnF material is a retained local collection. It is not automatically
  deleted by cache TTL/pressure. Keep the raw delivered bytes and source references.
- Existing job submission, scheduling, processing and result retention remain
  owned by the current system. Supply compatible URLs/metadata; do not require a
  new task envelope or replacement results service.
- Strict worker network isolation, double service/user authentication, project
  memberships, per-user proxy metering, multiple simultaneous storage backends,
  a separate tmp namespace and agent-specific APIs are follow-ups.
- One Compose host, existing S3/Postgres approach and minimal operator tools.
  No mandatory storage-provider switch or Supabase adoption.

## Explicit exclusions

- No Gallica Presentation proxy, backend manifest rewriting or remote manifest
  composition. Corpusense owns direct manifest retrieval and image URL routing.
- No general asset-store completion, universal filesystem/alias/capability API,
  storage deduplication, HA/Swarm certification or full-scale legacy load targets.
- No change to upstream content. Local identifiers and representations must not
  erase or falsely claim canonical source identity or byte equality.
- No OCR engine/job scheduler rewrite. A worker simulator is not integration proof.

## Representation selection follow-up

A processing policy may later accept a minimum useful resolution, prefer eligible
local images and offer exact-rendition fetching. Record the selected representation
and coordinate mapping from the first release; a smart selector is not an R1/R2
gate. A 2048-pixel rendition is not automatically equivalent to full resolution,
and equal dimensions do not imply identical pixels/bytes. This policy must never
silently change exact IIIF proxy semantics (ADR-048).

## Evidence limits

Prior M-001 tests/recovery observations remain useful implementation evidence,
not M-002 acceptance. No new workload, deployment or migration has occurred as
part of this specification update. Verify host/runtime state before reuse.
