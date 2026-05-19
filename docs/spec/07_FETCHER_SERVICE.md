# 07 - Fetcher Service

> Terms and acronyms: [`00B_GLOSSARY_AND_ACRONYMS.md`](00B_GLOSSARY_AND_ACRONYMS.md)

## At a glance

The **fetcher-service** materializes remote URLs into `asset-store`. It performs outbound HTTP, decides **cache hit vs miss**, and writes bytes to the correct MinIO bucket (`cache` or `tmp`). **asset-store never fetches remote URLs** ([`01_SCOPE.md`](01_SCOPE.md), [`ADR-008`](03_ARCHITECTURE_AND_DECISIONS.md)).

| Step | What happens |
|------|----------------|
| 1. Cache lookup | Normalize URL → derive cache alias candidates → resolve via storage-guard |
| 2. On hit | Return existing `asset_id` + alias (unless caller sets `no_cache`) |
| 3. On miss | HTTP GET remote origin |
| 4. Store | Cacheable domain → `cache/{remote_mirror_id}/…`; else → `tmp/{tmpid}/…` |
| 5. Return | `{ asset_id, qualified_alias, cache_hit, bucket, partition_id }` |

```mermaid
sequenceDiagram
  participant Caller as TaskAPI_or_Orchestrator
  participant Fetcher as fetcher_service
  participant Guard as storage_guard
  participant Registry as asset_registry
  participant S3 as object_store
  participant Remote as Remote_origin

  Caller->>Fetcher: ensure_url(url, opts)
  Fetcher->>Fetcher: normalize URL, derive cache aliases
  alt cache hit and not no_cache
    Fetcher->>Guard: resolve alias in cache
    Guard->>Registry: resolve
    Fetcher-->>Caller: existing asset_id + alias
  else miss or no_cache
    Fetcher->>Remote: HTTP GET
    alt domain cacheable
      Fetcher->>Guard: write cap cache/mirror_id/
      Fetcher->>S3: PUT presigned
      Fetcher->>Guard: commit
    else not cacheable
      Fetcher->>Guard: write cap tmp/tmpid/
      Fetcher->>S3: PUT presigned
      Fetcher->>Guard: commit
    end
    Fetcher-->>Caller: new asset_id + alias
  end
```

**Callers:** task-api, task orchestrator, and (indirectly) workers that receive aliases in task definitions. **Not** asset-store, **not** workers talking to heritage sites directly.

---

## Scope

### In scope (fetcher module)

- `ensure_url` API (name provisional) for idempotent URL materialization.
- URL normalization and cache-alias derivation (see [`Q-021`](05_BACKLOG_AND_OPEN_QUESTIONS.md)).
- Domain allowlist policy: which origins may be written to `cache` ([`Q-022`](05_BACKLOG_AND_OPEN_QUESTIONS.md)).
- HTTP client: timeouts, max body size, redirect limit, SSRF controls.
- Integration with asset-store only: reserve → PUT → commit via storage-guard.
- Observability: cache hit rate, fetch errors, bytes ingested.

### Out of scope

- Image processing, IIIF tile generation, manifest editing.
- User authentication (delegated to upstream APIs).
- Virus scanning (caller's responsibility before or after fetch; contract in [`01_SCOPE.md`](01_SCOPE.md)).
- **`iiif_server_cache`** bucket — managed directly by the IIIF server, not via this service ([`03_ARCHITECTURE_AND_DECISIONS.md`](03_ARCHITECTURE_AND_DECISIONS.md)).

---

## API (draft)

### `POST /v1/ensure-url`

**Request (JSON)**

| Field | Required | Description |
|-------|----------|-------------|
| `url` | yes | Remote URL to materialize |
| `mirror_id` | yes for cache path | Partition under `cache` (e.g. `gallica`, `bnf`) |
| `no_cache` | no | If `true`, skip cache lookup and force refetch |
| `tmp_id` | no | Partition under `tmp` when not cacheable; server may assign |
| `preferred_alias_suffix` | no | Hint for alias tail under partition |
| `ttl_seconds` | no | Hint for asset TTL (esp. `tmp`) |

**Response (JSON)**

| Field | Description |
|-------|-------------|
| `asset_id` | Opaque id from asset-store |
| `qualified_alias` | e.g. `cache/gallica/bnf/ark-…/default.jpg` |
| `cache_hit` | `true` if served from existing cache alias |
| `bucket` | `cache` or `tmp` |
| `partition_id` | Mirror id or tmp id |

**Errors:** `400` invalid URL; `403` policy denied; `502` upstream fetch failed; `504` upstream timeout.

---

## Cache vs tmp decision

| Condition | Bucket | Partition | Typical TTL |
|-----------|--------|-----------|-------------|
| Origin domain ∈ cache allowlist | `cache` | `{remote_mirror_id}` | Long / infinite |
| Otherwise | `tmp` | `{tmpid}` | Short ([`Q-020`](05_BACKLOG_AND_OPEN_QUESTIONS.md)) |
| Caller `no_cache: true` | Same as policy after fetch | — | — |

Examples of **tmp** use ([`01_SCOPE.md`](01_SCOPE.md)):

- Task input URL on a non-cacheable domain.
- One-shot remote resource not promoted to cache.
- Inline/base64-equivalent payloads staged by task-api (may skip HTTP; still uses `tmp` bucket).

---

## Service identity and asset-store permissions

Fetcher authenticates to storage-guard as `fetcher`. See service matrix in [`03_ARCHITECTURE_AND_DECISIONS.md`](03_ARCHITECTURE_AND_DECISIONS.md).

| Operation | Allowed buckets |
|-----------|-----------------|
| Read (resolve) | `cache`, `tmp` |
| Write (reserve/commit) | `cache`, `tmp` |

Fetcher must **not** write `users` or `results`.

---

## Relationship to the IIIF server and the IIIF mirror/proxy

The archived discovery docs described an "IIIF proxy" prefetching remote images. That concept has since split into **two distinct future modules** with different responsibilities. Fetcher-service is the general URL-materialization layer that both will rely on.

| Aspect | IIIF server (`iiif-server`) | IIIF image mirror (`iiif-image-mirror`) |
|--------|-----------------------------|-----------------------------|
| **Role** | Serve stored assets via IIIF Image API | Relay heritage IIIF Image API requests; cache responses |
| **Reads from asset-store** | `cache`, `users` (via presigned GET) | `cache` only (via presigned GET) |
| **Writes to asset-store** | None — writes only to its own `iiif_server_cache` tile bucket | None directly — all cache writes delegated to fetcher-service |
| **Fetches remote URLs** | No | Via fetcher-service (`cache/{mirror_id}/…`) |
| **IIIF Presentation manifests** | May read; does not compose | Must **not** rewrite manifests to point at itself |
| **IIIF Image API** | Serves from stored assets | Relays and caches from authoritative heritage endpoints |
| **Client awareness** | Transparent to client | Client must actively point at mirror; no impersonation |
| **In scope for asset-store MVP** | Surveyed for later | No (future separate module) |

### IIIF server

The IIIF server's goal is to serve content already stored in asset-store in a IIIF Image API-compatible format (other efficient distribution protocols may be studied in the future). It is a **reader** of asset-store, not a fetcher and not a mirror. It owns and manages `iiif_server_cache` independently for derived tile storage; that bucket is not provisioned or written by asset-store.

### IIIF image mirror

The IIIF image mirror (`iiif-image-mirror`) is a **separate future module** whose goal is reliable, user-accessible caching of heritage images served by national libraries and similar authoritative repositories via the IIIF Image API.

Key characteristics:

- **IIIF Image API only** — no Presentation API, no manifest relay, no manifest rewriting.
- **End-user facing** — it has its own access-control layer for end users (outside asset-store’s service-identity model); asset-store only sees the module’s service identity (`iiif-image-mirror`).
- **Cache backend** — uses fetcher-service and the asset-store `cache` bucket; all ingestion follows the standard reserve → PUT → commit flow.
- **Reads from asset-store** — `cache` only, via presigned GET from storage-guard.
- **No writes to asset-store** — cache population is delegated entirely to fetcher-service.
- **Separate service** — distinct codebase and deployment from `iiif-server`.
- **Client awareness** — clients must explicitly point requests at the mirror; the mirror does not impersonate the upstream repository.

**Open question — derivative generation ([`Q-026`](05_BACKLOG_AND_OPEN_QUESTIONS.md)):** Full IIIF Image API compliance (beyond level 0) requires serving arbitrary region/size/rotation combinations, which typically means generating image derivatives rather than proxying verbatim responses. Generating derivatives internally risks subtle divergence from the upstream server’s rendering. The advantage (full Image API compliance, reduced upstream load) must be weighed against this risk before a decision is made. If derivatives are stored, a dedicated tile bucket (separate from the asset-store `cache` bucket) is the preferred approach, mirroring the `iiif_server_cache` pattern used by `iiif-server`.

Whether this module is needed at all is tracked as [`B-021`](05_BACKLOG_AND_OPEN_QUESTIONS.md).

---

## Scenario

See **SCN-007** in [`00A_SCENARIOS.md`](00A_SCENARIOS.md).

---

## Open questions

| ID | Topic |
|----|--------|
| Q-021 | Cache alias derivation: single canonical alias vs multiple per mirror |
| Q-022 | Domain allowlist storage and ownership |
| Q-023 | Fetcher MVP phase relative to asset-store Phase 2 |
| Q-020 | Default `tmp` TTL and GC ([`05_BACKLOG_AND_OPEN_QUESTIONS.md`](05_BACKLOG_AND_OPEN_QUESTIONS.md)) |

---

## Requirements trace (informal)

Fetcher implements platform behavior referenced by task flows; asset-store requirements **FR-010**–**FR-015**, **FR-020**–**FR-022** apply to the guard/registry calls fetcher makes. Dedicated `FR-F*` rows may be added when fetcher is implemented in its own repo.
