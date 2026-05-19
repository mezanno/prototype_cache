# asset-store prototype

Prototype for the `asset-store` module: immutable asset storage, alias registry,
and scoped capability checks for async workers and future IIIF/cache consumers.

## Goal

Define and validate a production-grade design for a deployable, testable, observable storage subsystem before selecting final technologies.

## Current implementation slice

The first code slice is deliberately small and infrastructure-free:

- `src/asset_store_core/` — registry, **four storage buckets** (`cache`, `tmp`,
  `users`, `results`), `partition_id`, object keys `{partition}/assets/{asset_id}`,
  capabilities, and **service→bucket policy** (FR-015).
- `tests/` — spec invariants (32 tests); no HTTP, Postgres, or MinIO yet.
- **storage-guard** — not implemented; tests call the registry directly (see
  [`docs/IMPLEMENTATION_NOTES.md`](docs/IMPLEMENTATION_NOTES.md)).
- `services/`, `tools/`, `deploy/` — placeholders per `docs/WORKPLAN.md`.

Run tests locally:

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

## Documentation

- Implementation status & design FAQ: `docs/IMPLEMENTATION_NOTES.md`
- Project architecture: `docs/PROJECT_ARCHITECTURE.md`
- Spec: `docs/spec/` (start with `00B_GLOSSARY_AND_ACRONYMS.md` if terms are unfamiliar)
- Global execution plan: `docs/WORKPLAN.md`
- Agent operating guide: `AGENTS.md`
- Cursor rules for agents: `.cursor/rules/`
