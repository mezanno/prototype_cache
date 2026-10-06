# M-001 task 5 — bounded corpus, concurrency and 24-hour soak

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
