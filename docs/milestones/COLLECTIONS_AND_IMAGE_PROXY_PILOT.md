# M-002 — Custom collections, local IIIF and Gallica Image proxy

Owner decisions accepted 2026-11-07; plan recorded 2026-11-08. This replaces
[M-001's delivery priority](PRIVATE_CACHE_PILOT.md), not its recorded evidence.
See the [execution queue](../WORKPLAN.md) and [active requirements](../spec/02_REQUIREMENTS.md).

## Release 1 — An operator can upload and publish a collection

Deliver a minimal admin surface/tools and service API over a collection-owned
catalog and raw-data storage. Import representative files with document/page IDs,
order, dimensions/checksum and source metadata. Preserve delivered bytes, expose
per-item outcomes/retries, and separate draft/validated/published states. Storage
and metadata survive restart. Readers cannot mutate; only authorized operators
can import, publish or unpublish. Publication of approved test content will be
public; backend buckets need not be public.

**Done:** restricted-write and unpublished-read tests; a representative partial
import/retry; metadata/order/checksum verification after reopen/restart; limits,
status/errors and operator instructions. FR-100..103/106, NFR-100..103/106.

## Release 2 — Users view/import/process through IIIF

Select an existing Image API engine using actual formats and UI versions; generate
local Presentation manifests/index in the collection application. Serve stable
published page URLs to Corpusense and existing workers with browser/CORS settings.
Record exact input representation/dimensions and mapping to canonical source/canvas
when known. No scheduler, results-store or task-payload replacement.

**Done:** actual Corpusense imports/displays ordered pages, the existing real job
reads a local input independently of browser disconnection, results are retrieved
through existing interfaces, an output source/coordinate reference is verified, and an
isolated restore recovers catalog plus matching raw files. Failures are visible.
FR-104..105/107..109, NFR-100/101/104.

R1+R2 are the first end-user test release. Use a minimal approved corpus; select
concrete sample sizes and limits in B-101, not legacy full-scale certification.

## Release 3 — Gallica image traffic uses a transparent proxy/cache

Corpusense obtains Presentation manifests directly and routes Image API info.json
and image requests through an allowlisted proxy. Include successful-response
cache reuse, explicit request keys/freshness, bounded origin demand/429 recovery
and server-held API-key configuration. API key receipt and exact quota are not yet
established. Isolated fixtures let implementation proceed meanwhile.

**Done:** actual UI traffic proves direct manifests/proxied images and info; repeated
requests do not contact origin; renditions remain distinct; key-redaction and
isolated failure/overload/recovery tests pass within configured bounds. No
Presentation routes/backend manifest rewriting. FR-120..124, NFR-101/102/105.

Prepare R3 contract/fixtures during R1/R2; do not wait for admin polish. Public
proxy-user reads and lack of per-user accounting are accepted pilot limitations.

## Explicit follow-ups

User/project permissions, independent service-and-user verification, private
collections, proxy authentication/metering, strict worker egress/model sidecar,
smart representation choice, multiple active backends and migration, tmp/task
storage policy, agentic workflows and expanded production hardening are B-110..116.
Stable IDs/provenance and a small location adapter preserve their path now.

## Release evidence template

For each release record: source/image identity; approved material; versions and
finite limits; real UI/job requests (without credentials); checksums/mapping;
failure/recovery and persistence results; operator startup/rollback/backup guidance;
known limitations and owner review. Never report old cache-only evidence as M-002
acceptance or describe this plan as delivered functionality.
