# asset-store prototype

Prototype for the `asset-store` module: immutable asset storage, alias registry,
and scoped capability checks for async workers and future IIIF/cache consumers.

## Goal

Define and validate a production-grade design for a deployable, testable, observable storage subsystem before selecting final technologies.

## Current implementation slice

The first code slice is deliberately small and infrastructure-free:

- `src/asset_store_core/` contains the executable domain model for assets,
  aliases, lifecycle transitions, audit events, and prefix-scoped capabilities.
- `tests/` pins the invariants from the spec before adding FastAPI, Postgres,
  or MinIO adapters.
- `services/`, `tools/`, and `deploy/` contain placeholders for the next
  implementation steps described in `docs/WORKPLAN.md`.

Run tests locally:

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

## Documentation

- Project architecture: `docs/PROJECT_ARCHITECTURE.md`
- Spec templates: `docs/spec/`
- Global execution plan: `docs/WORKPLAN.md`
- Agent operating guide: `AGENTS.md`
- Cursor rules for agents: `.cursor/rules/`
