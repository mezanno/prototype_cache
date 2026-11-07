# Collection publishing and Gallica image proxy — specification

**Pivot accepted 2026-11-07.** Deliver usable services for Corpusense, in order:

1. Restricted collection upload/import and administration, with durable storage.
2. Public IIIF publication of approved test collections, usable by Corpusense and existing workers.
3. An allowlisted Gallica **Image API** proxy/cache. Corpusense fetches Presentation manifests directly and rewrites image routing internally.

The existing job submission/processing system stays unchanged. A general-purpose
`asset-store` is no longer a product goal or a prerequisite. No repository/package
rename, backend replacement, deployment or data migration is implied by this pivot.

## Source of truth and reading order

1. [Scope and release acceptance](01_SCOPE.md).
2. [Active requirements](02_REQUIREMENTS.md).
3. [Architecture and ADRs](03_ARCHITECTURE.md).
4. [Pilot operations](04_OPERATIONS.md).
5. [Backlog, risks and open choices](05_BACKLOG_AND_OPEN_QUESTIONS.md).
6. [Execution plan](../WORKPLAN.md) and [M-002 delivery plan](../milestones/COLLECTIONS_AND_IMAGE_PROXY_PILOT.md).
7. Service contracts: [collections](../services/collections-service.md), [Gallica Image proxy](../services/gallica-image-proxy.md).

These documents supersede M-001 and the old asset-store delivery requirements.
Old IDs FR-001..072, NFR-001..012, ADR-001..041, B-001..025 and SCN-001..010
remain historical identifiers; do not reuse them or treat their uncompleted work
as new pilot gates. [Historical specifications and workplan](../history/asset-store/README.md)
preserve the prior design, decisions and handoffs. Existing runtime contracts and
security limitations still apply to any reused code; a documentation pivot does
not change deployed behavior or close findings.

## Delivery boundary

Keep the existing S3/Postgres foundation. Give the collection application ownership
of its metadata and raw data storage; do not mandate a universal alias registry or
capability broker between every consumer and its files. A small storage adapter
and stable resource IDs preserve future backend flexibility. Supabase is an
option to revisit only for a concrete delivery blocker, not a new selection phase.

Public reads apply only to published material approved for the first tests.
Administrative writes remain restricted. User/project authorization, authenticated
and metered proxy access, strict worker egress and concurrent storage backends are
deferred. Agentic workflows are future consumers of stable IDs and provenance,
not a new pilot API.

## Glossary

| Term | Meaning |
|---|---|
| Collection | Locally held, ordered material for users to view/process; retained independently of cache eviction. May contain one or more documents. |
| Document / page | Logical units used to generate IIIF manifests/canvases; grouping and ordering are explicit import metadata. |
| Representation | A specific stored image of a page, with dimensions, format, checksum and provenance. |
| Canonical source | Upstream material/page identity when known; distinct from local URLs and encoded-byte identity. |
| Raw data | Uploaded bytes preserved as supplied; derivatives never overwrite them. |
| Service storage | Service-owned records/indexes, generated manifests and disposable derivatives/cache, distinct from retained raw data. |
| IIIF Image API | Image information and image-region/size/rotation/format requests. |
| IIIF Presentation API | Manifests/collections describing material; generated for local collections, fetched directly by Corpusense for Gallica. |
| Proxy cache | Disposable copies of allowlisted upstream Image API responses; not the collection retention authority. |
| Asset-store | Existing implementation (`asset_store_core`), available for selective reuse, no longer the target product architecture. |
| FR / NFR / ADR / SCN / B / Q / R | Functional requirement / non-functional requirement / decision / scenario / backlog / open question / risk. |
