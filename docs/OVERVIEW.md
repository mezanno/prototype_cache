# asset-store — architecture & progress

> **Checkpoint: 2026-09-26 · B-013 implemented (uncommitted) · Next: B-018 security review**
>
> Working ingestion, retrieval and cleanup prototype. Production readiness remains open.

**Purpose:** a shared repository for remote content, user uploads and worker results.
Callers use stable **aliases**; asset-store owns metadata, access capabilities and
lifecycle, while existing S3 software stores the bytes.

**Legend:** 🟢 **Implemented** = working and tested in the prototype · 🟡 **Partial** = gaps remain
· 🔵 **Simulated** = test substitute · ⚪ **Planned** = not delivered here.
Status words accompany colors. No implementation task is currently in progress.

## Architecture at a glance

Solid arrows show implemented connections; dashed arrows show planned integration.
The service box is **one FastAPI process**, not three microservices.

```mermaid
flowchart TB
    origin["Remote HTTP origins"]
    fetch["IMPLEMENTED · fetcher-service<br/>URL rules, fetch and cache policy"]
    bulk["IMPLEMENTED · bulk-loader CLI<br/>Batch ingestion"]
    worker["SIMULATED · worker-sim CLI<br/>Verified reads and result publication"]
    edge["PLANNED · upload-api / task-api<br/>User authorization and task dispatch"]
    admin["IMPLEMENTED · admin-ui<br/>Inspect assets and operate lifecycle"]

    subgraph service["asset-store · single service"]
        api["IMPLEMENTED · HTTP API<br/>Caller-facing control and data paths"]
        guard["IMPLEMENTED · storage-guard<br/>Service auth and scoped capabilities"]
        registry["IMPLEMENTED · asset-registry<br/>Aliases, metadata, quotas and audit"]
        adapter["IMPLEMENTED · S3 adapter<br/>Store bytes and sign GET URLs"]
        api --> guard
        guard --> registry
        guard --> adapter
        api --> registry
    end

    pg[("IMPLEMENTED · Postgres<br/>Metadata and audit")]
    s3[("IMPLEMENTED · Garage / S3<br/>cache · tmp · users · results")]
    gc["IMPLEMENTED · lifecycle worker CLI<br/>Expiry and retryable cleanup<br/>Separate process; dry-run default"]

    origin --> fetch
    fetch --> api
    bulk --> api
    worker --> api
    edge -.-> api
    admin --> api
    registry --> pg
    adapter --> s3
    worker -->|"Optional presigned GET"| s3
    gc -->|"Registry adapter"| pg
    gc -->|"Delete payloads"| s3

    classDef done fill:#dcfce7,stroke:#15803d,color:#14532d
    classDef simulated fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef planned fill:#f1f5f9,stroke:#64748b,color:#334155,stroke-dasharray:5 5
    class fetch,bulk,api,guard,registry,adapter,pg,s3,gc,admin done
    class worker simulated
    class edge planned
```

**Current byte paths:** writes are proxied through the guard (reserve → PUT → commit);
reads use the proxy or a presigned S3 GET. **Direct presigned PUT is not implemented.**
Fetcher is a separate service: asset-store itself never fetches remote URLs.
Future IIIF server / image-mirror consumers sit outside this module and are not implemented here.

## Delivery map

| Component / concern | State | Delivered → remaining |
|---|---|---|
| **Registry + HTTP API** · B-009 | 🟢 Implemented core | Durable aliases, lifecycle, quotas, audit, migrations → complete admin surface below |
| **Storage-guard** · B-010 | 🟡 Partial target | Service authentication, scoped proxy tokens, presigned GET → tokens remain process-local; direct PUT and security hardening remain |
| **Storage backends** · B-005/008 | 🟡 Partial certification | Real Garage integration including multipart → OVH S3 validation and remaining backend spikes |
| **Fetcher** · B-020 | 🟢 Implemented MVP | Real HTTP, URL→alias rules, cache/tmp routing, refetch checksum conflict detection → production security review |
| **Bulk-loader** · B-011 | 🟢 Implemented CLI | Batch ingestion through guarded HTTP → 10k-asset acceptance/load evidence remains B-015 |
| **Worker-sim** · B-012 | 🔵 Simulation, implemented | Real reads/writes, checksum verification, manifest published last → actual workers and task engine are external |
| **Lifecycle worker** · B-014 | 🟢 Implemented | TTL, orphan cleanup, quota/capacity eviction, deletion retries, metrics → deploy/schedule explicitly; migration 0002 required |
| **Admin path** · B-013 | 🟢 Implemented; visual QA pending | Console, authenticated admin API, cursor listing, inspect/audit, TTL restoration, aliases, quotas, bounded bulk expiry → browser acceptance check |
| **Observability + CI** · B-003/004 | 🟡 Partial | Metrics, JSON logs, correlation IDs, sample lifecycle alerts; lint/types/tests CI → tracing, dashboards, alert wiring, image build/scan |
| **Deployment + recovery** · B-016/017/019 | 🟡 Partial | Local Compose and Dockerfile → Swarm, chaos tests, backup/restore drill, pilot/rollback |
| **Security + scale** · B-018/015 | ⚪ Planned validation | Scope tests exist → control-plane authorization review, secrets/HTTPS hardening and measured load/SLO certification |

**Test substitutes:** `InMemoryAssetRegistry` and `LocalObjectStore` replace Postgres
and S3 for infrastructure-free tests; `LocalObjectStore` is an in-memory dictionary.
The durable adapters are real implementations, not mocks. Upstream upload/task
services are planned integrations, not implemented merely because their service identities exist.

## What the four spaces hold

| `cache` | `tmp` | `users` | `results` |
|---|---|---|---|
| Remote mirrors | Temporary inputs | User uploads | Worker artifacts |
| Partition: mirror | Partition: temporary session | Partition: user | Partition: user (`anon` allowed); task in alias |
| No default TTL | Default 24 h; max 7 d | No default TTL | Default/max 365 d, configurable |
| Quota/pressure eviction | Quota/pressure eviction | No automatic capacity eviction | No automatic capacity eviction |

TTL applies when set; eviction exemptions protect against quota/pressure sweeps,
not expiry. Deadlines are currently shared by all aliases of an asset.

## Steering checkpoint

```mermaid
flowchart LR
    core["DELIVERED<br/>Ingest and retrieve<br/>Fetcher + worker-sim"]
    lifecycle["DELIVERED · B-014<br/>Lifecycle cleanup"]
    admin["LATEST · B-013<br/>Admin console + API"]
    security["NEXT · B-018<br/>Security review"]
    readiness["REMAINING<br/>Load + operations<br/>Recovery + pilot"]
    core --> lifecycle --> admin --> security --> readiness
    style core fill:#dcfce7,stroke:#15803d,color:#14532d
    style lifecycle fill:#dcfce7,stroke:#15803d,color:#14532d
    style admin fill:#dcfce7,stroke:#15803d,color:#14532d
    style security fill:#fef3c7,stroke:#b45309,color:#78350f
    style readiness fill:#f1f5f9,stroke:#64748b,color:#334155
```

**Evidence:** last code validation recorded **326 passing tests**, none skipped,
with Garage/Postgres enabled; lint, formatting and strict typing passed. Backend
tests are environment-gated in ordinary runs. Browser visual/interaction QA remains
pending (no browser available in the implementation session). This is not load or deployment certification.

**Architect attention:** upstream services still own user→prefix authorization
(R-012); process-local capabilities constrain replica/restart behavior; legacy reserve/commit control-plane
authorization still needs review. Admin routes now require an authenticated admin. Keep these boundaries explicit before wider exposure.
Per-alias deadlines and content deduplication remain deferred; several foundational
ADRs/spikes still await formal close-out despite working code.

---

**Navigate:** [Architecture & decisions](spec/03_ARCHITECTURE.md) ·
[Workplan](WORKPLAN.md) · [Implementation evidence & limitations](IMPLEMENTATION_NOTES.md) ·
[Backlog & risks](spec/05_BACKLOG_AND_OPEN_QUESTIONS.md) ·
[Lifecycle runbook](services/lifecycle-worker.md)

*This page is a status map, not a replacement for the specs. At each milestone,
refresh the checkpoint, diagram labels, table and validation evidence together.*
