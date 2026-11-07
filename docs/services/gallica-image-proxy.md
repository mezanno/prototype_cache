# Gallica Image API proxy/cache — active contract

**Planned M-002/R3; Image API only.** FR-120..124 and ADR-046/047 apply. Existing
`fetcher_service` is selective reuse, not proof this contract is implemented.

## Client boundary

Corpusense fetches Gallica **Presentation manifests directly**. It internally
routes Image API requests through the proxy, including info.json and image URLs
derived from manifests or image information. No Presentation proxy endpoints,
server-side manifest rewriting, composition or local replacement of canonical
upstream identifiers. Preserve source IDs in collection/job metadata.

Before B-108 acceptance, document proxy base URLs and browser/CORS behavior with
actual Corpusense requests. Choose whether info.json needs narrow service-base
URL adaptation or the UI intercepts all resulting image URLs (Q-105). It must not
accidentally send derived requests straight to BnF. This is not a manifest rewrite.

## Origin and credentials

- Allow only configured BnF Image hosts/versions/paths and validate every redirect
  and connection destination. Reuse existing SSRF/TLS protections; this is not an
  arbitrary-URL proxy. Reject manifests and unsupported/ambiguous paths.
- Add the dedicated API key only server-side according to BnF's actual mechanism.
  Never return/log it or accept arbitrary downstream credentials to forward.
  Expected higher quotas are not assumed available until documented/configured.
- User authentication and per-user metering are deferred. A finite shared origin
  rate/concurrency budget, bounded waits/retries/body size and timeout apply now.
  Respect 429/backoff; repeated/simultaneous misses cannot create unbounded fan-out.

## Cache semantics

Transparent supported image/info requests fetch on a miss and reuse successful
cached responses. This supersedes M-001's mandatory explicit-preload/cache-only
rule for R3; it does not change the old facade's behavior automatically. Preload
may remain an operator convenience, not a required user step.

Choose effective request keys, freshness, changed-origin and force-refresh policy
in Q-105 before implementation acceptance. Distinct region/size/rotation/format
and any response-varying context must not collide. Retain complete successful
responses only; failed refresh does not destroy valid prior cache bytes.
Do not serve a smaller preloaded collection image as an exact upstream rendition,
inherit legacy native/default merging indiscriminately, or infer equivalence from
similar pixels. Cache storage is disposable and separate from retained collections.

## Acceptance and operations

SCN-104/105: actual UI shows direct manifests and proxied info/image requests;
repeat requests generate no origin call; isolated fixtures cover rendition keys,
redirect policy, 429, timeouts/partial bodies, storage failure, resource release and
healthy recovery. Check key redaction across logs/URLs/headers/JSON responses.
Record cache outcomes, origin calls/throttling/errors, bytes/latency, inflight and
local overload with finite label cardinality. Finish with a bounded approved real
BnF/UI smoke, not live failure injection or an unrestricted benchmark.
