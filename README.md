# asset-store prototype

Prototype for the `asset-store` module: immutable asset storage, alias registry,
and scoped capability checks for async workers and future IIIF/cache consumers.

## Goal

Define and validate a production-grade design for a deployable, testable, observable storage subsystem before selecting final technologies.

## Current implementation slice

The slice is infrastructure-free (in-memory backend; no Postgres or real S3 yet) but
now spans the full request path end to end:

- `src/asset_store_core/` — registry, **four storage buckets** (`cache`, `tmp`,
  `users`, `results`), `partition_id`, object keys `{partition}/assets/{asset_id}`,
  an object-store backend seam (`ObjectStoreBackend` + in-memory `LocalObjectStore`),
  prefix-scoped capabilities, **service→bucket policy** (FR-015), and a `StorageGuard`
  facade composing capability + policy + registry/object-store calls.
- `src/asset_store_core/api/` — a FastAPI app (single process, ADR-002):
  `/healthz`, `/readyz`, `/metrics`, reserve/commit/resolve, capability mint, and a
  capability-guarded data plane (`PUT`/`GET /objects/{alias}`, FR-010..015) using
  `Authorization: Capability <id>` bearer tokens. Errors use RFC 7807
  `application/problem+json`; observability (ADR-013) adds Prometheus metrics,
  structured JSON logs, and an `X-Correlation-Id` per request.
- `tests/` — 72 unit/integration/contract tests, all green.
- `services/`, `tools/`, `deploy/` — placeholders per `docs/WORKPLAN.md`.

Run the tests and the API locally (uv-managed env):

```bash
uv run pytest -q
uv run uvicorn asset_store_core.api:create_app --factory --reload
```

The app is exposed as a factory at `asset_store_core.api:create_app`; the in-memory
backend means it starts with no external dependencies.

## Documentation

- Implementation status & design FAQ: `docs/IMPLEMENTATION_NOTES.md`
- Project architecture: `docs/spec/03_ARCHITECTURE.md`
- Spec: `docs/spec/` (glossary at the end of `docs/spec/README.md`)
- Global execution plan: `docs/WORKPLAN.md`
- Agent operating guide: `AGENTS.md`
- Cursor rules for agents: `.cursor/rules/`
