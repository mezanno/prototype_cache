# M-001 task 2 — backup/restore rehearsal

B-017 / B-019 / NFR-005; pilot P5 and the backup/restore gate in
[operations](spec/04_OPERATIONS.md). Executed 2026-10-05; **isolated restore passed** (ADR-037).

## Proposed coherent cold backup

The single-host pilot permits planned downtime. Stop fetcher and asset-store
first, then stop Postgres and Garage gracefully. With all writers stopped,
archive these three named volumes into mode-600 gzip tar files inside a new
mode-700 directory under ignored `deploy/pilot/private/`:

- `asset-store-pilot_postgres-data`
- `asset-store-pilot_garage-meta`
- `asset-store-pilot_garage-data`

Capture the protected runtime files and resolved Compose configuration alongside
the archives; these contain database, Garage and service credentials. Never print
or commit them. Record archive SHA-256 hashes, image digests, source checkpoint,
snapshot time and archive sizes. Always restart the original pilot on failure;
check both readiness endpoints before proceeding. Retain original volumes.

This is a coordinated cold-volume snapshot, not an online database backup or
PITR implementation. Restore requires the same pinned Postgres/Garage versions;
no backend upgrade is part of this rehearsal. Local copies do not protect against
host loss; an approved encrypted off-host destination remains an operating gate.

## Isolated restore and checks

Create a separate Compose project `asset-store-restore-20261005` and three fresh
volumes. Extract only this trusted snapshot into those volumes using a temporary
root helper with no network. Use captured configuration and the same pinned
application/backend images; change only project/volume identities and loopback
API ports (18100/18101). Postgres/Garage ports remain unpublished. Scheduled
lifecycle apply remains excluded. Original pilot storage must never be mounted
writable by restore services. Before extraction, verify archive hashes and reject
pre-existing restore volumes to prevent overwriting an earlier rehearsal.

Check migrations and readiness. Compare asset and alias records with the
snapshot baseline. Read every retained committed payload from restored Garage,
checking registry size and SHA-256; separately verify expired fixture state,
quota and audit records. Run authenticated cache-hit HTTP smoke through restored
fetcher; require the existing asset identity/checksum and repeat-hit result.
Check the original pilot remains healthy and unchanged. Stop the isolated restore
stack after evidence collection; retain its volumes and protected backup until
the owner approves retention/deletion. Do not run `down -v` on the pilot.

## Authorization status

The owner requested backup/restore checks. Automatic approval review rejected the
proposed execution on 2026-10-05 because the specific pilot outage and sensitive
configuration copying were not explicitly authorized. No services were stopped,
no archives were created and no restore stack was started by that rejected call.
Explicit approval of a brief pilot outage, protected credential-containing copies,
and isolated volume restore is required before retrying. Task 2 remains pending.

## Executed evidence — 2026-10-05

The owner explicitly approved resumption after the automatic review block.
Protected backup: `deploy/pilot/private/backup-20261005-02/` (ignored by Git).
Directory mode 700 and all files mode 600 were verified; root-created archives
needed a root helper to restrict their file modes. Runtime config and credentials
are included, with archives and protected JSON verification reports.

| Archive | Compressed bytes | SHA-256 |
|---|---:|---|
| Postgres | 6,743,883 | `37695e6ffe36db575f9a92c80d406fd9bb40ca93ecb11a908d016ed07d0c686e` |
| Garage metadata | 75,402 | `4c7b02ae511377b219dc23f170ea7c93e16b164615015e1d2647e1acf6c574ed` |
| Garage data | 1,393,413 | `235e619094b54d35aed9ff0d9e9af7eade7543e25699e448b04c7e6621e6199e` |

Application image was the deployed `f25279675d7e…` image, with recorded Garage
v1.0.1/Postgres 16 digests unchanged. Fetcher was stopped first; direct database
and S3 reads recorded the baseline without modifying access metadata. Then the
remaining application and both backends stopped gracefully for volume archives.
The original stack restarted before isolated restoration.

Restored tables matched sorted full-row SHA-256 fingerprints and counts:
6 assets, 8 aliases, 47 audit events, 2 bucket quotas, 3 partition quotas,
0 alias tombstones and 1 Alembic version row. Matching full rows include lifecycle,
annotations, alias bindings, quota values and migration revision. All 6 available/
expired retained payloads passed direct Garage size and canonical SHA-256 checks:
2,052,400 bytes total. No user payload was purged or regenerated.

Network/volume inspection confirmed every restored backend/application container
used only `asset-store-restore-20261005_default` and restore-prefixed named volumes.
Both original and restored APIs passed readiness. Authenticated WebP smoke on
18101 and 18001 returned 655,296 bytes, checksum
`c5a299d6b8a05253e4eb072e016b9be2ac6c8cd7711ec2b4ce352c75ebef88bf`,
with initial cache hit and repeat preload hit. Before those smoke requests, the
original pilot's full table fingerprints and retained bytes also matched baseline.
Smoke requests subsequently produce normal audit/access updates.

Two procedure errors were corrected: the first checksum comparison omitted the
registry's `sha256:` prefix, and rendered Compose configuration inherited the
pilot network name. The initial precheck aborted before archive creation and
restarted fetcher; its protected config-only directory is retained separately.
The restore was stopped and every restore container recreated on a dedicated
network before accepted evidence was collected. Initial restore startup on the
shared network is not counted as isolated evidence. Original metadata equality
was confirmed afterward. Future procedures must rewrite network names before up.

Final state: original pilot's four services healthy; restore services stopped,
restore volumes and snapshot retained; scheduled cleanup disabled. No release
sign-off. Daily scheduling, approved encrypted off-host backup destination,
retention/deletion policy, recovery timing targets and application rollback remain
open. This rehearsal proves recovery of this small snapshot on this host using
identical backend versions, not host-loss resilience or PITR.
