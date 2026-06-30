# 04 - Operations And Readiness

## Observability at a glance

| What to watch | Source | Labels |
|---------------|--------|--------|
| Per-user / per-task storage | Registry compactor | `space`, `partition_id` |
| Per-bucket disk (ops) | object-store exporter | `bucket` |
| Cache effectiveness | fetcher-service | `fetch_cache_hit`, `fetch_remote_errors` |
| API health | asset-registry, storage-guard | `endpoint`, `result_class` |

**Quota enforcement** uses registry sums per `(space, partition_id)`, not the object store alone ([`Q-004`](05_BACKLOG_AND_OPEN_QUESTIONS.md)).

---

## Deployment Model

- **Runtime target** - Docker Swarm in the target environment (NFR-011). Docker Compose for single-machine development.
- **Environments** - `dev` (developer workstation; single-node Compose), `staging` (Swarm cluster with two nodes, scaled-down replicas), `prod` (Swarm cluster; replica count sized to load).
- **Release strategy** - rolling update per service; `asset-registry` and `storage-guard` are stateless and can be rolled one task at a time; `object-store` (Garage) uses its own rolling strategy with quorum preserved; Postgres is updated during maintenance windows with read-only mode if required.
- **Rollback strategy** - re-deploy previous image tag (Swarm `service update --rollback`); schema migrations are forward-compatible by policy so an older service binary can run against a newer schema for at least one release cycle.

## Configuration And Secrets

- **Config source** - environment variables for ports, URLs, feature flags; YAML configuration file for the larger settings (capability TTL bounds, default grace periods).
- **Secret manager** - Docker Swarm secrets for MVP (service credentials, Postgres passwords, object-store credentials); migration to HashiCorp Vault or similar tracked as a forward step.
- **Rotation policy** - service credentials rotated by re-deploying with the new secret; rolling restart absorbs the transition; rotation event recorded in the audit log.
- **Environment separation rules** - one Swarm secret per `(environment, service)` pair; no production secret visible from staging containers.

## Observability

### Metrics

Per-service (`asset-registry`, `storage-guard`, and later `fetcher`) Prometheus-style metrics. Labels: `service`, `endpoint`, `space` (bucket), `partition_id` where applicable, `result_class` (`2xx`/`4xx`/`5xx`).

- **`asset_store_requests_total`** (counter) - request count by endpoint and result class.
- **`asset_store_request_duration_seconds`** (histogram) - per-endpoint latency; standard quantiles via histogram_quantile.
- **`asset_store_capability_issued_total`** (counter) - by `mode` (`presigned`/`token`), `op` (`read`/`write`), `outcome` (`granted`/`denied`).
- **`asset_store_capability_issue_duration_seconds`** (histogram) - for NFR-003.
- **`asset_store_alias_state_transitions_total`** (counter) - by `from`, `to`.
- **`asset_store_storage_bytes`** (gauge) - per `space` and per `(space, partition_id)`; refreshed by a periodic compactor job (authoritative for quotas).
- **`asset_store_storage_assets`** (gauge) - per `space`, per `partition_id`, per `state`.
- **`objectstore_bucket_usage_bytes`** (gauge) - per bucket from the object-store exporter (coarse cost/ops view).
- **`fetch_cache_hit_total`** / **`fetch_remote_errors_total`** / **`fetch_bytes_ingested_total`** (counter) - fetcher-service; labels `bucket` (`cache`|`tmp`), `mirror_id` optional.
- **`asset_store_audit_events_total`** (counter) - by `action`.
- **`asset_store_checksum_mismatch_total`** (counter) - durability canary.

Plus standard object-store and Postgres exporter metrics (request rate, latency, error rate, disk usage, connection pool).

### Logging

- **Format** - structured JSON, one line per event; fields include `ts`, `service`, `level`, `correlation_id`, `caller_service_id`, `space`, `alias` (when relevant), `event`, `message`.
- **Correlation IDs** - one `correlation_id` per inbound request; propagated downstream via the `X-Correlation-Id` header.
- **Redaction policy** - no secrets in logs; capability tokens replaced with their `capability_id` only; alias names allowed (they are not secrets by policy - operator guidance forbids putting PII in aliases).

### Tracing

- **Trace boundaries** - inbound HTTP request boundary; outbound object-store and Postgres calls.
- **Required spans** - `capability.issue`, `asset.commit`, `asset.resolve`, `audit.append`, `object_store.put`, `object_store.get`, `db.query`.
- **Exporter** - OTLP via a sidecar collector; backend left as a deployment choice (Jaeger or Tempo recommended).

### Alerts

Alert thresholds are starting points; refined after Phase 4 load testing. Severity SEV-1 pages on-call; SEV-2 raises a ticket.

| Alert | Trigger | Severity | Owner |
|---|---|---|---|
| ReadErrorRateHigh | `rate(asset_store_requests_total{endpoint="resolve",result_class="5xx"}[5m]) / rate(asset_store_requests_total{endpoint="resolve"}[5m])` > 1% for 10 min | SEV-1 | on-call |
| ReadLatencyHigh | `histogram_quantile(0.95, asset_store_request_duration_seconds{endpoint="resolve"})` > 0.5 s for 15 min | SEV-2 | on-call |
| CapabilityMintLatencyHigh | `histogram_quantile(0.95, asset_store_capability_issue_duration_seconds)` > 0.1 s for 15 min | SEV-2 | on-call |
| ChecksumMismatchDetected | `increase(asset_store_checksum_mismatch_total[5m])` > 0 | SEV-1 | on-call |
| ObjectStoreNodeDown | `up{job="objectstore"} == 0` for 5 min | SEV-1 | on-call |
| ObjectStoreDiskAlmostFull | object-store node free space < 10% for 30 min | SEV-2 | on-call |
| PostgresConnectionsExhausted | `pg_stat_activity_count` >= 90% of `max_connections` for 10 min | SEV-2 | on-call |
| AuditWriteFailures | `increase(asset_store_audit_events_total{outcome="error"}[5m])` > 0 | SEV-1 | on-call |
| CapabilityIssueDeniedSurge | `rate(asset_store_capability_issued_total{outcome="denied"}[5m])` exceeds rolling baseline by 5x | SEV-3 | on-call |

## SLO / SLI Draft

The SLOs target the **read path** (the dominant workload). Write-path SLOs to be added after Phase 3.

| SLI | Definition | Target | Measurement Window |
|---|---|---|---|
| Availability (read) | (1 - 5xx rate on `resolve` and signed-URL GET) measured in 1-minute buckets | 99.9% | rolling 30 days |
| Latency (read p95) | p95 of `asset_store_request_duration_seconds{endpoint="resolve"}` | <= 200 ms (in-cluster) | rolling 7 days |
| Capability mint latency p95 | p95 of `asset_store_capability_issue_duration_seconds` | <= 50 ms | rolling 7 days |
| Durability canary | `increase(asset_store_checksum_mismatch_total)` | == 0 | rolling 30 days |

Error budget for the read availability SLO: 0.1% of 30 days = ~43 minutes per 30-day window. Burn-rate alerts to be configured in Phase 3.

## Testing Strategy

- **Unit tests** - per service; pytest; coverage targets `>= 80%` for new modules; mocks for the object-store layer when fast tests are needed.
- **Integration tests** - run the full stack via Docker Compose; exercise SCN-001..007 end-to-end; CI runs them on every PR.
- **End-to-end tests** - same scenarios run against the staging Swarm cluster nightly; failure raises a SEV-3 alert.
- **Load tests** - Locust- or k6-driven; reproduce S-2 and S-3 conditions; runs on demand and before each release candidate.
- **Chaos / failure injection** - kill one `asset-registry` task, one `storage-guard` task, one object-store node; verify that retries succeed and metrics report the impact within SLO error budget.
- **Security tests** - SAST in CI (e.g. `bandit`, `semgrep`); image scanning (`trivy` or `grype`); dependency vulnerability scan; capability-scoping test suite per S-4.

## Go-Live Checklist

- [ ] Security review completed for the prototype scope (capability lifecycle, secrets, TLS, audit).
- [ ] Threat model documented (STRIDE pass on `storage-guard`).
- [ ] Runbooks written for: capability issuance failures, object-store node loss, Postgres failover, audit log overflow, garbage collection misfire.
- [ ] Dashboards and alerts live in the chosen observability backend; on-call ownership defined.
- [ ] Backup/restore tested for Postgres and the object store.
- [ ] Incident ownership defined (paging schedule, escalation contacts).
- [ ] Capacity baseline measured under S-2 / S-3 loads; SLO targets validated against measured headroom.
- [ ] License audit completed (in particular: object-store and any vendored dependency).
- [ ] Disaster recovery rehearsal completed at least once.

## Runbook Stubs

These will live in `docs/runbooks/` once the implementation lands; placeholders here so we do not forget them at code time.

- `RUNBOOK-001` Object-store node loss - detect, drain, replace, rebalance.
- `RUNBOOK-002` Postgres failover - if/when a replica is added.
- `RUNBOOK-003` Capability issuance saturation - tune workers, identify caller.
- `RUNBOOK-004` Audit log overflow - rotate, archive, alert tuning.
- `RUNBOOK-005` Garbage collection stuck - manual trigger and inspection.
- `RUNBOOK-006` License or CVE response - swap object-store image, rotate keys.
