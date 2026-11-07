# Delivery workplan — collection publishing and Gallica Image proxy

**Pivot accepted 2026-11-07; recorded 2026-11-08.** Owner authorized updating the
specifications and plan. This checkpoint changes documentation only: no new app
code, tests/workloads, migration, deployment, fault injection, commit or push.

## Objective and decisions

Ship custom collection upload/admin/storage, expose the collection through IIIF
for Corpusense and current workers, then deliver the urgent Gallica Image API
proxy/cache. Preserve the current job submission/processing system. The general
asset-store programme and M-001 completion cease to be delivery prerequisites.

Accepted boundaries are [ADR-042..050](spec/03_ARCHITECTURE.md#adr-log--active-pivot).
[Scope](spec/01_SCOPE.md), [requirements](spec/02_REQUIREMENTS.md),
[backlog/questions](spec/05_BACKLOG_AND_OPEN_QUESTIONS.md) and the
[M-002 release plan](milestones/COLLECTIONS_AND_IMAGE_PROXY_PILOT.md) are authoritative.

## Execution order

| Step | Deliverable | Work items | Exit / handoff |
|---|---|---|---|
| 0 | Pivot documentation and preservation | B-100 | Done, docs only. Old programme is historical, not passed or deleted. |
| 1 | Concrete import contract and first representative collection | B-101 | Agree IDs/order, schema/formats, host limits and operator access. Obtain Corpusense/job contract for later integration; do not block independent storage/import work on unrelated details. |
| 2 | Raw storage, catalog, retryable import and minimal admin | B-102/103 | R1: restricted writes, raw bytes/checksums and metadata survive restart, failed items retry, only validated published material can be exposed. |
| 3 | Existing IIIF engine + generated local manifests + real UI/job proof | B-104/105/106 | R2: Corpusense displays/imports the collection; unchanged job system processes one local page; source-coordinate export and isolated restore proven. |
| 4 | Transparent Gallica Image proxy/cache and Corpusense routing | B-107/108 | R3: direct manifest fetch in UI, proxied info/image requests, cache reuse, finite shared upstream load and fault recovery. |

Start B-104 sample/software verification during import work. Prepare R3 routing,
origin fixtures and API-key integration separately while R1/R2 progress. Finish
minimal usable increments; do not insert admin polish, a new auth platform or
storage-provider selection between releases. No new agents/delegation assumed.

## Initial implementation slice

1. Read Q-101/102/103/106; obtain an example input collection and current UI/job
   repository or sanitized request. These remain missing, not implicitly answered.
2. Define the smallest collection/document/page/representation import contract
   with explicit order, immutable raw data, source metadata and per-item outcomes.
3. Choose the existing S3/Postgres integration for that slice. Reuse adapters and
   transport/observability code where useful; do not require a generic asset-store
   HTTP hop or change existing consumers/migrations just to rename the design.
4. Implement catalog/import/restricted admin with behavior tests, finite limits,
   failure status and operator guidance. Record concrete schema/API choices as
   ADRs before coding. This documentation checkpoint itself implements none of it.

## Scope rules

- Restricted operator writes; public reads of approved published test material.
  No per-user/project login or privacy guarantee yet; drafts/unpublished image
  routes stay hidden. Do not make raw backend/admin endpoints public.
- Existing job submission, scheduling and results stay as they are. Do not adopt
  worker-sim's alias/capability payload as the real product contract by default.
- Local manifests are generated for uploaded collections. Gallica manifests are
  fetched by Corpusense directly; it handles image URL routing. No Presentation
  proxy/backend manifest rewriting. Authentication/metering of proxy users is later.
- Keep source references and exact input dimensions/checksum/mapping from day one.
  Smart resolution selection is later; exact Image requests are not silently
  answered with a smaller collection representation.
- One backend now; stable logical IDs and separate locations permit future
  simultaneous backends/project placement/migration. No new universal alias layer,
  Supabase adoption, repo rename, tmp namespace, result service, HA/Swarm or agent
  interface is required for this pilot.

## Reuse and evidence

Existing source includes S3/Postgres adapters, registry/guards/admin, imports,
fetcher origin/redirect protections, metrics and lifecycle. Reuse selectively.
The current facade is authenticated preload + cache-only image reads, not a
complete IIIF Image or collection service. Proxy uploads buffer bytes (50 MiB
by default); tokens are process-local. Collection publication and R3 miss fetching
will require implementation; the pivot changes no live routes.

The [historical workplan](history/asset-store/WORKPLAN.md) preserves all prior
checkpoints: recorded code baseline 542 tests passed (not rerun here), accelerated
cache-read and suspension-aware observations, restore/rollback work, and unresolved
security/browser/off-host backup/performance limitations. They are not proof of
new collection/UI acceptance. The last recorded M-001 observation is closed;
actual machine/runtime state must be verified before any operational work.

## Verification and release discipline

Use [pilot operations](spec/04_OPERATIONS.md) for proportional checks. Every changed
behavior needs tests, relevant logs/metrics and a short operator procedure. Isolated
failure fixtures precede bounded real-origin smoke. Validate actual UI/job behavior,
not just a simulator. Keep publication, checksums, resource bounds, key handling,
origin safety and recovery; broad legacy fault/load/soak certification is deferred.
Do not close applicable findings by changing the product plan.

## Preservation and authorization

- Existing archives, historical reports, runtime configuration, data/volumes,
  migration history, protected pilot files and owner images under `tmp/` remain
  intact. No automatic cleanup, expiry change, restart or migration is implied.
- Existing service contracts remain true for unchanged code, but their roadmaps,
  pause/handoff instructions and six-section integration form no longer define
  the current delivery sequence. This workplan supersedes them.
- The previous owner pauses on the old programme do not prevent this explicitly
  authorized documentation pivot. They do not authorize live workloads either.
- **Next task:** B-101 then the smallest R1 implementation slice. Missing sample,
  host or UI details should be requested only for the work they actually block.
  No commit/push or runtime actions were requested in this documentation update.
