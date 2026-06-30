# Global Workplan

## Objective

Deliver a deployable, testable, monitored prototype of the **`asset-store`** module along the "compose" architecture recommended in [`spec/A_OSS_SURVEY.md`](spec/A_OSS_SURVEY.md), with a clear path from prototype to production.

The plan below is aligned with `ADR-001 = OVH S3 (hosted) + Garage (self-hosted), MinIO disqualified`, `ADR-002 = compose`, `ADR-003 = hybrid capability mode` (all provisional pending Phase 0 spikes). If a spike reverses one of these ADRs, the Phase 1+ tasks adapt but the phase boundaries do not.

Each phase has explicit exit criteria mapped to `FR-*`/`NFR-*`/`S-*` IDs from [`spec/01_SCOPE.md`](spec/01_SCOPE.md) and [`spec/02_REQUIREMENTS.md`](spec/02_REQUIREMENTS.md). Backlog IDs (`B-*`) come from [`spec/05_BACKLOG_AND_OPEN_QUESTIONS.md`](spec/05_BACKLOG_AND_OPEN_QUESTIONS.md).

## Phase 0 - Spec & survey close-out

**Goal:** lock unknowns blocking the build; validate `ADR-001`/`ADR-002`/`ADR-003` via time-boxed spikes.

**Work items:**

- B-001 - assign owners/dates to Q-001..017; resolve Q-001/Q-002/Q-009/Q-013/Q-016.
- B-005 - Spike S-001: object-store baseline on Garage / OVH S3 (PUT/GET/multipart/presigned URLs/lifecycle).
- B-006 - Spike S-002: minimal `asset-registry` against the object store (Garage); SCN-001 dry-run with 1k assets.
- B-007 - Spike S-003: InvenioRDM compare; confirm compose path is the right choice for our requirements.
- B-008 - Spike S-004: Garage certified as the self-hosted backend.

**Exit criteria:**

- All `Q-*` rows have owner + due date.
- Q-001, Q-002, Q-009, Q-013, Q-016 marked Resolved.
- ADR-001, ADR-002, ADR-003 status changed from Proposed to Accepted (or revised) in `spec/03_ARCHITECTURE.md`.
- Spike notes appended to `spec/A_OSS_SURVEY.md` section 7.

## Phase 1 - Foundations

**Goal:** create a minimal but production-shaped service skeleton matching the chosen architecture.

**Work items:**

- B-002 - Repository scaffold:
  - `services/asset-store/` (single Python/FastAPI deployable; internal `registry`, `capabilities`, `storage` modules; async, alembic migrations) per ADR-002.
  - `tools/bulk-loader/` (Python click CLI).
  - `tools/worker-sim/` (Python click CLI).
  - `tools/admin-ui/` (static SPA or HTMX; final pick at code time).
  - `deploy/compose/` (dev stack: object store (Garage) + Postgres + asset-store + admin-ui + observability sidecars).
  - `deploy/swarm/` (target Swarm stack file; mirrors compose with replica counts and Swarm secrets).
- B-003 - CI baseline (ruff, mypy, pytest, build, trivy image scan).
- B-004 - Observability skeleton (structured JSON logs, OpenTelemetry, Prometheus `/metrics`, sample Grafana dashboard).

**Exit criteria:**

- Green CI on the base branch.
- `docker compose up` in `deploy/compose/` brings up the local stack in under 2 minutes (target FR-072 / NFR-011); all services pass `/healthz` and `/readyz`.
- A no-op request can be traced end-to-end (logs, metric, trace span) in the local stack.

## Phase 2 - Core ingestion + retrieval (MVP write/read happy path)

**Goal:** deliver the end-to-end happy path for SCN-001, SCN-002, SCN-003 against the local stack.

**Work items:**

- B-009 - `asset-registry` MVP: data model + Alembic migrations + endpoints implementing FR-001..007.
- B-010 - `storage-guard` MVP: service-identity auth + FR-010..014 + audit log + presigned URL minting.
- B-011 - `bulk-loader` CLI implementing SCN-001 against 10k assets.
- B-012 - `worker-sim` CLI implementing SCN-002 (read path) and SCN-005 (write path).
- B-014 - Lifecycle worker: sweep `pending` orphans; `expired -> deleted` after grace.

**Exit criteria:**

- SCN-001, SCN-002, SCN-003, SCN-005 acceptance tests green in CI on every PR.
- Capability scoping test suite (S-4) green - no cross-prefix access possible.
- Audit log entries present for all expected events (FR-050..052 acceptance).
- Read path returns p95 latency under 200 ms in-cluster on the local stack with one worker (NFR-002 sample).

## Phase 3 - Admin path, reliability, security

**Goal:** make the prototype operationally credible and safe.

**Work items:**

- B-013 - `admin-ui` covering SCN-004 (list, inspect, expire/delete, audit view).
- B-018 - Security review pass: STRIDE on `storage-guard`; secrets handling audit; HTTPS posture; capability TTL / scoping fuzzing.
- Lifecycle hardening: rate limits on capability issuance per service identity; idempotency-key replay protection across services.
- Backup hook for Postgres + a second S3 target (B-017) - design and basic implementation.
- Resolve Q-003, Q-005, Q-006, Q-010, Q-014, Q-017 (the Phase 2/3 batch of open questions).

**Exit criteria:**

- SCN-004 acceptance test green.
- All P0 alerts in `spec/04_OPERATIONS.md` configured against the local stack and firing on synthetic faults.
- Security-review findings either fixed or accepted with a `R-*` risk row.
- Backup of Postgres + object-store snapshot exercised; restore drill documented.

## Phase 4 - Load test, capacity, SLO baseline

**Goal:** measure against the non-functional targets and prove the SLO is achievable.

**Work items:**

- B-015 - Locust/k6 load tests for S-2 (30 concurrent readers) and S-3 (10k assets ingest).
- B-016 - Chaos suite: kill-one of each service; kill one object-store node.
- Capacity baseline run: ingest 100k assets to ~1 TB; measure read latencies, registry query times, object-store disk usage.

**Exit criteria:**

- SLO dashboard exists; error-budget burn-rate alerts configured.
- NFR-001 (capacity), NFR-002 (read latency p95), NFR-003 (mint latency p95), NFR-004 (concurrency), NFR-005 (durability canary) measured and within targets.
- Chaos suite passes: zero failed user-visible requests after retry.

## Phase 5 - Pilot readiness

**Goal:** validate the prototype in a controlled real workflow.

**Work items:**

- B-019 - Pilot plan + rollback rehearsal; success metrics defined.
- Documentation pass: runbooks `RUNBOOK-001..006` finalised in `docs/runbooks/`.
- Cost and performance report based on Phase 4 numbers.
- Go-live checklist sweep (from `spec/04_OPERATIONS.md`).

**Exit criteria:**

- Pilot sign-off checklist complete.
- Go/No-Go decision documented; remaining risks accepted in writing.

## Cadence And Governance

- Weekly architecture review: ADR changes, open questions, risk register.
- Twice-weekly delivery sync: backlog progress, blockers, risks.
- Single source of truth: `docs/spec/` and the ADR table.

## Immediate Next 7 Tasks

1. Assign owners and dates to all `Q-*` rows in [`spec/05_BACKLOG_AND_OPEN_QUESTIONS.md`](spec/05_BACKLOG_AND_OPEN_QUESTIONS.md).
2. Schedule Spikes S-001 and S-002 (B-005, B-006); allocate 4-5 working days total.
3. Schedule Spike S-003 (B-007) immediately after S-002 to confirm the compose-vs-adopt choice.
4. Schedule Spike S-004 (B-008) opportunistically; non-blocking.
5. Create the repo scaffold tickets per B-002 (six directories listed in Phase 1).
6. Define CI pipeline as B-003 (ruff, mypy, pytest, build, trivy).
7. Stand up the observability skeleton (B-004) so every following PR can be reasoned about.

## Phase Dependency Diagram

```mermaid
flowchart LR
    P0[Phase 0<br/>Spec & spikes]
    P1[Phase 1<br/>Foundations]
    P2[Phase 2<br/>Core MVP]
    P3[Phase 3<br/>Admin + security]
    P4[Phase 4<br/>Load + SLO]
    P5[Phase 5<br/>Pilot]

    P0 --> P1
    P1 --> P2
    P2 --> P3
    P3 --> P4
    P4 --> P5
```
