# M-001 task 3 — monitoring, retention and cleanup

B-004/B-014/B-019 / FR-050/060/064/068 / NFR-009 / ADR-038.
Owner resumed in CLI on 2026-10-06; deployed browser disconnect recheck remains pending.

## Retention policy

Docker diagnostic logs remain bounded at 10 MiB × 3 files per container, without
30-day coverage guarantees. Database audit is authoritative: retain all pilot
audit/metadata/tombstones, at least 30 days; no SQL deletion job. Audit export and
long-term archiving remain wider readiness work. Retain task-2 protected backup
and restore volumes; no automatic deletion. Daily backups still require an outage
window, encrypted off-host destination and approved retention policy (ADR-037).

Payload policy is unchanged: tmp default TTL 24 hours, results maximum/default
365 days, cache/users no default TTL. Tmp grace is 24 hours, other buckets 7 days.
Cache/tmp pressure eviction starts at 90% budget; exempt assets and users/results
are protected from pressure eviction. Exemption does not prevent TTL cleanup.
Health snapshots replace one mode-600 JSON file each minute, without history growth.

## CLI monitoring

`deploy/pilot/monitor.py` reads API readiness/metrics, Compose service health,
lifecycle textfile age/metrics and free space on Docker's actual data filesystem.
It never fetches origins or changes registry state. Local ports are 18000/18001;
adapt deliberately if deployment ports change. No credential or alias/partition
metric labels are emitted.

```bash
.venv/bin/python deploy/pilot/monitor.py
cat deploy/pilot/private/monitor.json
```

Counters are cumulative since process startup; compare snapshots for rates.
Cache outcomes retain hit/miss/error labels; upload admission and registry pool
signals identify local saturation. Alerts cover unhealthy/missing services,
unavailable HTTP/metrics/Docker/disk, nonfinite metrics, lifecycle older than
180 seconds, per-bucket occupancy above 80%, exhausted eviction, cleanup errors,
and Docker filesystem under 10% free. Cleanup errors warn until restart/review.
Check snapshot timestamp too: stale JSON means the monitor schedule needs review.
This local operator check has no paging/notifications or SLO claim.

The checked-in `deploy/pilot/monitor.cron` is installed for user joseph. Previous
crontab was empty. It replaces the private JSON snapshot each minute; inspect
with `crontab -l`. Disable by removing only this entry, preserving other jobs.
Cron requires host Docker access and the repository virtualenv. Output is
redirected; run interactively if the snapshot timestamp stops advancing.

## Live acceptance — 2026-10-06

Original four services healthy. Existing-image lifecycle dry run: zero candidates,
applied/skipped/errors and no exhaustion. Then enabled existing maintenance
worker (`--apply --interval 60`) with the already deployed immutable image.
Fresh lifecycle metrics: cache about 0.13%, results about 0.98%, tmp/users zero;
no cleanup errors/exhaustion. No candidates changed in the initial pass.

First monitor sample flagged unavailable asset metrics; subsequent direct read
and snapshot passed. The initial warning is retained as an observation.
Docker filesystem free space was about 98.3 GB / 10.01%, near the 10% warning
threshold. Address host headroom before expanding corpus/soak; no unrelated files
or volumes were removed and no quotas raised.

Stop cleanup with `pilot stop lifecycle` using the existing runbook helper.
Actions remain audited and deletion-fenced. Metadata is retained; payload deletion
requires restore/preload for recovery. Task-2 backup remains protected and retained.
No backup schedule, audit purge or host cleanup was added.

## Remaining gates

Host disk quotas/headroom, off-host backup selections, remote alerting, full
dashboards and audit export remain open. Task 4 security scans/rollback and Task 5
corpus/concurrency/soak are separate. Owner approved committing this checkpoint; no push. Wait for explicit approval
before starting task 4.
Browser acceptance remains pending.

Security review: monitor uses no application credentials, emits only selected
metric names and controlled outcome/bucket/reason labels, and suppresses backend
exception text. Docker access remains operator-level authority; the monitor
issues read-only Docker operations. Snapshot replacement uses a mode-600 temporary
file in the same protected directory. Cleanup reuses existing audited lifecycle
locks/deletion fences; no new capability or deletion API was introduced.

Schedule acceptance: installed crontab re-read successfully; subsequent JSON
snapshot timestamp advanced without manual invocation and reported no alerts.
Worker logs showed repeated zero-candidate/error applied sweeps.

Validation: **525 Python tests passed, none skipped**, using separate development
Garage/Postgres; two existing upstream deprecation warnings. Node client suite
passed. Ruff lint/format, strict mypy (88 files) and whitespace checks passed.
