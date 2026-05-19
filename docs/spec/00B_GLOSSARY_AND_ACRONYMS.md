# 00B - Glossary And Acronyms

Brief reference for readers new to this spec set. Domain concepts used throughout [`README.md`](README.md) and the numbered spec files.

---

## How this spec set is organized

| Prefix | Meaning | Where |
|--------|---------|--------|
| **FR-** | Functional requirement (must/should behaviour) | [`02_REQUIREMENTS.md`](02_REQUIREMENTS.md) |
| **NFR-** | Non-functional requirement (performance, security, …) | [`02_REQUIREMENTS.md`](02_REQUIREMENTS.md) |
| **ADR-** | Architecture decision record (choice + rationale) | [`03_ARCHITECTURE_AND_DECISIONS.md`](03_ARCHITECTURE_AND_DECISIONS.md) |
| **SCN-** | End-to-end scenario (who does what) | [`00A_SCENARIOS.md`](00A_SCENARIOS.md) |
| **S-** | Success criterion (measurable MVP goal) | [`01_SCOPE.md`](01_SCOPE.md) |
| **Q-** | Open question (not decided yet) | [`05_BACKLOG_AND_OPEN_QUESTIONS.md`](05_BACKLOG_AND_OPEN_QUESTIONS.md) |
| **R-** | Risk | [`05_BACKLOG_AND_OPEN_QUESTIONS.md`](05_BACKLOG_AND_OPEN_QUESTIONS.md) |
| **B-** | Backlog work item | [`05_BACKLOG_AND_OPEN_QUESTIONS.md`](05_BACKLOG_AND_OPEN_QUESTIONS.md) |

MoSCoW priority on requirements: **M** = must, **S** = should, **C** = could, **W** = won't (this iteration).

---

## Core domain terms

| Term | Plain language |
|------|----------------|
| **Asset** | One stored file (any format): image, PDF, JSON, etc. Identified by opaque **`asset_id`**. Bytes are write-once. |
| **Alias** | Stable name workers and APIs use instead of internal ids (e.g. `users/42/uploads/photo.jpg`). |
| **Qualified alias** | Full path: `{space}/{rest…}` — what appears in APIs and capabilities. |
| **Space** | Registry name for a **storage bucket**: `cache`, `tmp`, `users`, or `results`. |
| **Partition id** | Scope inside a bucket: user id, task id, mirror id, or tmp session id. |
| **Storage bucket** | MinIO/S3 top-level container (not a sub-folder). Four in MVP. |
| **Object key** | Physical path in MinIO, e.g. `42/assets/{asset_id}`. Workers never see it. |
| **Capability** | Short-lived permission to read or write a prefix of aliases (often a presigned URL). |
| **Presigned URL** | Time-limited URL that lets a client PUT/GET directly on MinIO without holding long-term credentials. |
| **Storage-guard** | Service that checks who is calling, issues capabilities, writes audit entries. |
| **Asset-registry** | Service that stores metadata, aliases, and lifecycle state (`pending` → `available` → …). |
| **Object-store** | MinIO (or any S3-compatible store) where bytes live. |
| **Fetcher-service** | Separate module that downloads remote URLs and stores results in `cache` or `tmp`. |
| **Lifecycle state** | `pending` (reserved, no bytes yet), `available`, `expired`, `deleted`. |
| **Audit log** | Append-only record of who did what (capabilities, alias changes, admin actions). |
| **Mutable alias** | Rare opt-in: alias may be rebound to another asset after an audited detach. |

---

## Acronyms and technical terms

| Acronym | Expansion | In this project |
|---------|-----------|-----------------|
| **API** | Application Programming Interface | HTTP+JSON services (`asset-registry`, `storage-guard`, fetcher). |
| **S3** | Amazon Simple Storage Service | De facto object-storage API; MinIO implements it. |
| **MinIO** | (product name) | Chosen S3-compatible object store for MVP ([`ADR-001`](03_ARCHITECTURE_AND_DECISIONS.md)). |
| **OSS** | Open-source software | Surveyed candidates in [`06_OSS_SURVEY.md`](06_OSS_SURVEY.md). |
| **STS** | Security Token Service | AWS pattern for temporary credentials; used with presigned URLs / roles. |
| **IAM** | Identity and Access Management | Policies on buckets and keys (MinIO supports S3-style IAM). |
| **PUT / GET** | HTTP methods | Upload and download objects in S3. |
| **MIME** | Multipurpose Internet Mail Extensions | Content type label (e.g. `image/jpeg`); often declared by caller. |
| **TTL** | Time to live | How long an asset or capability stays valid before expiry. |
| **GC** | Garbage collection | Background job removing expired/deleted payloads. |
| **UUID** | Universally unique identifier | Format for `asset_id` (prefer UUID v7 when available). |
| **IIIF** | International Image Interoperability Framework | Standard for image APIs/manifests; served by a future IIIF server, not asset-store. |
| **ARK** | Archival Resource Key | Persistent id scheme (`ark:/…`); possible future alias style ([`Q-011`](05_BACKLOG_AND_OPEN_QUESTIONS.md)). |
| **OCFL** | Oxford Common File Layout | Preservation-oriented on-disk layout; influences immutability thinking. |
| **DOI** | Digital Object Identifier | Another PID scheme; out of scope for MVP primary ids. |
| **SSRF** | Server-side request forgery | Risk when a server fetches user-supplied URLs; mitigated by isolating fetch in fetcher-service. |
| **mTLS** | Mutual TLS | Both client and server present certificates; future hardening ([`ADR-006`](03_ARCHITECTURE_AND_DECISIONS.md)). |
| **OIDC** | OpenID Connect | Identity layer on top of OAuth; future user auth integration. |
| **PII** | Personally identifiable information | Must not appear in alias names per spec policy. |
| **GDPR** | EU data protection regulation | Tracked as compliance question, not fully solved in MVP. |
| **SLI** | Service level indicator | Measurable signal (e.g. read error rate). |
| **SLO** | Service level objective | Target for an SLI (e.g. 99.9% availability). |
| **SEV-1 / SEV-2** | Severity levels | Alert urgency (1 = page on-call). |
| **OTLP** | OpenTelemetry Protocol | How traces are exported ([`04_OPERATIONS_AND_READINESS.md`](04_OPERATIONS_AND_READINESS.md)). |
| **PITR** | Point-in-time recovery | Postgres backup feature ([`R-004`](05_BACKLOG_AND_OPEN_QUESTIONS.md)). |
| **Compose / Swarm** | Docker Compose / Docker Swarm | Local dev vs target orchestration ([`NFR-011`](02_REQUIREMENTS.md)). |
| **FastAPI** | Python web framework | Used for custom services ([`ADR-006`](03_ARCHITECTURE_AND_DECISIONS.md)). |
| **Postgres** | PostgreSQL | Database for registry metadata and audit. |
| **RFC 7807** | Problem Details for HTTP APIs | Standard JSON error format in API requirements. |
| **MoSCoW** | Must, Should, Could, Won't | Priority tagging on requirements. |
| **STRIDE** | Spoofing, Tampering, … | Threat-modeling mnemonic ([`B-018`](05_BACKLOG_AND_OPEN_QUESTIONS.md)). |
| **AGPL** | GNU Affero GPL | MinIO license family; flagged in OSS survey. |

---

## Jargon we avoid or use carefully

| Phrase | Prefer instead |
|--------|----------------|
| “Sub-bucket” | **Prefix** inside a bucket (S3 has no nested buckets). |
| “Space `u-42`” (legacy) | **`users/42/…`** qualified alias ([`03_ARCHITECTURE_AND_DECISIONS.md`](03_ARCHITECTURE_AND_DECISIONS.md)). |
| “IIIF proxy” (legacy) | **Fetcher-service** ([`07_FETCHER_SERVICE.md`](07_FETCHER_SERVICE.md)). |
| “Object key” in user APIs | **Alias** — keys are internal only. |

---

## Related documents

- Platform diagram and bucket table: [`README.md`](README.md)
- Scenarios in plain steps: [`00A_SCENARIOS.md`](00A_SCENARIOS.md)
- Remote URL flow: [`07_FETCHER_SERVICE.md`](07_FETCHER_SERVICE.md)
