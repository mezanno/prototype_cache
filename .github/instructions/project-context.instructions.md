---
description: Current collection/IIIF/proxy pilot context across this repository.
applyTo: "**"
---

# Collection and IIIF pilot context

- Owner-approved pivot: restricted custom collection upload/admin/storage → local IIIF publication → Gallica Image API proxy/cache. See `docs/spec/README.md` and `docs/WORKPLAN.md`.
- Keep existing Corpusense/job submission/processing interfaces unchanged; obtain real examples rather than treating worker-sim as the product protocol.
- The general asset-store programme is frozen; existing registry/guards/adapters/fetcher are selective reuse. No mandatory generic alias/capability layer, Supabase switch or package/repo rename.
- Public reads of approved published test material, restricted administrative writes. User/project auth, proxy login/metering, strict worker egress, multiple backends and agentic interfaces are follow-ups.
- Local collection manifests are generated. Gallica Presentation manifests are fetched directly by Corpusense, which routes Image API info/image requests through the proxy. No server-side Presentation proxy or manifest rewriting.
- Preserve raw files and canonical provenance, exact representation dimensions/checksum and export coordinate mapping. Collection retention is separate from disposable cache eviction.
- Keep `docs/spec/` authoritative. Record choices as ADRs and unknowns as Q rows; tests and relevant observability accompany behavior changes.
- `docs/history/asset-store/` preserves the superseded programme; old sequencing/handoffs are not current instructions. Existing runtime/security limitations remain true for reused code.
- Discovery archives `docs/_archive/` and `docs/spec/_archive/` are read-only. Preserve protected runtime/report/config files, migration history and owner images.
