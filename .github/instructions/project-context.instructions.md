---
description: Core project context for asset-store work across this repository.
applyTo: "**"
---

# Asset-Store Project Context

- The module under development is `asset-store`: a multi-tenant content/asset repository with three internal layers (`object-store`, `asset-registry`, `storage-guard`). The repo is still named `prototype_cache` for historical reasons.
- Treat `docs/spec/` as the requirements source of truth. The reading order and glossary live in `docs/spec/README.md`.
- Discovery-stage notes live under `docs/_archive/` and `docs/spec/_archive/` and are read-only; promote points into the active spec rather than editing the archive.
- Prefer measurable requirements and explicit assumptions; mark unknowns as `Q-*` rows in `docs/spec/05_BACKLOG_AND_OPEN_QUESTIONS.md`.
- For every major technical choice, update the ADR table in `docs/spec/03_ARCHITECTURE.md`.
- Out of scope for the prototype: image processing, remote URL fetching, IIIF serving, end-user authentication.
- In scope for the prototype: durable storage, alias/metadata/lifecycle, short-lived prefix-scoped capabilities, audit log, admin UI, bulk loader, worker simulator.
- Keep implementation, tests, and observability aligned with the spec.