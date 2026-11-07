# Collection application — active contract

**Planned; M-002/R1–R2.** [Requirements](../spec/02_REQUIREMENTS.md) and
[ADR-042..050](../spec/03_ARCHITECTURE.md#adr-log--active-pivot) govern implementation.
No collection endpoints or IIIF engine have been delivered by this document.

## Responsibilities

- Minimal restricted admin tools and service API: create/import, inspect item
  outcomes, retry failures, publish and unpublish. No end-user account system now.
- Durable collection/document/page/representation metadata; explicit order; raw
  file preservation and checksum/dimension extraction. A collection can contain
  multiple documents; manifest grouping comes from explicit import metadata.
- Local Presentation manifests/index and linkage to an existing Image API server.
- Reachable published input URLs and source/coordinate metadata for Corpusense
  and the existing job system. Results remain in the existing system.

## Import and catalog contract to finalize in B-101

Minimum supplied fields: collection/document/page identifiers or creation rules,
explicit order/label, file mapping, and optional canonical source/rights/provenance.
Minimum derived fields: stable local IDs, representation ID, checksum, bytes,
format/dimensions, raw location and import/publication state. Original uploads need
not have upstream references; record unknown values honestly.

Image files plus a CSV/JSON index is a candidate import arrangement, not an accepted
schema. Confirm a representative sample and supported file formats/sizes first.
Do not default to arbitrary archive extraction or all TIFF/JPEG2000 variants.
Concrete endpoints, retry identifiers and limits are implementation-contract work;
there is no new Corpusense task envelope here.

## Storage and publication

The application owns raw objects and catalog. Use the existing S3/Postgres approach
with separate retained raw data and disposable service artifacts/derivatives.
Buckets/prefixes and reader credentials are implementation choices; no universal
four-bucket/alias/capability contract. Never let a cache sweep delete raw collections.

A failed/partial import stays unpublished. Only validated published content is
publicly readable. Publication controls must apply to the image server as well
as manifest routes; guessing a draft image ID must not bypass them. Unpublish stops
new service reads; specify derivative-cache invalidation and any issued-link expiry.
Downloaded copies are outside revocation. No automatic raw deletion on unpublish.

## IIIF and provenance

Choose the Image/Presentation versions that the existing Corpusense actually
supports. An off-the-shelf Image API engine performs image operations; the app
produces basic ordered manifests/indexes. No remote manifest editor/composer.
Cantaloupe is a candidate to verify, not a fixed stack choice.

Preserve upstream canonical IDs, original manifest/canvas/image-service references,
attribution/rights and image provenance when available. Local ~2048-pixel BnF
representations do not claim full-master resolution or exact upstream bytes.
Record the actual representation and coordinate frame for each processing attempt
through compatible metadata or a side record keyed by the existing job/attempt ID;
the current job interface stays unchanged.

For initial full-page scaling, retain actual dimensions and the map to source/canvas.
Do not claim equivalent geometry for crops/rotations/deskew or distinct scans
without a known transform. Relative coordinates can be derived where meaningful;
never discard processed-image dimensions/pixel coordinates merely to normalize.
Smart minimum-resolution/local-ranking/exact-fetch selection is B-113, not a gate
for serving the first collection.

## Acceptance

SCN-101..103: restricted import, partial retry/persistence, publication gate, real
Corpusense display/import and real job read, canonical coordinate reference when
known, isolated restore. Add relevant import/publication/image metrics/logs and
short operator guidance with each behavior; no new monitoring platform required.
