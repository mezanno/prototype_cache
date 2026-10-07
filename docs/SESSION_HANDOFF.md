# Session reset handoff — updated 2026-10-07

## Current checkpoint — observation reviewed and closed, paused (2026-10-07)

Owner resumed final review after the deadline. The fresh observation finished
2026-10-07 21:38:01 UTC (23:38 Paris), 24 hours 35.53 seconds after start.
[Final evidence](TASK5_RESUME_SOAK_FINAL.json): **2,895/2,895 scheduled reads
verified**, 965 recovered 503 attempts, no read failures; initial 60-read burst
is separate. 965 scheduled rounds; 963 complete resource rounds plus final capture.
One 7h57m39s overnight gap and two unavailable resource captures remain recorded.
Reads succeeded at suspension/resume boundary captures; complete resource
observations resumed on the following minute. Missing-capture cause is unproven
because exception details are intentionally redacted. This closes the bounded
suspension-aware observation, **not uninterrupted 24-hour certification**.

Cleanup check **closed**: existing 32-byte disposable fixture reached deleted
state and physical HEAD absence at 2026-10-07 20:40:49 UTC. Registered assets/
aliases unchanged; retained bytes dropped exactly 32. No observed new origin
connections or monitoring alerts. Container identities unchanged; post-review
application/backend health passed, lifecycle running. Audit grew by 186 rows:
184 granted capabilities, one logical delete and one payload delete. Database
grew 122,880 bytes. Active capabilities peaked at one, registry waiters zero;
disk free ratio stayed above 16.42%. Memory remained within limits but final
lifecycle memory rose 25.02→26.26%, so do not infer absence of slow leaks.
Per-round latency summaries cannot establish a whole-run p95; existing accelerated
p95 1.084 s and overload limits remain material acceptance qualifications.

Removed **only** the `task5-resume-soak.json` cron entry; every other cron entry
preserved. Normal monitoring and lifecycle continue. `deploy/pilot/soak.cron`
is now a retained template, not an installed workload. Protected crontab backup:
`deploy/pilot/private/task5-crontab-before-close.txt`. All original/incomplete/
accelerated/new reports preserved; final private report checksum is recorded in
the public summary. No application/config/image changes, faults or full tests
against pilot data. Latest code suite remains 542 passed; this checkpoint is
reviewed operational evidence/docs only. Commit locally, no push, then **pause**.

Next step requires owner resume: implemented observability and documentation
before real pipeline integration, plus deterministic/seeded randomized fetcher
client/origin/network/internal failure acceptance. No such implementation or
injection has started. Task 5's selected corpus, accelerated workload and
suspension-aware observation steps are closed with coverage/latency limitations;
full-scale/continuous-service certification, representative pipeline workload,
security remediation, Garage inventory, browser recheck, off-host backup/disk
controls and release sign-off remain open. Preserve untracked owner images.

## Current checkpoint — new suspend/resume observation running

Owner explicitly resumed observation on 2026-10-06, then authorized committing
this checkpoint before suspension; **owner will push, agent must not push**. Earlier
pause instructions and disabled-soak status below are historical. No further
implementation or fault injection authorized by this observation request.

New state: `deploy/pilot/private/task5-resume-soak.json` (private, mode 600).
Start **2026-10-06 21:37:26 UTC / 23:37:26 Paris**; 24-hour wall-clock boundary
**2026-10-07 21:37:26 UTC / 23:37:26 Paris**. Minute tick from
`deploy/pilot/soak.cron` is installed; original monitoring entries preserved.
Crontab backup: `deploy/pilot/private/task5-crontab-before-resume.txt`.
[Startup summary](TASK5_RESUME_SOAK_START.json): 60/60 verified burst reads,
one retried 503, p95 84.45 ms, zero origin-counter change. First scheduled sample
had zero issues. Same three approved URLs/two cached resources; no new preloads,
quota changes, cleanup commands, code edits or backend restarts.

Preserve original `task5-soak.json`, `task5-soak-incomplete.json` and accelerated
report; do not rerun `start` or overwrite any existing state. Original expired
32-byte fixture `caa51e80-8874-4eb3-a102-45168c90660b` is reused read-only; bytes
still present initially. Normal grace ends near 2026-10-07 20:40 UTC and scheduled
cleanup may occur after resume; verify registry deletion plus S3 HEAD absence.

Acceptance is **suspension-aware observation**, not uninterrupted availability.
Existing runner records gaps over 180 seconds as `schedule_gap_or_clock_change`;
retain them and correlate with owner-provided suspend/resume times. Compute
active sampling coverage separately from elapsed wall time; never fill missing
samples. It will not make up missed reads. At/after deadline it records final
resources and stops workload; cron then remains installed as a no-op until review
and removal of only this entry. If resume happens after the deadline, no new
reads are launched: final resources alone do not prove read recovery. A separately
approved recovery smoke/new window may be needed. A second day is not automatic.

On session reset: read this handoff first, inspect the new state and timestamps,
verify pilot readiness, monitoring freshness, lifecycle health, expired capability
renewal and expected cleanup. Preserve transient resume errors, resource/origin
changes and missing evidence. Review before removing soak cron; leave monitoring
and lifecycle intact. Do not run full tests against pilot DB. Last code suite:
542 tests passed with separate dev Garage/Postgres; this checkpoint only changes
schedule/docs/evidence. Pipeline observability/documentation and seeded randomized
plus deterministic fetcher fault acceptance remain prerequisites, not implemented.
Security/browser/off-host backup/disk/release gates remain open.

## Current owner pause — 2026-10-06 21:34 UTC

Owner requested a committed consistent state before suspending the computer.
**Pause now; do not start any workload, restart the soak, inject faults or begin
implementation until the owner resumes.** No 24-hour soak is active: cron absence
was reverified; normal monitoring cron remains installed and lifecycle remains
enabled. Those jobs cannot observe the host during suspension. On resume,
verify pilot readiness, monitor freshness, lifecycle recovery and expected expiry
before interpreting measurements; record suspension gaps explicitly. Normal
wall-clock TTL/grace may elapse overnight; do not shorten them or reset state.

Completed checkpoints: `9a3daf1` original soak tooling; `aeacb85` preserved
incomplete soak (30 samples/90 reads); `c6f58ab` accelerated tooling; `eb724ee`
reviewed 15-minute results (4,320 verified reads, 720 retried 503s, p95 1.084 s);
`d57a225` fetcher fault acceptance requirements. Full implementation validation:
542 tests passed, none skipped; Ruff lint/format, strict mypy and client checks
passed. Subsequent changes are docs/evidence only. No pushes. Owner-downloaded
`tmp/native.jpg` and `tmp/default.jpg` remain untracked and must be preserved;
protected runtime/report/backup files stay ignored, never expose credentials.

Next authorized discussion on resume: observability and documentation
prerequisites for real pipeline integration, including a seeded randomized and
deterministic fetcher failure matrix. Implementation and fault execution have
not started. Determine the pipeline's input/output/job-correlation contract;
prepare bounded instrumentation and operator guidance with tests, commit and
pause for approval before advancing. Daytime active-hour/suspend-resume
observation is separate from uninterrupted 24-hour acceptance. Security findings,
Garage inventory coverage, browser recheck, off-host backup/disk controls, tmp
reclamation acceptance and release sign-off remain open.

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

Earlier checkpoints follow chronologically; latest outcome above is authoritative.

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


## Current checkpoint — backup/restore rehearsal passed

Deployment evidence committed as `d425176`; no push. Owner resumed task 2 and
explicitly approved the outage/protected backup after automatic review rejection.
Coherent cold snapshot and isolated restore passed on 2026-10-05: seven database
tables match; all six retained payloads (2,052,400 bytes) match sizes/checksums.
Original and restored cache-hit smoke/readiness passed. Original pilot is healthy;
restore services are stopped, volumes and protected backup retained. See
[rehearsal evidence](BACKUP_RESTORE_REHEARSAL.md), including corrected procedure
errors and remaining daily/off-host/retention gates. The owner approved committing evidence and ADR-037 on 2026-10-06 and
requested a pause. No push; further commits require owner approval.
Task 1's deployed browser recheck remains pending. Pause before task 3 monitoring/
retention/cleanup scheduling until owner resumes. Scheduled cleanup is disabled.

## Historical checkpoint — workspace acceptance

Task 1 browser acceptance was exercised with owner-assisted native confirmations.
The fixture is expired again with its original alias only and `browser: 2026-10-05`
annotation. A disconnect cleanup defect was fixed in workspace JavaScript and
verified in a temporary local UI preview forwarding to the real pilot API.
**The running pilot image is unchanged; the fix is not deployed.**

The owner approved committing this checkpoint: client cleanup/session isolation, 10 Node regressions and
CI wiring, acceptance screenshots and documentation. All 519 Python tests pass
against separate dev Postgres/Garage, all 10 client regressions pass, Ruff/mypy and
syntax/whitespace checks pass. See [updated acceptance](acceptance/ADMIN_UI_LOCAL.md).

The owner approved this commit and forbids pushing. Further commits require approval.
Next: apply the reviewed fix through the normal immutable
pilot image update and recheck disconnect before task 1 closes. Then pause for
explicit owner resume before backup/restore. Do not redo completed browser actions
or infer that the deployed original client contains the fix. Temporary preview
and browser sessions were closed; protected runtime files were not changed.

## Historical checkpoint — 2026-10-01

## Resume instruction

The owner is switching to the desktop harness to enable browser control.
**Resume task 1: admin visual/interaction acceptance.** Do not begin backup/restore
until task 1 is completed, committed and the owner explicitly resumes the next task.
The owner requested work **one task at a time, with a commit and pause between tasks**.
Do not spawn agents; the previous delegation trial was stopped by the owner.
Follow AGENTS.md and the active specs/workplan. No active goal tool state was created.

## Repository and commits

Repository: `/home/joseph/git_github/mezanno/prototype_cache`, branch `main`.

- `9b5ccb4`: private pilot Compose package.
- `0a75eeb`: local deployment, BnF v3/WebP, unified legacy/current full-image resource,
  optional worker/results workflow and quickstart. Amended from `1001025`.
- `fd03437`: task-1 live admin HTTP evidence and browser blocker.
- This handoff is committed in the following checkpoint.

Tracked implementation changes are committed. `tmp/` contains owner-downloaded
`native.jpg` and `default.jpg`, intentionally untracked. Preserve them.
Protected runtime files under `deploy/pilot/private/` are ignored and excluded
from builds; do not expose their values or commit them.

## Running local pilot

Docker Compose project `asset-store-pilot`; separate from the development stack.
Owner authorized deployment on this machine with local/SSH-tunnel access.

- Admin: `http://127.0.0.1:18000/admin`
- Asset-store docs: `http://127.0.0.1:18000/docs`
- Cache docs: `http://127.0.0.1:18001/docs`
- Garage/Postgres backend ports are unpublished; APIs bind host loopback.
- Postgres/Garage/asset-store/fetcher are running. Migration 0003 applied.
- Scheduled lifecycle apply remains **disabled**. Last dry run: no candidates/errors.
- Local results budget: 64 MiB; cache budget: 1 GiB; object cap: 50 MiB.
- Application image: `sha256:cf5736cb6147c223c13760945c76e593cc71213412ab6f3ce154f280e4fae2d7`.
- Backend/build input identities: [deployment record](../deploy/pilot/LOCAL_DEPLOYMENT.md).

Operator command, from repository root:

```bash
pilot() {
  docker compose --env-file deploy/pilot/private/pilot.env -f deploy/pilot/compose.yml "$@"
}
pilot ps
```

Do not replace runtime files, delete volumes, restart unrelated dev services or
run full registry tests against the pilot database. Full tests use the separate
dev Postgres/Garage environment; some tests reset development schemas.

## Credentials and browser access

Existing admin credential is the `admin` entry in
`ASSET_STORE_SERVICE_CREDENTIALS` in protected `deploy/pilot/private/asset.env`.
Enter only its secret into **Admin secret**, then Connect. The page adds
`Service admin:` itself. Do not put the secret in URLs or screenshots/docs.
The owner confirmed login works after correcting an initial copy/paste error.
Asset-store also has distinct fetcher/task-api/worker identities. Fetcher
credentials are in protected `fetcher.env`. Existing secret values need no reset.

This API harness had no browser/app surfaces (`cua.getState()` returned empty
inventories). `cua.createBrowserTab("iab", ...)` failed with browser unavailable.
A pending async question asked the owner to connect a browser. The owner chose
to switch to desktop; do not treat browser interaction acceptance as already done.
In the desktop session, read fresh computer-use documentation and select the
connected admin tab. Browser element bindings from this session do not persist.

## Task 1 evidence and next actions

[Admin acceptance record](acceptance/ADMIN_UI_LOCAL.md) records live HTTP checks:
filtering/usage, annotations, stale revision conflict, attach/detach, eviction,
quota update, expire/read denial, TTL restore/read, bulk expiry, audit and metrics.
**25 focused admin tests passed**, including Postgres. No product code defect
was identified. These checks are not visual or browser-event evidence.

Dedicated disposable fixture, currently **expired**:

- Asset `b71ddbde-ca28-4299-aed7-b0c49f7e763b`
- Results partition `adminchecke280b2bde3ec44f89290ccd7a2818b2f`
- Alias `results/adminchecke280b2bde3ec44f89290ccd7a2818b2f/acceptance/attempt1/worker1/sample.txt`
- 36-byte text; quota 1,024 bytes / 3 assets; no physical purge.

Use only that fixture/partition for acceptance mutations. Preserve cached images
and real task outputs. In the actual browser, check login/disconnect, layout/focus,
filters, quota display, inspect/audit, restore/edit annotation/mutable alias and
expire again, success/error feedback and stale-selection recovery. Record findings
and screenshots without credentials; fix concrete defects with regression tests.
Commit task-1 completion, then pause for owner resume.

Remaining task order: 2 backup/restore; 3 monitoring/retention/cleanup scheduling;
4 security scans and rollback; 5 corpus/concurrency/24-hour soak. Do not silently
approve a release, enable destructive cleanup or advance through pause boundaries.

## Cache behavior and verified content

Exact HTTPS hosts: legacy `gallica.bnf.fr` image paths and current
`openapi.bnf.fr/iiif/image/v3/` paths. JPEG/TIFF and v3 WebP; no queries, credentials,
ports, manifests or arbitrary origins. Redirects retain policy and connection-bound
SSRF/TLS checks. Authenticated preload is explicit; reads are cache-only (404 miss).
Legacy full/full/0/native.jpg maps to current v3 full/max/0/default.jpg for the
same identifier/page, with one asset and canonical v3 bytes. Other renditions are
independent. Cold/forced mapped fetches use v3 because the old API is unstable.

Owner-supplied JPEG pair:

- `https://gallica.bnf.fr/iiif/ark:/12148/bpt6k9907264/f7/full/full/0/native.jpg`
- `https://openapi.bnf.fr/iiif/image/v3/ark:/12148/bpt6k9907264/f7/full/max/0/default.jpg`

Live deployed pair verified one asset, 740,739 bytes, SHA-256
`a7a1f2ba2b730682e1b9a897f303f278b41a614dd417747d074d55746f864e34`.
Direct legacy requests returned 403. Downloaded owner JPEGs have equal dimensions
but slightly different pixels/bytes. Owner reports discussions with BnF specialists
indicating different IIIF servers may back the API versions; this is attributed
architectural context, not independently verified causation. Mapping is logical
resource identity with v3 canonical representation, not a byte-equivalence claim.

Owner-supplied WebP URL also passes preload, cached reads, full-container restart
and asset-store-only restart/capability remint, with unchanged cached-smoke origin
connection counts. Details are in the deployment record.

## Documentation and validation

- [Short deployment/task quickstart](PILOT_QUICKSTART.md): includes both JPEG URLs,
  local read URLs, WebP sample and runnable cache → worker → results example.
- [Deployment runbook](../deploy/pilot/README.md)
- [Deployment evidence](../deploy/pilot/LOCAL_DEPLOYMENT.md)
- [Console walkthrough](guides/admin-console.md)
- [Task 1 evidence](acceptance/ADMIN_UI_LOCAL.md)
- [Workplan](WORKPLAN.md)

Last full suite: **519 passed, none skipped**, with separate development
Garage/Postgres. Ruff lint/format, strict mypy (86 files), whitespace checks pass.
The quickstart's exact Python demo passed against deployed APIs, writing a copied
WebP artifact and manifest last. This is a simulator, not an OCR engine/scheduler.
Only docs/evidence changed after that full run; subsequent 25 admin regressions pass.

## Latest checkpoint — task 3 resumed in CLI (2026-10-06)

Owner resumed task 3; browser recheck remains pending. Lifecycle scheduled after
zero-candidate/error dry run. Minute private health snapshot cron installed;
audit/backup copies retained without deletion scheduling. See [task 3](TASK3_OPERATIONS.md).
Earlier cleanup-disabled/pause-before-task-3 statements are historical.
Owner approved the task-3 commit. Task 4 has not started; wait for explicit
owner approval before security scans or rollback work. No push.

## Latest checkpoint — task 4 performed (2026-10-06)

Owner resumed task 4. Scan/review and app rollback/return passed; current image
f25279675d7e… is restored, backend containers/schema unchanged, lifecycle resumed,
monitor no alerts. Six payloads/stable metadata and pre-existing audit match.
[Task 4 record](TASK4_SECURITY_ROLLBACK.md) lists open High/Critical remediation
and Garage scan coverage limits. No release/risk sign-off. Owner approved committing task 4 and explicitly resumed task 5. No push.
Browser recheck pending.

## Latest checkpoint — task 5 soak running (2026-10-06)

Task 4 committed ab9b251. Owner resumed task 5 and chose three known URLs/two
cached resources. Burst 60/60 hashes passed, one 503 retried; no origin calls.
[Task 5](TASK5_PILOT_ACCEPTANCE.md) / ADR-040 records host-only tooling and fixtures.
Minute soak cron installed alongside monitoring; state private/task5-soak.json,
start 2026-10-06 20:41:37 UTC, full-window deadline 2026-10-07 20:41:37 UTC.
Do not claim completion before then, overwrite state or rerun start. Final review
must assess sample gaps/errors, resources and tmp fixture reclamation. Dedicated
32-byte tmp asset caa51e80-8874-4eb3-a102-45168c90660b was scheduled-expired before
start; normal 24-hour grace retained. Remove only the soak cron after review.
536 tests/quality checks pass. Task-5 tooling/docs checkpoint committed; no push. Existing
security findings and browser/off-host/disk/release gates remain open.

## Task 5 checkpoint review — 2026-10-06

Owner requested continuation with a commit and approval pause at each important
step. Reviewed existing acceptance tooling, corpus, tests and startup evidence;
no running schedule/state, application code or backend images changed. Confirmed
pilot health and separate development backends. Fresh focused suite: 11 passed;
Ruff lint/format, strict mypy (90 files) and Node client suite passed.
At 20:57:01 UTC, private soak state contained 16 samples, 48 successful reads,
16 explicit retried 503 attempts and zero recorded issues. This is an interim
observation, not full-window acceptance. Preserve original deadline and state.
Pause after committing this checkpoint; ask owner approval before the final
post-deadline review and removal of only the soak cron. Existing automated
soak/monitoring/lifecycle schedules continue during the approval pause.

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

Schedule verification at 2026-10-06 21:38:01 UTC: automatic second sample
recorded, state running, zero issues. Private mode 600 and original incomplete
soak preservation verified. Owner subsequently authorized the checkpoint commit; pushing remains with owner.
