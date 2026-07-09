# fetcher-service

Remote-URL materialization for the `asset-store` module ([`ADR-008`](../../docs/spec/03_ARCHITECTURE.md#adr-log)): the fetcher performs the outbound HTTP that asset-store never does, decides cache hit vs miss, and writes bytes into `cache/{mirror_id}/…` (or stages non-cacheable URLs in `tmp/{tmp_id}/…`). The full contract is [`docs/services/fetcher-service.md`](../../docs/services/fetcher-service.md); the scenario is SCN-007.

**Phasing (Q-023, resolved):** an **in-repo** service that talks to asset-store over **HTTP+JSON** like any other caller ([`ADR-017`](../../docs/spec/03_ARCHITECTURE.md#adr-log)). Delivered in two steps (B-020):

- **Step 1 — stub (done):** the `ensure_url` control flow — URL normalization, the declarative URL→alias rewrite-rule set ([`ADR-014`](../../docs/spec/03_ARCHITECTURE.md#adr-log), incl. IIIF dedup), cache lookup, and store-through-guarded-proxy — with a **no-network `SyntheticFetcher`** that emits deterministic JSON derived from the URL.
- **Step 2 — the cache (next):** a real HTTP fetcher (timeouts, max body, redirect limit, SSRF controls), multi-alias attachment, and byte-identity dedup.

The implementation lives in [`src/fetcher_service/`](../../src/fetcher_service/); tests are in [`tests/test_fetcher_service.py`](../../tests/test_fetcher_service.py).

## Transport

Control plane (capability mint, `resolve`, `reserve`, `commit`) and data plane (payload bytes) both run over HTTP+JSON; uploads use the guarded proxy `PUT /objects/{alias}`. The performance path is presigned upload direct-to-S3 ([`ADR-003`](../../docs/spec/03_ARCHITECTURE.md#adr-log) / [`R-013`](../../docs/spec/05_BACKLOG_AND_OPEN_QUESTIONS.md)), **not** a second RPC protocol.

## Run (dev)

```bash
# against a running asset-store on :8080 (dev service secret defaults to dev-secret:fetcher)
ASSET_STORE_BASE_URL=http://localhost:8080 \
  uv run uvicorn --factory fetcher_service.app:create_app --port 8090
```
