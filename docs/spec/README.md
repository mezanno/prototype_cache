# Specification

This folder is the source of truth for the `asset-store` module (formerly named `prototype_cache`).

## Module identity

`asset-store` is a multi-tenant content/asset repository with three internal layers:

- **`object-store`** - layer 1, S3-compatible distributed blob store (vendored OSS, e.g. MinIO).
- **`asset-registry`** - layer 2, the asset/metadata/lifecycle service mapping each `asset_id` to one or more **aliases** (logical names) with a `pending -> available -> expired -> deleted` lifecycle.
- **`storage-guard`** - layer 3, a capability broker that mints short-lived, prefix-scoped tokens or signed URLs for upload services and workers, and emits an audit log.

It is **not** an image cache in isolation. The "cache" use case (mirroring distant IIIF images) is one of several consumers of the same asset store, alongside user uploads and worker artifacts.

## Reading order

1. [`01_SCOPE.md`](01_SCOPE.md) - what is in/out of scope and success criteria.
2. [`00A_SCENARIOS.md`](00A_SCENARIOS.md) - concrete MVP scenarios (SCN-001..005).
3. [`02_REQUIREMENTS.md`](02_REQUIREMENTS.md) - `FR-*`, `NFR-*` with measurable targets and acceptance criteria.
4. [`06_OSS_SURVEY.md`](06_OSS_SURVEY.md) - off-the-shelf candidates and finalist architectures.
5. [`03_ARCHITECTURE_AND_DECISIONS.md`](03_ARCHITECTURE_AND_DECISIONS.md) - `ADR-*` log, component table, data model, state machine.
6. [`04_OPERATIONS_AND_READINESS.md`](04_OPERATIONS_AND_READINESS.md) - SLI/SLO, metrics, alerts, testing strategy.
7. [`05_BACKLOG_AND_OPEN_QUESTIONS.md`](05_BACKLOG_AND_OPEN_QUESTIONS.md) - `Q-*`, `R-*`, `B-*`.

Discovery-stage inputs are archived in [`_archive/`](_archive/) and must not be edited.

## Glossary

- **Asset** - a single immutable payload (binary blob, e.g. an image or a PDF) stored in the `object-store` and tracked by the `asset-registry`. Identified by an opaque, server-assigned `asset_id`.
- **Alias** - a human- or service-meaningful name for an asset (e.g. `space/u-42/uploads/photo.jpg`, `space/cache/iiif/gallica/ark:/12148/btv1b...`, or `ark:/<naan>/<suffix>`). One asset can have multiple aliases. An alias is unique within its namespace and, by default, is bound to its `asset_id` for life (single-binding-for-life). See **Mutable alias** for the explicit opt-in to rebinding.
- **Mutable alias** - an alias created with the explicit flag `mutable: true`. May be rebound to a different `asset_id` via an audited `alias.rebind` operation. The flag is set at create time and is itself immutable. Default for every alias is `mutable: false`; this default is what historians and citation systems rely on.
- **Space** - a top-level namespace owned by a tenant (user, team, project, or service). Determines quota, ownership, and the alias prefix. Example space ids: `cache`, `u-42`, `proj-archives`, `results-task-987`.
- **Capability** - a short-lived, prefix-scoped credential issued by the `storage-guard` to allow a specific operation (read or write) on a specific alias prefix for a bounded duration. Implemented either as an S3 presigned URL or as a server-issued token validated by a proxy.
- **Signed URL** - one concrete form of capability: a direct URL to the `object-store` containing a time-bounded signature. Used when the consumer can talk to the `object-store` directly.
- **Storage guard** - the layer 3 service. Single point that authorizes operations on aliases, mints capabilities, and writes the audit log.
- **OCFL** - Oxford Common File Layout, a write-once on-disk layout for digital preservation. Influences the `asset-registry` storage layout and immutability guarantees.
- **ARK** - Archival Resource Key, a persistent identifier scheme (`ark:/<naan>/<suffix>`). Candidate scheme for public-facing aliases.
- **State** - the lifecycle position of an asset: `pending` (alias reserved, payload not yet uploaded), `available` (payload present and readable), `expired` (TTL reached, not readable, not yet garbage-collected), `deleted` (garbage-collected, payload removed).
- **Audit log** - append-only structured log emitted by the `storage-guard` and `asset-registry` recording capability issuance, alias mutations, lifecycle transitions, and admin actions.

## Writing rules

- Prefer measurable requirements over vague statements (no "fast", "robust", "secure" without a number or a method).
- Capture decisions with rationale and alternatives in the ADR log.
- Mark unknowns explicitly as `Q-*` rows in [`05_BACKLOG_AND_OPEN_QUESTIONS.md`](05_BACKLOG_AND_OPEN_QUESTIONS.md); do not hide assumptions in prose.
- Keep one source of truth per topic. Cross-link rather than duplicate.
