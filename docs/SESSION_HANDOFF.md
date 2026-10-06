# Session reset handoff — updated 2026-10-05

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
