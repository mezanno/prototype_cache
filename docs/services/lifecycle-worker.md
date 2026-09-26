# Lifecycle worker (B-014)

FR-060/063/064/067/069 and ADR-020: a trusted maintenance process performs one
sweep by default, or repeats on an operator-selected interval. It uses the same
registry/storage adapters as asset-store. **Dry-run is the default**; `--apply`
is required to change lifecycle state or remove bytes. No public deletion API or
new service capability is introduced.

## Retention and safe cleanup

- Reservations accept optional positive `ttl_seconds`. The prototype stores one
  deadline per asset, shared by its aliases; independent alias TTLs remain deferred.
- `tmp` defaults to 24 hours and accepts hints up to 7 days. `results` defaults to
  the operator maximum (365 days); hints may shorten but not exceed that maximum.
  `cache` and `users` have no default deadline. Deadlines start at reservation.
- Reads of expired or deadline-past assets return 410; deleted assets return 404.
  TTL checks deny new reads before the next sweep. Existing signed URLs are not
  revocable; newly minted URLs are capped by the remaining asset lifetime.
- Due available assets become expired. Grace starts at the actual expired
  transition, not at an editable metadata timestamp: 24 hours for tmp, 7 days for
  other buckets. `exempt` does not prevent TTL expiry or orphan cleanup.
- Pending reservations older than 24 hours are orphan candidates. Expired assets
  past grace and administratively deleted assets are payload cleanup candidates.
  Metadata/aliases are retained for audit; deleted names do not become reusable.
- Each applied action locks and rechecks the asset snapshot. Proxy uploads hold
  the same Postgres row lock across PUT and commit, so cleanup cannot remove an
  in-flight upload. Changed candidates are skipped for the next sweep.
- Cleanup first commits a terminal `deleted` state under the asset lock, fencing
  delayed commits. It then deletes S3 bytes idempotently and records
  `payload_deleted_at` in a second transaction. Storage failure or a crash after
  S3 deletion leaves a deleted, unpurged candidate for retry. Cleanup never
  resurrects a reservation whose payload may already have disappeared.
  Dry-run never writes access counters, audit, quota, lifecycle state or objects.

## Eviction and accounting

Successful proxy reads update `read_count`/`last_read_at`; presigned issuance is
counted as an access approximation because direct S3 GETs are not observed.
Eviction score is `age_since_last_read_days * size_bytes`, descending; never-read
assets use creation time. Asset id breaks ties. This follows ADR-009's size/age
rule; the historical `*_lfu` metric labels do not imply frequency-based scoring.

Only `cache` and `tmp` may be automatically pressure/quota evicted. `exempt`
assets are always skipped; `users` and `results` are never swept for pressure.
Partition sweeps also require `eviction_sweep_enabled` and a byte quota: trigger
at 90%, expire candidates until available bytes reach 75%. Bucket pressure uses
explicit operator capacity limits, triggers at 90%, and targets 70%.

Quota usage counts **available** assets, released exactly once on expiry/deletion
(matching the current adapters). Physical occupancy estimates count committed
bytes whose payload has not been deleted, including grace-period bytes. These
are different quantities. Pending bytes and unregistered objects are not included
in that estimate. Capacity pressure schedules expiry; actual disk relief waits
for grace. Already expired bytes count as scheduled relief, preventing repeated
over-eviction while waiting. Exhaustion is reported when eligible candidates
cannot reach the projected target, never by evicting exempt/user/results assets.

## Observability and operations

Structured JSON events identify candidate/action, asset id, bucket and reason.
Applied transitions are audited as lifecycle-worker; failures are logged without
credentials or backend exception text. Prometheus collectors expose applied
`gc_evicted_total{space,reason}`, `gc_eviction_exhausted{space}`,
`gc_errors_total{space}`, and estimated `storage_space_used_ratio{space}`.
Dry-run emits candidates but never increments applied-action counters. Metrics
may be written to a Prometheus textfile; scheduled runs must use a dedicated file.

Migration 0002 adds expiry-transition/access/deletion metadata and backfills
existing expired timestamps from updated_at. Existing tmp/results reservations
receive their default deadlines; grace begins when a sweep expires them. Run
Alembic before starting the worker; do not depend on runtime schema alteration.

## Runbook

From the repository root, use the disposable local stack:

```bash
uv sync --locked --group dev
docker compose -f deploy/compose/docker-compose.yml up -d garage postgres
bash deploy/compose/garage-init.sh
set -a
source deploy/compose/.env.garage
set +a
export ASSET_STORE_PG_DSN=postgresql://asset:asset@127.0.0.1:5432/asset_store

# Fresh database, or an existing Alembic-managed database:
uv run --locked alembic upgrade head

# Preview only; the default does not delete or expire anything.
uv run --locked python -m asset_store_core.lifecycle

# Apply one pass after reviewing candidates in the JSON logs.
uv run --locked python -m asset_store_core.lifecycle --apply

# Scheduled worker; metrics are atomically written for a textfile collector.
uv run --locked python -m asset_store_core.lifecycle --apply --interval 60 \
  --metrics-file /tmp/asset-store-lifecycle.prom
```

For an old dev database created by runtime bootstrap without an Alembic version,
first verify that its schema matches migration 0001, then `alembic stamp
0001_initial_schema` before upgrading. Do not stamp an unverified schema. Stop the
old API/worker during migration; restart both on the updated code. Schema
downgrade removes the new fields but does not undo backfilled deadlines or quota
repairs. Applied payload deletions are not reversed by a schema downgrade.

The CLI exits nonzero if any candidate action failed. Failed deletions remain
fenced and eligible for retry. A repeated worker retains Prometheus counters in
memory; separate one-shot runs reset those counters.

API and worker environment configuration:

| Setting | Default | Purpose |
|---|---|---|
| `ASSET_STORE_RESULTS_MAX_TTL_SECONDS` | `31536000` | Maximum and default results TTL for new reservations |
| `ASSET_STORE_CAPACITY_BYTES` | `{}` | JSON bucket byte budgets, e.g. `{"cache":1000000000}`; no capacity gate if absent |
| `ASSET_STORE_CAPACITY_HARD_RATIO` | `0.95` | Prospective committed occupancy ceiling; reject commits with 503 + `Retry-After: 60` |

Configure the same budgets on API and worker. Budgets are operator estimates,
not an automatic S3 disk-capacity probe. A worker-only `--config policy.json` can
override `pending_seconds`, the four-entry `grace_seconds` map, `capacity_bytes`,
`pressure_trigger`, `pressure_target`, `quota_trigger` and `quota_target`.
Prefer the shared environment budget to a worker-only budget override. Changing
the results maximum affects new reservations; migration 0002 backfills existing
results with the documented 365-day default.

High-water and exhausted/error alert examples are in
[`deploy/observability/lifecycle-alerts.yml`](../../deploy/observability/lifecycle-alerts.yml).
Load them into Prometheus and configure node-exporter's textfile collector for the
metrics file directory; the dev stack does not automatically deploy those services.

Acceptance tests (same scenarios on in-memory and Garage/Postgres adapters):

```bash
uv run --locked pytest tests/test_lifecycle_worker.py tests/test_migrations.py -q
```

The lifecycle tests use isolated schemas and clean their objects. The migration
tests reset the public schema: run the full suite only against the disposable
development database. No production cleanup was run while validating this task.
