# 02 — Active pilot requirements

**M-002; accepted 2026-11-07.** These requirements supersede the asset-store
programme for new delivery. [FR-001..072/NFR-001..012](../history/asset-store/spec/02_REQUIREMENTS.md)
remain historical runtime/design references, not blanket release gates. All new
requirements below are required for their assigned release unless marked deferred.

## Collections — R1

| ID | Requirement | Acceptance |
|---|---|---|
| FR-100 | Provide restricted administrative upload/import, collection inspection and publication controls through a service API and minimal operator tooling. | Unauthorized mutation is rejected; an operator imports, inspects and changes publication status using documented tools. No new identity platform required. |
| FR-101 | Import files with explicit document/page IDs and order; preserve raw bytes and compute SHA-256, size, detected image dimensions/format. Bound supported formats, per-file/batch size and concurrency in configuration. | Representative files round-trip with matching checksums; invalid/oversized items fail clearly; retrying a partial import does not duplicate successful items or overwrite their raw bytes. |
| FR-102 | Store durable collection/document/page/representation records independently of physical bucket/key names. Store generated service data separately from immutable raw data by ownership/prefix or bucket. | Restart/reopen preserves IDs, ordering, metadata and raw file locations; source-file names are not trusted as paths. Physical location changes do not change public resource IDs. |
| FR-103 | Retain canonical upstream identifiers, original manifest/canvas/image-service references, attribution/rights and provenance when supplied. Support wholly original uploads with no upstream ID. | Import/retrieve metadata preserves supplied references and distinguishes local publication URLs from upstream canonical material; missing source information is explicit. |
| FR-106 | Track per-item import outcomes and draft/published/unpublished status. Publish only complete validated material; unpublish denies new service reads without implicitly deleting raw data. Retained collections are not subject to proxy-cache eviction. | Failed items remain unpublished; operator can diagnose/retry; drafts/unpublished pages cannot be retrieved through collection or image routes. Cache cleanup leaves collection raw bytes unchanged. Previously downloaded copies cannot be revoked. |

## Local IIIF and processing — R2

| ID | Requirement | Acceptance |
|---|---|---|
| FR-104 | Serve IIIF Image API using existing server software, with stable local image IDs, truthful info.json dimensions and supported renditions for imported files. Choose versions/formats against actual Corpusense requirements (Q-102). | Representative UI requests for info.json, full image and region/size derivatives succeed; declared dimensions/profile match actual service capabilities. |
| FR-105 | Generate local Presentation manifests, and a collection index where needed, with explicit order, stable IDs, accurate canvas/image dimensions and reachable local image services. Preserve source/rights information. | Actual Corpusense imports the published material and displays its pages in order; check manifest structure against the chosen IIIF version and verify browser CORS behavior. |
| FR-107 | Supply collection image URLs reachable by Corpusense and current workers without changing the job submission/processing contract. | One real job submits through the existing interface and reads a published local input; a simulator alone does not satisfy acceptance. |
| FR-108 | Expose stable representation identity, checksum and actual image dimensions for recording alongside each processing attempt. A side record keyed by existing job/attempt IDs may carry this without changing the job envelope. Input records must not silently follow later replacement images. | The integration evidence identifies the exact file used; representation additions do not alter a recorded input. Do not add a new result store or task envelope. |
| FR-109 | Preserve a coordinate frame and mapping to the canonical page/canvas when known; record crop/rotation/scaling and any processing transform needed by exports. Never infer a reliable map solely from similar images. | A known region maps correctly from processed pixels to the source/canvas and back within a documented rounding tolerance. Initial fixtures may use full-page scaling; nontrivial alignment remains unsupported unless explicitly mapped. Unknown alignment is exposed, not fabricated. |

## Gallica Image proxy — R3

| ID | Requirement | Acceptance |
|---|---|---|
| FR-120 | Proxy only configured Gallica/BnF Image API hosts/routes, including info.json and images. Validate destinations at connection time and redirects; reject unsupported URLs. No Presentation API routes. | Supported paths succeed; non-allowlisted/unsafe destinations and redirects fail without unauthorized origin access; manifest routes are rejected. Reuse existing fetcher protections. |
| FR-121 | Corpusense fetches Gallica Presentation manifests directly and routes both info.json and image requests through the proxy. Document public base URLs and browser/CORS behavior. | Actual UI network evidence shows direct manifest retrieval and proxied image/info requests; requests derived from info.json do not accidentally bypass the proxy. No backend manifest rewriting. |
| FR-122 | Cache successful info/image responses with bounded storage and an explicit freshness policy, keyed by the effective upstream request/representation and any response-varying context. Do not silently substitute a lower-resolution collection image for an exact proxy request. | Repeated requests reuse cache without origin calls; different renditions do not collide; forced refresh/cache expiry and changed-response behavior are specified/tested before release. Old M-001 refetch/legacy-URL exceptions are not silently inherited. |
| FR-123 | Keep the dedicated upstream API key server-side. Configure a shared upstream rate/concurrency budget, bounded waits/retries and response byte/time limits; respect upstream throttling/backoff. User login and per-user accounting are deferred. | Isolated origin fixtures demonstrate bounded fan-out/retries, 429 handling and recovery; neither logs, public URLs, responses nor info.json disclose the key. Simultaneous misses do not create unbounded origin demand. |
| FR-124 | Distinguish cache hit/miss, upstream error/throttling and local overload in operator signals; preserve valid prior cache data after a failed refresh. | Operators can diagnose an injected failure; incomplete payloads never become successful cache entries; resources are released and subsequent healthy requests succeed. |

## Non-functional requirements

| ID | Requirement | Acceptance / release |
|---|---|---|
| NFR-100 | Durable metadata and raw files with restart safety and a documented coherent backup/restore method. | R1 restart/reopen checks; R2 isolated restore of the selected collection verifies metadata and checksums before shared use. No claim of off-host disaster recovery without off-host evidence. |
| NFR-101 | Restricted writes, least-privilege backend credentials, public reads only for approved published test material. TLS for remote admin/secret-bearing access; storage credentials stay server-side. | R1 negative mutation/draft-access tests; R2 publication/image visibility tests; R3 key-redaction and allowlist tests. Backend buckets need not be public. |
| NFR-102 | Bound request bytes, concurrent work, upstream waits/retries, disk use and diagnostic state; health remains responsive under saturation. | Configure and document finite limits for the actual host/corpus. Failure/overload tests demonstrate bounded behavior; values are chosen in B-101/B-104, not inferred from old defaults. |
| NFR-103 | Minimal observability: import/publication events, item status, checksums, timing, storage/errors; health and credential-safe structured logs. | R1 operator can diagnose an interrupted/failed import; IDs in logs, bounded-cardinality metric labels. No full tracing/dashboard platform prerequisite. |
| NFR-104 | Preserve current UI/job contracts and canonical provenance through the integration. | R2 real UI + real job + source-coordinate export evidence; disconnect/reconnect the browser and retrieve completed results through existing interfaces. Existing job lifetime/session behavior is verified, not reimplemented or assumed. |
| NFR-105 | Measure proxy cache outcomes, upstream requests/429s, latency, bytes, concurrency and local overload without credential leakage. | R3 bounded fixtures and real UI smoke; record measured results and limitations. No inherited 30-worker/1-TB/200-ms certification gate. |
| NFR-106 | Simple deployment and future-compatible references. | One-host documented startup/restart; application resource IDs are independent of endpoint/bucket/key. Single backend now; simultaneous routing/migration and replicas deferred. |

## API and implementation rules

- Document the concrete endpoints, accepted import schema, formats, configured
  limits and error/retry behavior before implementing their release. These specs
  deliberately do not invent a Corpusense task payload.
- Mutation attribution identifies the authorized operator credential; per-human
  accounts are not required in the pilot. Never accept a browser-supplied path as
  proof of ownership. No anonymous uploads or public administrative operations.
- Tests, logs/metrics and operator guidance accompany new behavior. Use isolated
  fixtures for destructive/error cases; live BnF is for bounded approved smoke only.
- Existing deployed capabilities, aliases, migrations and lifecycle state retain
  their current behavior until a separate implementation explicitly changes them.
