# fetcher-service

Remote-URL materialization for the `asset-store` module ([`ADR-008`](../../docs/spec/03_ARCHITECTURE.md#adr-log)): the fetcher performs the outbound HTTP that asset-store never does, decides cache hit vs miss, and writes bytes into `cache/{mirror_id}/…` (or stages non-cacheable URLs in `tmp/{tmp_id}/…`). The full contract is [`docs/services/fetcher-service.md`](../../docs/services/fetcher-service.md); the scenario is SCN-007.

**Phasing (Q-023, resolved):** an **in-repo** service that talks to asset-store over **HTTP+JSON** like any other caller ([`ADR-017`](../../docs/spec/03_ARCHITECTURE.md#adr-log)). Delivered in two steps (B-020):

- **Step 1 — stub (done):** the `ensure_url` control flow — URL normalization, the declarative URL→alias rewrite-rule set ([`ADR-014`](../../docs/spec/03_ARCHITECTURE.md#adr-log), incl. IIIF dedup), cache lookup, and store-through-guarded-proxy — with a **no-network `SyntheticFetcher`** that emits deterministic JSON derived from the URL.
- **Step 2 — the cache (in progress):** a real `HttpFetcher` (connect/read timeouts, max body size, redirect limit, and default-deny SSRF controls) is **done**; a checksum-mismatch correctness detector (R-011) and a Garage-gated end-to-end test remain. Dedup is by canonical alias (name); content-addressed storage dedup is deferred, per-space opt-in ([`Q-035`](../../docs/spec/05_BACKLOG_AND_OPEN_QUESTIONS.md)).

The implementation lives in [`src/fetcher_service/`](../../src/fetcher_service/); tests are in [`tests/test_fetcher_service.py`](../../tests/test_fetcher_service.py).

## Transport

Control plane (capability mint, `resolve`, `reserve`, `commit`) and data plane (payload bytes) both run over HTTP+JSON; uploads use the guarded proxy `PUT /objects/{alias}`. The performance path is presigned upload direct-to-S3 ([`ADR-003`](../../docs/spec/03_ARCHITECTURE.md#adr-log) / [`R-013`](../../docs/spec/05_BACKLOG_AND_OPEN_QUESTIONS.md)), **not** a second RPC protocol.

## Run (dev)

```bash
# against a running asset-store on :8080 (dev service secret defaults to dev-secret:fetcher)
ASSET_STORE_BASE_URL=http://localhost:8080 \
  uv run uvicorn --factory fetcher_service.app:create_app --port 8090
```

## Configuration

| Env var | Default | Purpose |
| --- | --- | --- |
| `ASSET_STORE_BASE_URL` | `http://localhost:8080` | asset-store control/data plane base URL |
| `FETCHER_SERVICE_ID` | `fetcher` | service identity used for capability minting |
| `FETCHER_SERVICE_SECRET` | `dev-secret:fetcher` | shared secret for the `Service` auth scheme |
| `FETCHER_RULES_FILE` | _(built-in default rule set)_ | path to a TOML URL→alias rewrite-rule file |
| `FETCHER_SYNTHETIC` | `0` | when truthy (`1`/`true`/`yes`), use the no-network `SyntheticFetcher` instead of real HTTP |
| `FETCHER_HTTP_CONNECT_TIMEOUT` | `5.0` | outbound connect timeout (seconds) |
| `FETCHER_HTTP_READ_TIMEOUT` | `30.0` | outbound read timeout (seconds) |
| `FETCHER_HTTP_MAX_BYTES` | `52428800` (50 MiB) | maximum response body accepted before aborting |
| `FETCHER_HTTP_MAX_REDIRECTS` | `5` | maximum redirects followed (each hop re-validated for SSRF) |
| `FETCHER_ALLOW_PRIVATE_HOSTS` | `0` | when truthy, permits fetching private/loopback addresses (tests only) |

The `HttpFetcher` blocks requests to private, loopback, link-local, reserved, multicast, and unspecified addresses by default (SSRF protection), resolving each hostname and re-validating after every redirect. DNS-rebinding (TOCTOU between validation and connect) is an accepted prototype limitation.
