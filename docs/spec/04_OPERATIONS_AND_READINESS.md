# 04 - Operations And Readiness

## Deployment Model

- Runtime target (k8s/VM/serverless):
- Environments (dev/staging/prod):
- Release strategy (rolling/canary/blue-green):
- Rollback strategy:

## Configuration And Secrets

- Config source:
- Secret manager:
- Rotation policy:
- Environment separation rules:

## Observability

### Metrics

- Ingestion request rate
- Success/error rate by source type
- Object write/read latency
- Queue lag (if async import)
- Worker fetch latency

### Logging

- Structured JSON logs:
- Correlation IDs:
- Redaction policy:

### Tracing

- Trace boundaries:
- Required spans:

### Alerts

List initial alerts with threshold and owner:

| Alert | Trigger | Severity | Owner |
|---|---|---|---|
|  |  |  |  |

## SLO / SLI Draft

| SLI | Definition | Target | Measurement Window |
|---|---|---|---|
| Availability |  |  |  |
| Latency |  |  |  |
| Error rate |  |  |  |

## Testing Strategy

- Unit test scope:
- Integration test scope:
- End-to-end test scope:
- Load/performance test scope:
- Chaos/failure injection scope:

## Go-Live Checklist

- [ ] Security review completed
- [ ] Threat model completed
- [ ] Runbooks written
- [ ] Dashboards and alerts live
- [ ] Backup/restore tested
- [ ] Incident ownership defined
