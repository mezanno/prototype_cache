# Implementation Notes

How the **current code** relates to the spec, and deliberate shortcuts for the prototype phase.

## What is implemented today

| Layer | Status |
|-------|--------|
| `asset_store_core` | In-memory registry, paths, buckets/partitions, object keys, capabilities, service policy |
| storage-guard (HTTP) | **Not implemented** — see below |
| MinIO / Postgres | **Not implemented** |

Run tests:

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

### Spec alignment (ADR-007)

- Registry `space` = MinIO bucket (`cache`, `tmp`, `users`, `results`).
- `partition_id` on every asset; `storage_key` = `{partition_id}/assets/{asset_id}`.
- Qualified aliases: `{bucket}/{partition_id}/…` (e.g. `users/42/uploads/photo.jpg`).
- `service_policy` encodes FR-015 bucket allowlists (used in tests; not wired into registry calls).

## Deferring storage-guard for early development

**Yes — reasonable for this prototype phase**, because:

1. **There is no guard service yet** — only domain types (`Capability`, `SingleUseLedger`) and `assert_service_bucket_allowed()`.
2. **Unit tests already bypass the guard** — they call `InMemoryAssetRegistry` directly, which matches how you validate registry rules quickly.
3. **Recommended order:**
   - Registry + MinIO adapter (reserve / PUT / commit / resolve) with direct calls in integration tests.
   - Add a thin **guard facade** that composes `service_policy` + capability checks + registry.
   - HTTP server last.

**Do not delete guard concepts from the spec** — FR-010–FR-015 remain the production contract. When adding HTTP, re-enable policy checks in one place rather than spreading auth in every caller.

For integration tests before the guard exists, either:

- Call registry + MinIO directly (documented shortcut), or
- Call `assert_service_bucket_allowed()` manually before writes to rehearse FR-015.

## “Are we just building a filesystem on S3?”

**Partly — and that is intentional, but it is not only paths on disk.**

| Layer | Off-the-shelf? | What we use |
|-------|----------------|-------------|
| Raw blob store | **Yes** | MinIO / S3 ([`ADR-001`](spec/03_ARCHITECTURE_AND_DECISIONS.md), [`06_OSS_SURVEY.md`](spec/06_OSS_SURVEY.md)) |
| Aliases + lifecycle + multi-name + audit | **No single match** | Custom registry (ADR-002 rejected InvenioRDM etc. as overshoot) |
| Prefix-scoped, short-lived credentials | **Partial** | S3 presigned URLs + our guard semantics |
| Heritage-specific fetch + cache policy | **No** | Planned fetcher-service |

Products that look similar and why we did not adopt them as the whole stack:

| Product | Overlap | Gap vs our spec |
|---------|---------|-----------------|
| **MinIO / AWS S3 alone** | Buckets + keys | No alias layer, no `pending→available`, no per-task capabilities |
| **Nextcloud / Seafile** | User files | User-sync model, not service identities + worker aliases |
| **InvenioRDM / Fedora** | Repository + files | Record/RDF centric; heavy deps; wrong mutability model |
| **rclone / s3fs / goofys** | Mount S3 as filesystem | No alias immutability, audit, or capability broker |
| **LakeFS** | Versioned object branches | Git-like branching, not citation-stable aliases |

So: **we are not replacing S3** — we are adding a **thin control plane** (registry + guard) for things S3 does not standardize: multiple stable names per blob, lifecycle states, service-scoped access, and audit. That is smaller than a full DAM or institutional repository.

If requirements shrink to “store files per user with ACLs only,” revisiting **Nextcloud** or **Garage + a tiny metadata DB** could be worth a spike ([`Q-009`](spec/05_BACKLOG_AND_OPEN_QUESTIONS.md)). The current spec (immutable assets, alias grace, fetcher, worker results) justifies the custom layer.

## Related spec docs

- Storage layout: [`spec/03_ARCHITECTURE_AND_DECISIONS.md`](spec/03_ARCHITECTURE_AND_DECISIONS.md)
- Jargon: [`spec/00B_GLOSSARY_AND_ACRONYMS.md`](spec/00B_GLOSSARY_AND_ACRONYMS.md)
- OSS survey: [`spec/06_OSS_SURVEY.md`](spec/06_OSS_SURVEY.md)
