# AGENTS Guide

## Mission

Deliver custom collection upload/admin/storage, local IIIF publication for
Corpusense and existing workers, then an allowlisted Gallica **Image API**
proxy/cache. The owner accepted the pivot on 2026-11-07; see
[`docs/spec/README.md`](docs/spec/README.md) and [`docs/WORKPLAN.md`](docs/WORKPLAN.md).
The current job submission/processing system remains unchanged.

The general `asset-store` programme is frozen. Existing `asset_store_core` and
`fetcher_service` code is available for selective reuse; universal aliases,
capability brokerage or completion of M-001 must not become prerequisites.
The historical repo/package names do not imply a rename task.

## Source Of Truth

Before coding, read in this order:

1. [`docs/spec/README.md`](docs/spec/README.md) and the spec files it lists (the glossary is at the end of the README if jargon is unfamiliar).
2. [`docs/spec/03_ARCHITECTURE.md`](docs/spec/03_ARCHITECTURE.md) for architecture and ADRs.
3. [`docs/WORKPLAN.md`](docs/WORKPLAN.md)

If requirements conflict, update docs first, then implement.

## Operating Rules

- Keep outputs concise and directly actionable.
- Prefer incremental PRs with small blast radius.
- Do not add undocumented features.
- For every major technical choice, add/update an `ADR-*` row in [`docs/spec/03_ARCHITECTURE.md`](docs/spec/03_ARCHITECTURE.md).
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

1. B-101: first collection/import contract and actual Corpusense/job integration inputs.
2. R1: durable raw files/catalog, restricted admin/API, retryable import and publication status.
3. R2: existing IIIF Image engine, generated local manifests, real UI/job and source-coordinate proof.
4. R3: Image-only Gallica proxy/cache; Corpusense fetches manifests directly and routes image requests.
5. Later: user/project authorization, proxy metering, worker egress, multiple backends and agentic interfaces.

Public reads apply only to approved published test material; writes stay restricted.
Preserve canonical source/provenance and exact representation/coordinate metadata.
Keep archives, runtime data, private reports/config, migrations and owner images
intact. No cleanup, workload, deployment, rename, commit or push is implicit in a
documentation update. Use the active plan rather than historical pauses/next steps.
