# Task 1 — local admin acceptance (2026-10-01)

**Status: live HTTP acceptance passed; visual/interaction acceptance blocked.**
Requirement: B-013 / SCN-004 / FR-040–042 / FR-005–007 / FR-051–053.
The owner requested one task at a time with a commit and pause between tasks.
Task 2 (backup/restore) has not started.

## Environment and scope

Running local pilot, asset-store at `http://127.0.0.1:18000/admin`, durable
Postgres/Garage. Existing protected admin and worker credentials were used;
no secrets are recorded here. The owner previously confirmed login works after
correcting copy/paste. Other UI actions are not inferred from that confirmation.

A dedicated 36-byte text fixture was uploaded through the guarded HTTP path:

- Asset: `b71ddbde-ca28-4299-aed7-b0c49f7e763b`
- Partition: `adminchecke280b2bde3ec44f89290ccd7a2818b2f`
- Alias: `results/adminchecke280b2bde3ec44f89290ccd7a2818b2f/acceptance/attempt1/worker1/sample.txt`
- Final state: **expired**; physical bytes are retained for normal lifecycle cleanup.

Only this fixture/partition was mutated. Cached images and task result artifacts
were preserved. Scheduled cleanup remains disabled. No permanent payload purge
or database reset was performed.

## Observed through real HTTP endpoints

| Check | Result |
|---|---|
| Anonymous admin data request | 401 |
| Filter by results/partition/prefix and one-row page | Correct fixture; no raw storage key |
| Partition usage | 36 bytes; matching asset count |
| Annotation update | Saved string map |
| Mutation with stale revision | 409 conflict |
| Mutable secondary alias attach/detach | Added/removed on this asset only |
| Eviction policy | Exempt saved |
| Dedicated partition quota | 1,024 bytes / 3 assets; usage preserved |
| Expire and guarded read | Expired; read returned 410 |
| TTL restoration | Available; downloaded bytes matched fixture |
| Bulk-expiry preview/apply | One candidate; one applied, zero skipped |
| Related audit | Authenticated admin events present |
| Action metrics | Annotation success counter present |

The disposable fixture was expired again by the bulk check. The protected runtime
record is `deploy/pilot/private/admin-acceptance-evidence.json`.
Focused validation: **25 admin regression tests passed**, including the
Postgres-backed cases; only two existing upstream deprecation warnings.
Existing admin regression tests exercise memory/Postgres contract cases; this
record adds real deployed HTTP evidence, not a new product feature or ADR.

## Browser blocker and remaining checks

Computer-use inventory reported no available browser/app surfaces. Attempting
`createBrowserTab("iab", ...)` returned **Browser is not available: iab**.
A connected browser is required before declaring B-013 UI acceptance complete.
HTTP responses cannot establish visual layout or correct browser event handling.

Resume task 1 after connecting a browser containing the local admin page:

1. Check layout, visible status, keyboard focus and connect/disconnect behavior.
2. Filter to the dedicated results partition and expired fixture above; inspect
   metadata, annotations, quota display and audit history.
3. Restore the fixture with TTL, edit its test annotation, attach/detach a mutable
   test alias, then expire it again through the visible UI controls.
4. Check displayed success/error feedback and stale-selection recovery; ensure
   Disconnect clears displayed data and in-memory credential usage.
5. Record browser screenshots/findings, fix concrete defects with regressions,
   commit completion and pause for owner resume before backup/restore.

Do not perform these mutations on the owner's cached images or real task outputs.
