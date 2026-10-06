# M-001 task 5 — bounded corpus, concurrency and 24-hour soak

## Current disposition — stopped incomplete (2026-10-06)

Owner approved ending the uninterrupted soak in favor of a future accelerated
run and daytime observation. Only the task-5 cron entry was removed at
21:11:11 UTC; monitoring and lifecycle schedules were preserved. Original state
was not rewritten or restarted. A byte-identical mode-600 snapshot is retained
as `deploy/pilot/private/task5-soak-incomplete.json`; original cron is retained
privately for recovery. The original state still says `running`, but no soak
schedule remains: that value is historical, not evidence of an active run.

[Stopped-run summary](TASK5_INCOMPLETE_EVIDENCE.json): 30 samples, 90 successful
reads, 30 explicit retried 503 responses, no read errors or recorded issues.
Roughly 30 minutes of observation is **not a passed 24-hour soak**. Normal
expiry/deletion grace is unchanged; fixture reclamation acceptance is pending.
The workload's startup burst remains separate from these scheduled totals.

Next checkpoint: prepare and test a paced 15-minute accelerated workload,
commit, and pause for owner approval before execution. Before any integration
into the real processing pipeline, **implement observability and documentation**
and validate them as their own checkpoint. This must cover input retrieval,
processing/result publication, job correlation, timings, failures/retries,
overload, resource measurements and credential-safe operator guidance. Confirm
the pipeline contract before selecting concrete instrumentation. Existing
monitoring is a baseline, not completion of that integration prerequisite.
Daytime observations must report cumulative active time, suspension gaps and
resume recovery; they cannot claim an uninterrupted 24-hour soak.


B-015/B-019, SCN-010, NFR-002/004/005, FR-050/064; ADR-040.
Owner resumed task 5 after approving task-4 commit. Security remediation and
browser acceptance remain open; this workload cannot approve a release.

## Planned acceptance

Freeze the reviewed corpus with expected size/SHA-256 before running. The three
previously approved URLs represent two unique stored resources; the owner explicitly selected those three URLs. The proposed 100-URL
milestone fixture is not silently replaced with a claimed full-scale result.

Use three clients for a 20-read-per-client burst, recording successful latency,
bytes, each HTTP status and bounded overload retries. Existing fetcher admission
is two jobs: three clients may observe explicit 503/Retry-After. Preserve these
observations even if retries succeed; never raise limits for a passing result.

Then schedule three verified cache-only reads each minute for a real 24 hours,
rotating corpus entries. Record process memory/CPU/PIDs, database row counts/size,
private monitor freshness/lifecycle/error/disk signals, active capability state
and outbound-origin connection counters. Stop workload at the elapsed 24-hour
boundary and mark observations ready for review. Missing schedules, checksums,
new origin connections, unexpected errors/restarts and resource warnings remain
visible; no automatic go/no-go or notification to testers.

Reports and locks stay in ignored protected private storage; one bounded state
file contains at most 1,441 samples and is atomically replaced. Scheduled overlap
is skipped under an exclusive lock. Credentials come from protected fetcher env;
never appear in URLs, argv, logs or evidence. No origin preloads occur in the soak,
no quota changes or deletion commands are introduced. Lifecycle remains enabled.

A dedicated tiny tmp fixture will exercise live scheduled expiry and payload
reclamation without altering grace: upload with a 5-second TTL, observe available
then expired, and start the soak after expiry. Its normal 24-hour grace expires
during the observation window; compare its lifecycle row with a direct S3 HEAD.
Only this disposable fixture may be reclaimed by this check; real cached images
and outputs are preserved. Record the expected fixture-byte reduction separately
from unexpected registered-content changes. Full registry metadata remains retained.

## Initial execution — 2026-10-06

[Startup evidence](TASK5_START_EVIDENCE.json) records the frozen three-URL corpus
and two distinct cached resources, all SHA-256 verified. Repeated preload reused
the two existing assets. Cache-only miss returned 404 in about 6.74 ms without
origin calls; unapproved host returned 403, invalid credential 401. There were
no new origin connections during these controls or the concurrency burst.

Burst: three clients, 60/60 successful logical reads, 42,735,480 bytes. HTTP
attempts: 60 × 200 and one explicit 503, recovered by bounded retry. P95 including
backoff 30.63 ms; maximum 1,045.18 ms. No checksum mismatch/unrecovered errors.
These are local cached-read measurements on two unique resources, not the full
30-reader or 100-URL benchmark. Cold-ingestion/miss-to-origin latency is not
measured by this cache-only workload.

Dedicated tmp fixture: 32 bytes, asset `caa51e80-8874-4eb3-a102-45168c90660b`.
It was available after upload, then the unchanged scheduled worker marked it
expired at 2026-10-06 20:40:07 UTC; physical bytes still existed at soak start.
Grace remains 24 hours. Expect terminal deletion/reclamation around the next
day's sweep; record direct HEAD and registry state at final review. A setup
helper initially asserted the wrong HTTP status for capability issuance, then
for resolve. The existing uploaded fixture was recovered without duplicating
assets; normal setup issuance audit is retained. No payload was deleted by the
setup script.

The true soak window starts **2026-10-06 20:41:37 UTC** and reaches 24 hours at
**2026-10-07 20:41:37 UTC** (22:41 Paris time). Installed minute tick is
`deploy/pilot/soak.cron`, added to joseph's crontab without replacing monitoring.
Full samples reside in protected `deploy/pilot/private/task5-soak.json`.
Stop by removing only the soak entry; preserve monitoring and lifecycle.
Completed tick becomes a no-op; remove its cron entry after evidence review.
No outside messages/paging are sent.

The first sample reported zero issues and fresh lifecycle/monitor metrics.
**Task 5 remains in progress until the full window is observed and reviewed.**
A stopped machine/schedule or missing observations must be recorded, never
filled with synthetic samples or treated as a completed soak. Do not rerun start
over this report. Security remediation, off-host backup/disk quota selections,
browser recheck and owner/operator/tester release sign-off remain open.

Validation: 536 Python tests passed, none skipped, including a real local HTTP
three-client harness test; two existing upstream deprecation warnings. Ruff
lint/format and strict typing passed (90 files). No production app code or
backend images changed; task-5 changes are host-side acceptance tooling/docs.

Schedule acceptance: a second sample appeared without manual tick invocation;
zero issues were recorded. Monitor-age validation was corrected during initial
setup to use actual resource-capture time rather than the preceding read-round
start, avoiding false warnings when the monitor finishes concurrently. Existing
samples remain retained and the actual 24-hour clock is unchanged.

Final review must total successful/failing requests and explicit overloads,
check sampling coverage and gaps, compare min/max/final memory/capabilities/
database/audit/disk measurements, verify no new origin connections or content
changes beyond the known fixture, and confirm fixture state deleted plus physical
HEAD absence. Missing cleanup evidence is an open check, not a passed result.
The release disposition remains **not approved** while High/Critical remediation,
Garage inventory coverage, browser acceptance and operator/tester/off-host/disk
gates remain unresolved, even if workload observations eventually pass.

Latest initial schedule verification: three samples recorded automatically, zero
issues, all sampled reads successful. Some minute rounds also observe explicit
503/retry; their per-round p95 with only three reads includes that backoff and
can exceed one second. This is retained overload evidence, not hidden zero-error
SLO certification. Latency summaries are per round; the 60-read startup burst
provides the initial larger-sample p95. Node client suite also passed.

## Resumed checkpoint review — 2026-10-06

Existing task-5 tooling and startup evidence reviewed for a consistent commit.
Pilot services healthy; focused acceptance tests (11), Node client regressions,
Ruff lint/format and strict mypy passed again. At 20:57:01 UTC, 16 scheduled
samples held 48 successful reads, 16 retried 503 attempts and zero recorded issues.
The original state and 24-hour deadline remain unchanged. Owner requested a
commit and approval pause before each following step; automated observation
continues while paused. Final review remains pending after the deadline.

Fresh full suite against isolated development Garage/Postgres: **536 passed,
none skipped**, with two existing upstream deprecation warnings.

## Accelerated tooling checkpoint — 2026-10-06

ADR-041 provides a separate 15-minute foreground runner targeting 4,320 cached
reads with three persistent clients. Backpressure skips slots; it never changes
limits or forces catch-up. Every outcome/missed slot and minute/final resource
signals remain available for review. The incomplete soak stays preserved and
its schedule disabled. See [operator instructions](../tools/cache-pilot/README.md).
Owner approved preparation only; commit and pause before live execution. Real
pipeline integration remains gated on implemented observability and documentation.

Preparation validation: **542 tests passed, none skipped**, against separate
development Garage/Postgres; two existing upstream deprecation warnings. Ruff
lint/format, strict mypy (91 files), Node client suite and CLI help passed.
No accelerated pilot execution or schedule installation occurred.

## Accelerated execution reviewed — 2026-10-06

Owner approved live execution after preparation commit `c6f58ab`.
[Reviewed evidence](TASK5_ACCELERATED_EVIDENCE.json) records 21:15:01–21:30:01 UTC,
900.01 seconds of workload. All three clients completed their 1,440 slots:
**4,320/4,320 successful size/SHA-256/ETag/MIME-verified reads**, 3,076,954,560
bytes, zero missed/unstarted slots and no read failures. All launches occurred
before the deadline. **720 explicit 503 attempts** recovered through existing
bounded retries; no limits were raised. Whole-run p95 including retries was
1,084.29 ms, maximum 1,154.03 ms. This does **not** establish the 200 ms latency
target or full-scale concurrency certification; overload latency remains visible.

Sixteen resource observations including final capture; largest scheduled sample
gap 64.45 seconds. No new origin connections, monitoring alerts, container
recreation or registered-content changes. Application/backend health passed
again. Audit grew 64→66 rows: two granted `capability.issue` events. Database
size grew by 8,192 bytes. Active capabilities peaked at one; registry waiters
at zero. Docker disk free-space ratio stayed at least 16.82%. Sampled memory:
asset-store 15.76–15.83%, fetcher 9.54–9.88%, Postgres 3.63–4.03%, Garage
1.10–1.16%, lifecycle 24.98–25.02%; these are sampled values, not proof against
slow leaks or short peaks. Original incomplete soak and its private snapshot
remain unchanged; no cron was installed for this foreground run.

Outcome: accelerated integrity/volume and observed stability checks passed;
latency/overload and coverage limits retained. This is two unique cached resources,
not the real pipeline or a 24-hour soak. Normal fixture cleanup grace remains
unchanged and reclamation acceptance is still pending. Security/browser/backup/
release gates remain open. Pipeline integration requires implemented observability
and documentation first. Commit evidence and pause for owner approval before
starting that prerequisite work. Last code validation remains 542 tests passed;
this checkpoint changes evidence/docs only. Private full report is mode 600 with
checksum recorded in the public summary.

## Fetcher fault-injection acceptance prerequisite — 2026-10-06

Owner explicitly requested randomized client/origin HTTP errors, unexpected
failures and network failures. Include this in the observability/documentation
prerequisite, then implement a bounded isolated fault harness and pause for
approval before live fault injection or pipeline integration. Existing accelerated
cache-only success does not exercise origin failure handling.

Required scenarios: client invalid/unauthorized requests and disconnect/cancel;
origin 404/429/500/502/503 and recovery; DNS/connect refusal/reset, connect/read
timeout, TLS failure, truncated/slow response bodies; unexpected internal/backend
exceptions. Define expected outcomes from the existing fetcher contract before
implementation (upstream HTTP/transport failures → 502, upstream timeout → 504;
client and admission errors retain their documented status). No new automatic
retry policy is implied by origin 429/503. Use seeded random sequences plus
forced deterministic coverage, recording seed, injected fault counts, observed
statuses, latency, recovery and failed attempts so rare cases cannot be missed.

Verify no corrupt or partially published available assets, preserved prior cached
bytes after failed refetch, released admission slots/connections, bounded state,
no credential/URL leakage in logs, and correctly correlated metrics/logs/audit.
Follow failed requests with successful requests to prove recovery. Keep fault
origins and backend failures isolated from real BnF and retained pilot content;
do not disable SSRF/TLS controls in the running pilot. Service restarts or host
network disruption require a separately reviewed scope.

Coverage baseline: `tests/test_fetcher_service.py` already covers origin 404,
502/504 mapping, slow-read timeout, redirect/body caps; `test_fetcher_refetch.py`
covers failed-refetch preservation; `test_fetcher_garage.py` covers a real origin
503; `test_fetcher_transport.py` covers connection deadlines, validated address
fallback, TLS and connection release. This is existing partial coverage, not
completion of the new randomized end-to-end failure matrix. Identify remaining
gaps when implementing the harness and observability. No injection performed.
