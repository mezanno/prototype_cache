# AGENTS Guide

## Mission

Build a production-shaped prototype of the **`asset-store`** module: a multi-tenant content/asset repository with an alias layer and a capability broker, used by asynchronous workers, upload services, and a thin admin UI. See [`docs/spec/README.md`](docs/spec/README.md) for the module identity and glossary.

The repo is named `prototype_cache` for historical reasons; the module name is `asset-store`. The repo will be renamed at code time, not before.

## Source Of Truth

Before coding, read in this order:

1. [`docs/PROJECT_ARCHITECTURE.md`](docs/PROJECT_ARCHITECTURE.md)
2. [`docs/spec/README.md`](docs/spec/README.md) and the spec files it lists.
3. [`docs/WORKPLAN.md`](docs/WORKPLAN.md)

If requirements conflict, update docs first, then implement.

## Operating Rules

- Keep outputs concise and directly actionable.
- Prefer incremental PRs with small blast radius.
- Do not add undocumented features.
- For every major technical choice, add/update an `ADR-*` row in [`docs/spec/03_ARCHITECTURE_AND_DECISIONS.md`](docs/spec/03_ARCHITECTURE_AND_DECISIONS.md).
- Add tests for every behavior change.
- Add/update metrics and logs for every new critical path.
- Discovery-stage notes in `docs/_archive/` and `docs/spec/_archive/` are read-only. Promote points into the active spec rather than editing the archive.

## Definition Of Done (Per Task)

- Requirement linked (`FR-*`/`NFR-*`).
- Code implemented with tests.
- Observability added (metrics/logging/tracing where relevant).
- Security implications reviewed (capability scope, audit trail).
- Docs updated.

## Suggested Work Order For Agents

1. Spec completion and ambiguity removal (`docs/spec/`).
2. Service scaffolding + CI baseline (`asset-registry`, `storage-guard`, dev compose stack).
3. Core ingestion path (write capability -> upload -> commit -> available).
4. Retrieval path for workers (read capability -> signed URL -> GET).
5. Reliability/security hardening (audit log, quotas, scoped tokens).
6. Operational readiness (dashboards, alerts, runbooks, backup).
