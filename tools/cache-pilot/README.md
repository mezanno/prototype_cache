# Private Gallica cache HTTP smoke check

M-001 / B-024 / SCN-010 / FR-010–015 / FR-020–022. This script calls the running
fetcher API over HTTP: one explicit preload, two byte reads and another preload.
It compares read hashes with ETags, enforces a download cap and requires the
second preload to reuse the same asset. It exits 0 on success, 1 on failure.
It may fetch one approved origin image on a miss; choose a reviewed URL before
running. It never forces refetch, deletes content or prints credentials/URLs.

Run from the repository root with its existing Python environment:

```bash
export CACHE_PILOT_BASE_URL=http://127.0.0.1:8081
export CACHE_PILOT_ORIGIN_URL=https://openapi.bnf.fr/iiif/image/v3/ark:/12148/bd6t543024772/f18/full/max/0/default.webp
export CACHE_PILOT_SERVICE_ID=task-api
read -rsp 'Task API service secret: ' CACHE_PILOT_SERVICE_SECRET
export CACHE_PILOT_SERVICE_SECRET
PYTHONPATH=src .venv/bin/python tools/cache-pilot/cache_smoke.py
unset CACHE_PILOT_SERVICE_SECRET
```

Use the actual approved origin URL and cache endpoint. The example host/port
assumes a local service or SSH tunnel; other hosts require HTTPS. The script
verifies TLS, disables environment proxies and does not follow redirects.
Optional `CACHE_PILOT_MAX_BYTES` defaults to 50 MiB; align it with service limits.
Secrets must come from operator provisioning, not development defaults. Both
`task-api` and `admin` identities are supported. Source queries are unsupported.

Successful output includes only byte count, SHA-256 and hit flags. Failure
output includes a sanitized HTTP status or contract/configuration failure.
For 401/403 check the service credential and URL policy; for 409 retry preload;
for 503 consult admission metrics and Retry-After; for 502/504 check origin or
backend health. The script deliberately does not retry automatically.

## Automated evidence and limits

- `tests/test_cache_smoke.py`: a real local HTTP cache API socket, generated JPEG
  fixture, verified read hashes, one origin call, and negative protocol/limit tests.
- `tests/test_gallica_garage.py`: local HTTPS origin with a Gallica hostname
  certificate, production URL policy, Garage bytes, isolated Postgres metadata,
  origin failure, committed concurrent hits and registry/application restart.
  Test-only DNS/port mapping and private-address permission are scoped to the
  fixture; production connection enforcement is unchanged.
- Existing policy tests cover denied redirect destinations, rendition separation,
  byte caps, immutable refetch mismatch and the documented concurrent conflict.

These are local implementation checks. They do not prove a live Gallica corpus,
fresh private deployment, full process/container restart or production readiness.
P4 runs this script against the packaged stack; P6 records corpus/soak acceptance.

## Bounded concurrency and 24-hour soak (Task 5 / ADR-040)

`pilot_acceptance.py` uses the owner-selected `pilot-corpus.json` (three URLs,
two unique JPEG/WebP resources) with frozen size/SHA-256. Three HTTP clients issue
20 reads each at start, preserving overload/retry status counts and end-to-end
latency. Tick mode performs three cache-only verified reads, rotates the corpus,
records resource/lifecycle/origin signals, and never requests origin preload.
Credential input defaults to protected `deploy/pilot/private/fetcher.env`;
URLs, credentials and exception text are omitted from runtime reports.

```bash
# State directory must be private. Refuses to overwrite an existing run.
.venv/bin/python tools/cache-pilot/pilot_acceptance.py start \
  --state deploy/pilot/private/task5-soak.json --fixture-id <dedicated-tmp-asset-id>
# Schedule the tick entry from deploy/pilot/soak.cron, preserving existing cron jobs.
.venv/bin/python tools/cache-pilot/pilot_acceptance.py tick \
  --state deploy/pilot/private/task5-soak.json
```

The state file is mode 600, atomically replaced and bounded to 1,441 samples;
exclusive locking skips overlapping invocations. Each observed sample records
byte integrity, successes/failures, HTTP attempt statuses, p95 including retry
backoff, Docker memory/CPU/PIDs/IDs, database size/counts, active capabilities,
monitor/disk/lifecycle signals and origin-counter changes. Retry is capped at
three total attempts for 503 only; other errors remain failures.
At the real 24-hour deadline the workload stops and marks observations ready for
review. It does not grant release approval or send external notifications.
Inspect state timestamp and sample gaps; stopped cron or changed credentials
must not be mistaken for successful observation. Short unit tests never count
as soak evidence. See [Task 5](../../docs/TASK5_PILOT_ACCEPTANCE.md).
