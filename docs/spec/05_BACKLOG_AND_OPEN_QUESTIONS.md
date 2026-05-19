# 05 - Backlog And Open Questions

## Open questions summary

| ID | Topic | Status |
|----|--------|--------|
| Q-004 | Quota: registry per `(bucket, partition_id)` vs MinIO | Partially directed — see ADR-007 |
| Q-020 | Default `tmp` TTL and GC | Open |
| Q-021 | Cache alias derivation (fetcher) | Open |
| Q-022 | Domain cache allowlist | Open |
| Q-023 | Fetcher MVP phasing | Open |
| Q-024 | Promote `tmp` → `users` (if ever) | Open |
| Q-025 | IIIF server integration phasing: formal service identity timing and `iiif_server_cache` read-path interaction | Open |
| Q-026 | `iiif-image-mirror` derivative generation: level 0 proxy-only vs level 1/2 with derivative generation (risk of upstream divergence) | Open |

Full table below.

## Open Questions

Each row is a single decision-blocking question. Until "Status" is `Resolved`, the corresponding `FR-*`/`NFR-*`/`ADR-*` is provisional. Owners are placeholders for the project lead to assign.

| ID | Question | Impact | Owner | Due Date | Status |
|---|---|---|---|---|---|
| Q-001 | What are the transactional semantics of a bulk batch? All-or-nothing per batch, per-N-item chunk, or best-effort with a manifest? | SCN-001 main flow + error behavior; bulk-loader UX | TBD | Phase 0 exit | Open |
| Q-002 | What is the maximum batch size before the bulk-loader must request a fresh capability? | Operational, capability TTL bounds | TBD | Phase 0 exit | Open |
| Q-003 | In which deployment topologies should `storage-guard` proxy the bytes instead of issuing presigned URLs? Default mode per environment? | ADR-003, NFR-007, NFR-008 | TBD | Phase 2 spike S-002 | Open |
| Q-004 | Quota enforcement model: per-`(space, partition_id)` hard limit, soft warn + alert, both? **Direction:** sums in **registry** on commit; MinIO bucket metrics for coarse ops only ([`ADR-007`](03_ARCHITECTURE_AND_DECISIONS.md)). | FR-042, FR-015, NFR-001 | TBD | Phase 3 | Open |
| Q-005 | MIME sniffing on commit (server-side) vs trust the caller? Trade-off between content-agnostic posture and operational safety. | FR-022, security guidance | TBD | Phase 2 | Open |
| Q-006 | Default grace period between `expired` and `deleted` (current draft: 7 days)? Per-space override? | FR-060 | TBD | Phase 2 | Open |
| Q-007 | Should the admin be allowed to override TTL/expire on system-managed buckets (e.g. `cache`)? | SCN-004, ADR-005 | TBD | Phase 3 | Open |
| Q-008 | Atomic-group write semantics: is the manifest-marker pattern enough or do we need a real transactional "commit bundle" endpoint? | FR-001..003, SCN-005 | TBD | Phase 3 | Open |
| Q-009 | Is MinIO's current license and commercial trajectory acceptable for our use? If not, do we pivot to Garage now or retain optionality? | ADR-001 | TBD | Phase 0 spike S-001/S-004 | Open |
| Q-010 | Audit storage: shared Postgres DB with the registry, or a dedicated append-only journal? Retention/export hook? | FR-050..053, NFR-009 | TBD | Phase 2 | Open |
| Q-011 | Identifier scheme for public/published aliases: do we adopt ARK as a special alias namespace and obtain a NAAN? When? | ADR-004; future IIIF module | TBD | Phase 4 | Open |
| Q-012 | Encryption at rest: required for any space (e.g. `u-*`) in MVP or fully deferred? | NFR-007, R-001 | TBD | Phase 3 | Open |
| Q-013 | What set of MIME types triggers a virus/malware scan call-out (out of scope to perform; in scope to document the contract)? | 01_SCOPE.md out-of-scope clause | TBD | Phase 0 exit | Open |
| Q-014 | Service-to-service auth in MVP: shared secret vs mTLS? When do we move to OIDC (Keycloak)? | ADR-006, NFR-007 | TBD | Phase 1 | Open |
| Q-015 | Resumable / progressive upload protocol: rely on object-store native multipart, or expose a thin tus.io-compatible layer? | FR-021 | TBD | Phase 2 | Open |
| Q-016 | Are there strictly internal aliases that callers must not see in API responses (e.g. raw object keys)? Default answer is yes; needs explicit confirmation. | Privacy, API contract | TBD | Phase 0 exit | Open |
| Q-017 | Should the storage-guard provide a "renew capability" endpoint, or does the caller always request a fresh one? | UX of long-running workers | TBD | Phase 2 | Open |
| Q-018 | Exact semantics of `mutable: true` aliases (FR-008): what can change (asset binding only? annotations are always editable regardless), grace period for name reuse on detach of an immutable alias, and which service identities are allowed to set the flag at create time | FR-001, FR-003, FR-008, ADR-005 | TBD | Phase 2 | Open |
| Q-019 | When do we scope the future `manifest-service` that composes IIIF manifests from editable descriptive metadata + immutable structural references? Does descriptive-metadata storage live in the manifest-service's own DB or in another shared module? | downstream module roadmap; cross-references 01_SCOPE.md | TBD | Phase 4 | Open |
| Q-020 | Default TTL and GC for `tmp` bucket assets (e.g. 24 h vs 7 d)? Per-partition override? | SCN-006, SCN-007, ADR-007 | TBD | Phase 2 | Open |
| Q-021 | Cache alias derivation for fetcher: single canonical alias per normalized URL vs multiple aliases per mirror ([`_archive/00A_USE_CASES_AND_SCENARIOS.md`](_archive/00A_USE_CASES_AND_SCENARIOS.md) SCN-003)? | SCN-007, [`07_FETCHER_SERVICE.md`](07_FETCHER_SERVICE.md) | TBD | Phase 2 | Open |
| Q-022 | Domain cache allowlist: config file, DB, admin UI; who maintains entries? | SCN-007, fetcher | TBD | Phase 2 | Open |
| Q-023 | Fetcher MVP: stub in asset-store repo vs separate service in Phase 2 vs 2b? | [`07_FETCHER_SERVICE.md`](07_FETCHER_SERVICE.md), WORKPLAN | TBD | Phase 2 | Open |
| Q-024 | Should upload-api ever promote `tmp` staging objects to `users` (copy + new alias) or always write directly to `users`? | SCN-003, SCN-006 | TBD | Phase 2 | Open |
| Q-025 | IIIF server integration phasing: when does `iiif-server` get a formal service identity provisioned, and how does `iiif_server_cache` interact with the asset-store read path (separate bucket, no asset-store involvement)? | SCN-008, [`01_SCOPE.md`](01_SCOPE.md) | TBD | Phase 4 | Open |
| Q-026 | `iiif-image-mirror` derivative generation: should the mirror generate image derivatives to achieve IIIF Image API level 1/2 compliance, or proxy level-0 URLs only? Generating derivatives risks subtle divergence from upstream rendering; if pursued, where are tiles stored (dedicated bucket outside asset-store)? | [`07_FETCHER_SERVICE.md`](07_FETCHER_SERVICE.md), B-021 | TBD | Phase 3 | Open |

## Risks

| ID | Risk | Probability (L/M/H) | Impact (L/M/H) | Mitigation | Owner |
|---|---|---|---|---|---|
| R-001 | No encryption-at-rest in MVP could become a compliance blocker before pilot | M | M | Track Q-012; design space layout to allow per-space SSE-S3 enablement without payload rewrites | TBD |
| R-002 | MinIO license terms or commercial trajectory could become unacceptable mid-prototype | M | M | Garage validated as drop-in alternative (Spike S-004); object-store usage is pure S3, no MinIO-specific extensions in code paths | TBD |
| R-003 | Capability scope bugs grant cross-bucket or cross-partition access | L | H | S-4 suite; FR-015 bucket allowlist tests; fuzz capability strings; default-deny in `storage-guard` | TBD |
| R-004 | Postgres becomes a single point of failure as load grows | L | H | Schema kept conservative; backups and PITR set up in Phase 4; read replica plan documented; horizontal scaling option (Citus or partitioning) noted for post-pilot | TBD |
| R-005 | Garbage collection misfire deletes payloads still referenced | L | H | Two-step lifecycle (`expired` then `deleted` after grace); sweeper is dry-run by default; metrics + alert on unexpected GC volume; restore-from-backup plan rehearsed | TBD |
| R-006 | Audit log grows unbounded and degrades query performance | M | M | Partition `audit_events` table by month; retention policy 30 days hot + export to cold storage; index design reviewed | TBD |
| R-007 | Operating Docker Swarm in production is a moving target (long-term plan is k8s) | M | M | Keep stack-file declarative; avoid Swarm-specific features that have no k8s equivalent; document the migration path | TBD |
| R-008 | Storage-guard becomes a hot bottleneck under read load | M | M | Stateless service horizontally scaled; presigned URL default avoids the proxy path; capability cache for repeat callers | TBD |
| R-009 | Hidden coupling on object-store internal layout (e.g. by admins) prevents object-store swap later | L | M | All callers go through the registry; no UI exposes raw object keys; ADR-001 swap procedure documented | TBD |
| R-010 | Spec under-models concurrent writes to the same alias prefix from multiple uploaders | M | M | Alias namespace uniqueness enforced at registry; reservation step (`pending`) holds the alias; idempotency keys required on writes | TBD |

## Implementation Backlog (Prototype)

Coarse-grained backlog. Refined into engineering tickets at Phase 1 kick-off. Ordering reflects dependencies; priority follows MoSCoW from [`02_REQUIREMENTS.md`](02_REQUIREMENTS.md).

| ID | Work Item | Type | Priority | Dependency | Done Definition |
|---|---|---|---|---|---|
| B-001 | Spec close-out: assign owners and dates to Q-001..017; mark Q-001/Q-002/Q-009/Q-013/Q-016 Resolved before Phase 1 | Doc | P0 | - | All Q-* rows above have an owner and a due date; the five listed are Resolved |
| B-002 | Repo scaffold: `services/asset-registry/`, `services/storage-guard/`, `tools/bulk-loader/`, `tools/worker-sim/`, `tools/admin-ui/`, `deploy/compose/`, `deploy/swarm/` | Infra | P0 | B-001 | `docker compose up` in `deploy/compose/` brings up MinIO + Postgres + asset-registry + storage-guard placeholders responding on `/healthz` |
| B-003 | CI baseline: lint (ruff), format (ruff/black), type-check (mypy), unit tests (pytest), container build, image scan (trivy) | Infra | P0 | B-002 | Green CI on the base branch; pre-commit hooks installed |
| B-004 | Observability skeleton: structured logs, OpenTelemetry instrumentation, Prometheus `/metrics`, dev Grafana dashboard | Infra | P0 | B-002 | Each service exposes `/metrics`; a request flow traced end-to-end in the local stack |
| B-005 | Spike S-001 (MinIO baseline) | Spike | P0 | B-002 | Notes appended to 06_OSS_SURVEY.md; Q-009 resolved |
| B-006 | Spike S-002 (asset-registry MVP) | Spike | P0 | B-002, B-005 | SCN-001 runs end-to-end against 1k assets; notes appended to 06_OSS_SURVEY.md |
| B-007 | Spike S-003 (InvenioRDM compare) | Spike | P0 | B-002 | Adopt-vs-compose decision confirmed; ADR-002 status updated |
| B-008 | Spike S-004 (Garage fallback) | Spike | P0 | B-005 | ADR-001 fallback validated; notes appended |
| B-009 | Asset-registry MVP: data model + migrations + FR-001..007 endpoints | Feature | P0 | B-006, B-007 | Integration tests covering SCN-001..005 happy paths green |
| B-010 | Storage-guard MVP: service identity auth + FR-010..015 endpoints + audit log + bucket allowlist | Feature | P0 | B-009 | Capability scoping (S-4) and cross-bucket denial (FR-015) green |
| B-020 | Fetcher-service MVP: ensure_url + cache/tmp policy ([`07_FETCHER_SERVICE.md`](07_FETCHER_SERVICE.md)) | Feature | P0 | B-010 | SCN-007 green |
| B-011 | Bulk-loader CLI | Feature | P0 | B-009, B-010 | SCN-001 acceptance test green at 10k assets |
| B-012 | Worker-sim CLI | Feature | P0 | B-009, B-010 | SCN-002 and SCN-005 acceptance tests green |
| B-013 | Admin-UI (minimum: list, inspect, expire/delete, audit view) | Feature | P1 | B-009, B-010 | SCN-004 acceptance test green |
| B-014 | Lifecycle worker: sweep `pending` orphans; transition `expired -> deleted` after grace | Feature | P1 | B-009 | Test forces expiry and verifies state transitions |
| B-015 | Load tests for S-2 / S-3 (locust or k6) | Test | P1 | B-011, B-012 | Numbers attached to NFR-002/003/004 acceptance |
| B-016 | Chaos suite: kill-one of each service and one object-store node | Test | P2 | B-015 | Service replicas survive; failure modes match `03_ARCHITECTURE_AND_DECISIONS.md` |
| B-017 | Backup hook to a second S3 target | Feature | P2 | B-009 | Documented and tested; FR-061 acceptance |
| B-018 | Security review pass (STRIDE on storage-guard) + go-live checklist sweep | Doc | P1 | B-010, B-013 | Findings logged; checklist boxes ticked or risks accepted |
| B-019 | Pilot plan + rollback rehearsal | Doc | P2 | B-015, B-018 | Plan reviewed; rehearsal report attached |
| B-021 | Decide whether `iiif-image-mirror` is needed and scope it: end-user auth model, IIIF Image API compliance level, derivative generation decision ([`Q-026`](05_BACKLOG_AND_OPEN_QUESTIONS.md)) | Doc | P3 | B-010 | Decision recorded; if yes, `iiif-image-mirror` service identity provisioned in storage-guard |

## Exit Criteria To Start Build Phase

- [ ] All P0 requirements have acceptance criteria (see [`02_REQUIREMENTS.md`](02_REQUIREMENTS.md) section "Acceptance Criteria").
- [ ] Storage and metadata decisions accepted (ADR-001 through ADR-006), at least provisionally; spikes scheduled.
- [ ] Security and observability baselines specified (this file plus [`04_OPERATIONS_AND_READINESS.md`](04_OPERATIONS_AND_READINESS.md)).
- [ ] Initial backlog (B-001..B-019) reviewed and sequenced.
- [ ] All Q-* rows have an owner and a due date; the five blocking spec questions (Q-001, Q-002, Q-009, Q-013, Q-016) are Resolved.
