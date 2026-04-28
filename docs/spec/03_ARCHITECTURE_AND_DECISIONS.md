# 03 - Architecture And Decisions

## Proposed Architecture

Describe chosen architecture in 1-2 paragraphs.

## Component Responsibilities

| Component | Responsibility | Inputs | Outputs |
|---|---|---|---|
| Ingestion API |  |  |  |
| Orchestrator |  |  |  |
| Storage Adapter |  |  |  |
| Metadata Store |  |  |  |
| Worker Access API |  |  |  |

## Data Model Draft

### Asset Metadata (minimum)

- `asset_id`:
- `tenant_id`:
- `source_type`:
- `storage_key`:
- `checksum`:
- `size_bytes`:
- `mime_type`:
- `state`:
- `created_at`:
- `expires_at`:

## State Machine

Define lifecycle states and transitions.

- States:
- Allowed transitions:
- Terminal states:
- Retry rules:

## ADR Log

Use one row per architecture decision.

| ADR ID | Decision | Status (Proposed/Accepted/Deprecated) | Rationale | Alternatives Rejected |
|---|---|---|---|---|
| ADR-001 |  |  |  |  |
| ADR-002 |  |  |  |  |

## Failure Modes

List major failure scenarios and behavior:

- Upload interrupted:
- Remote URL timeout:
- Storage provider temporary error:
- Metadata write success but object write failure:
- Duplicate submissions:

## Scalability Strategy

- Partitioning approach:
- Bottleneck assumptions:
- Horizontal scale points:
- Cost controls:
