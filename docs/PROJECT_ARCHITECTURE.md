# Project Architecture

## Scope Of This Module

This module is responsible for durable image ingestion and retrieval for async workers.  
It does **not** run image processing itself.

## High-Level Components

1. **Ingestion API**
   - Receives image submissions from:
     - direct upload
     - private-space import
     - remote URL reference
   - Validates metadata and request shape.
   - Returns a stable asset identifier quickly.

2. **Ingestion Orchestrator**
   - Normalizes input mode into one internal ingestion flow.
   - Applies anti-abuse controls (size/type/rate limits).
   - Emits lifecycle events.

3. **Object Storage Adapter**
   - Writes binary payloads to backing storage.
   - Reads payloads for workers.
   - Handles multipart upload and retries.

4. **Metadata Store**
   - Tracks asset lifecycle state, ownership, checksums, and retention policy.
   - Supports idempotency and traceability.

5. **Worker Access API**
   - Provides secure read URLs or signed fetch tokens.
   - Enforces worker/service authorization.

6. **Observability Layer**
   - Metrics, logs, traces, dashboards, alerts.
   - Audit events for compliance and incident investigation.

## Suggested Repository Layout

```text
prototype_cache/
  docs/
    PROJECT_ARCHITECTURE.md
    WORKPLAN.md
    spec/
      README.md
      01_SCOPE.md
      02_REQUIREMENTS.md
      03_ARCHITECTURE_AND_DECISIONS.md
      04_OPERATIONS_AND_READINESS.md
      05_BACKLOG_AND_OPEN_QUESTIONS.md
  AGENTS.md
  .cursor/
    rules/
      project-context.mdc
      docs-spec-quality.mdc
```

## Core Data Flow

1. Client submits image (file/private import/URL).
2. Ingestion API validates, normalizes, and assigns `asset_id`.
3. Payload is stored in object storage (or imported asynchronously).
4. Metadata record is created/updated with lifecycle state.
5. Worker requests processing input through Worker Access API.
6. Worker reads asset securely and emits processing result events.

## Non-Functional Targets (Baseline)

- **Availability**: target SLO >= 99.9% for read path.
- **Durability**: no silent data loss; checksums on write/read.
- **Latency**: ingestion acknowledgement in low seconds.
- **Security**: encrypted at rest and in transit, least privilege IAM.
- **Scalability**: horizontal API scale, storage growth without redesign.
- **Operability**: dashboards + alerting + runbooks available before rollout.
