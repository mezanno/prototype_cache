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

## Accelerated run (ADR-041)

Prepare a new private report path, then run from the repository root:

```bash
.venv/bin/python tools/cache-pilot/accelerated_acceptance.py \
  --state deploy/pilot/private/task5-accelerated.json
```

The owner approved the first run on 2026-10-06; reviewed results are in
[Task 5 evidence](../../docs/TASK5_ACCELERATED_EVIDENCE.json). A new run requires
a fresh report path and owner approval at the current checkpoint.
The command stays in the foreground; it installs no cron. Three persistent HTTP
clients target 1,440 reads each over 900 seconds (one per client every 0.625 s).
Existing overload retries can consume several slots: missed slots are counted
and skipped, never replayed in a catch-up burst. At 900 seconds no new reads
start; bounded in-flight reads/retries and final measurements can extend command
completion beyond 15 minutes. This is a target volume, not a guarantee of 4,320
completed reads. Successful-read p95 includes retry backoff; HTTP statuses and
failed reads remain visible. No preloads, quota changes or cleanup mutations.

The frozen three-URL/two-resource corpus and protected credentials are reused.
Minute resource snapshots and final resources/origin counters use the existing
observer. Review memory/CPU/PIDs, container identities, capabilities, database
and audit growth, disk/lifecycle/monitor signals, missing observations and origin
changes. The report retains at most 4,320 read outcomes plus roughly 16 resource
snapshots, is mode 600, and cannot overwrite an existing report. Exclusive locking
rejects overlapping invocations for the same report. Use Ctrl-C for a recorded
interruption; abrupt process/host loss can leave a `running` checkpoint with only
resource snapshots, which must be treated as incomplete, never resumed by
replacing that evidence. Credentials and exception text are excluded from output.

Resource observations are checkpoints; per-read details are written at normal
completion or Ctrl-C. Sampling does not report per-second resource peaks. Keep
the computer awake during this run. No automated release sign-off; cleanup grace,
slow leaks and suspend/resume behavior require separate observations. Pipeline
integration requires observability implementation and documentation first.
