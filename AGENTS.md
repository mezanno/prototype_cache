# AGENTS Guide

## Mission

Build a production-shaped prototype for image storage/cache used by asynchronous workers.

## Source Of Truth

Before coding, read:

1. `docs/PROJECT_ARCHITECTURE.md`
2. `docs/spec/01_SCOPE.md` to `docs/spec/05_BACKLOG_AND_OPEN_QUESTIONS.md`
3. `docs/WORKPLAN.md`

If requirements conflict, update docs first, then implement.

## Operating Rules

- Keep outputs concise and directly actionable.
- Prefer incremental PRs with small blast radius.
- Do not add undocumented features.
- For every major technical choice, add/update an ADR row in `03_ARCHITECTURE_AND_DECISIONS.md`.
- Add tests for every behavior change.
- Add/update metrics and logs for every new critical path.

## Definition Of Done (Per Task)

- Requirement linked (`FR-*`/`NFR-*`).
- Code implemented with tests.
- Observability added (metrics/logging/tracing where relevant).
- Security implications reviewed.
- Docs updated.

## Suggested Work Order For Agents

1. Spec completion and ambiguity removal.
2. Service scaffolding + CI baseline.
3. Core ingestion path.
4. Retrieval path for workers.
5. Reliability/security hardening.
6. Operational readiness (dashboards, alerts, runbooks).
