# Task 1 — local admin acceptance (2026-10-05)

**Status: reviewed fix deployed; CLI acceptance passed on 2026-10-05.**
The deployed browser disconnect recheck remains pending in this CLI-only session.
See [image update evidence](../../deploy/pilot/LOCAL_DEPLOYMENT.md#cli-image-update--2026-10-05).
The historical workspace evidence below predates deployment.
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

## Browser acceptance (2026-10-05)

The desktop in-app browser could reach the pilot at `127.0.0.1:18000/admin`.
The earlier no-browser blocker is resolved. Native JavaScript confirmation dialogs
blocked the automation API; the owner accepted these dialogs while the agent
operated the controls and verified each result. This is assisted browser evidence,
not an unattended browser test suite.

| Check | Browser result |
|---|---|
| Connect and filtered listing | Dedicated expired fixture, 36 bytes, quota 1,024 bytes / 3 assets |
| Inspect and related audit | Correct metadata, aliases and admin history; no raw storage key |
| TTL restore | Available; quota usage changed to 36 bytes / 1 asset; TTL audit appeared |
| Annotation save | Added `browser: 2026-10-05`; success feedback and audit appeared |
| Mutable alias | Attached then detached `.../worker1/browser.txt`; original alias retained |
| Invalid annotation JSON | Visible error; saved annotations preserved |
| Expire | Returned to expired; quota usage returned to 0 bytes / 0 assets |
| Stale revision in second tab | Rejected with “asset changed; reload before applying”; reselect refreshed metadata |
| State and alias-prefix filters | Available/nonmatching prefix produced no rows; expired/matching prefix returned the fixture |
| Bulk preview after expiry | Zero candidates; apply button disabled |
| Failed login and recovery | Invalid credential feedback; valid reconnect succeeded |
| Disconnect | Found retained quota edit values; corrected client clears them and denies reads until reconnect |
| Desktop and narrow layout | Readable at default desktop viewport and 390-pixel viewport; no document overflow |
| Keyboard focus | Tab navigation displayed a visible focus outline; controls remained accessible |

Final fixture state: **expired**, payload unpurged, original alias only, eviction
policy `exempt`, quota unchanged (1,024 bytes / 3 assets). The browser annotation
is retained as evidence. Cached images and real task outputs were not mutated.
No physical cleanup or scheduling changes were made.

## Confirmed defect and correction

Disconnect removed the asset panels but left loaded quota limits visible and
retained annotation/alias edit values in hidden controls. Additionally, controlled
JavaScript tests reproduced late responses restoring old data after disconnect.
The client now clears loaded/editable state on disconnect or a new connection,
and discards both successful responses and errors from an earlier connection.
User-entered list filters remain for convenient reconnection. Already submitted
server mutations are not cancelled or undone by disconnect.

The corrected workspace UI was served temporarily at `127.0.0.1:18002/admin`,
with `/admin/api` forwarded to the unchanged pilot API. No API responses were
mocked in these browser checks. This verified the actual workspace JavaScript
without modifying protected runtime files, replacing the immutable pilot image,
or restarting services. The preview and browser sessions were stopped afterward.
The correction is **not yet deployed** at port 18000.

Security review: old responses cannot repopulate disconnected pages or overwrite
new-session feedback. Credentials remain in page memory only; no credential was
saved in screenshots, URLs, source or test fixtures. Existing admin authorization,
revision checks, API audit, action metrics and structured logs remain in use.
No new server critical path or architecture decision was introduced.

## Validation and evidence

- **519 Python tests passed, none skipped**, using the separate development
  Postgres/Garage stack; two upstream deprecation warnings.
- **10 JavaScript client regressions passed** with Node 22 and no npm dependencies.
  They cover field clearing, delayed list/inspection/audit/preview responses,
  reconnect, errors, delayed JSON decoding and mutation completion after disconnect.
  All 10 fail against the original client, confirming the regression coverage.
- Ruff lint/format, strict mypy (86 files), JavaScript syntax and whitespace checks pass.
- CI now runs the JavaScript suite with Node 22 alongside existing checks.

Screenshots show the corrected workspace UI using the real fixture:
[desktop overview](images/admin-summary.png), [full desktop](images/admin-desktop.png),
[narrow layout](images/admin-narrow.png), [disconnected fields](images/admin-disconnected.png).

The owner approved committing this checkpoint; no push. Next: apply the reviewed client
through the normal immutable-image pilot update and recheck disconnect, then pause
for explicit owner resume before task 2 (backup/restore).
