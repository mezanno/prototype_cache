# M-001 task 4 — security scans and application rollback

B-018/B-019, SEC-09/R-020, NFR-005; M-001/P5. Owner authorized execution
2026-10-06. Browser recheck and task-5 corpus/soak remain separate.

## Reviewed rehearsal procedure

Compare image migration/lock/runtime inventories before using the retained prior
image. Current schema is 0003; both images have identical migration files, lock
and 33 runtime packages. No schema downgrade is needed or allowed for this pair.

Pause lifecycle while comparing retained objects/metadata. Verify current cached
WebP bytes before any preload so cache absence aborts without origin ingestion.
Record metadata/alias/quota/schema fingerprints, existing audit history and every
retained payload SHA-256. Recreate only asset-store/fetcher at the prior immutable
image; wait for each API's readiness, verify cached HTTP reads and repeat preload
hits, compare retained metadata/bytes, then return to the current immutable image
and repeat. Recovery must return to current image even if prior acceptance fails.
Resume lifecycle, preserving backend containers/volumes and protected config.
The prior image lacks the reviewed admin disconnect fix; avoid admin interaction
while temporarily running it. Both images carry the same scanned dependencies;
rollback is recovery evidence, not vulnerability remediation.

Current image: `sha256:f25279675d7e78c02eba46621452eebd148572a6584e1179e094af81a7468fff`.
Prior image: `sha256:cf5736cb6147c223c13760945c76e593cc71213412ab6f3ce154f280e4fae2d7`.

## Scan execution and findings — 2026-10-06

Trivy 0.75.0 official Linux release archive checksum verified:
`c6e65abddb348e25f10549df887045629cf28cc72453cd1c63acb717316b3f3f`.
Database updated 2026-10-06 19:11:49 UTC. Scans use exact local image identities
with `--image-src docker --scanners vuln`, no registry substitutions and no
secret/config scanner over protected runtime files. Exact installed app packages
were independently audited with pip-audit 2.10.1, not host interpreter marker
selection. Sanitized [all finding rows](security/TASK4_SCAN_EVIDENCE.json) include
report checksums, versions and fixed-version suggestions; full raw reports are
retained mode 600 under ignored `deploy/pilot/private/task4-scans/`.
Temporary scanner binaries/caches created by this task were removed after review.

Counts below are package/advisory rows, not unique CVEs or demonstrated exploits.

| Target/inventory | Critical | High | Medium | Low | Unknown |
|---|---:|---:|---:|---:|---:|
| Current app Debian packages | 0 | 51 | 85 | 67 | 2 |
| Current app Python (system + venv) | 0 | 2 | 7 | 1 | 0 |
| Previous app | Same findings as current app | | | | |
| Postgres Debian packages | 1 | 68 | 126 | 138 | 6 |
| Postgres bundled gosu Go inventory | 1 | 21 | 21 | 2 | 1 |
| Garage image | Inconclusive: no OS/package inventory detected | | | | |
| Garage official v1.0.1 source lock supplement | 0 | 7 | 8 | 13 | 0 |

### Reviewed remediation priorities (not accepted risks)

1. **App runtime:** both Trivy and pip-audit identify three urllib3 2.7.0
   vulnerabilities; suggested fix 2.8.0. High: CVE-2026-97687 (HTTPS proxy TLS
   configuration), CVE-2026-97689 (unbounded streaming chunk-header buffer);
   Medium: CVE-2026-97688 (deflate streaming loop). Official maintainer
   [proxy advisory](https://github.com/urllib3/urllib3/security/advisories/GHSA-8988-9cw3-xx77)
   and [streaming advisory](https://github.com/urllib3/urllib3/security/advisories/GHSA-vxq7-64xx-v4gw)
   confirm affected versions below 2.8.0. Fetcher uses httpx/httpcore for origins;
   urllib3 is used by the S3 client talking to private Garage. This reduces the
   public-origin exposure of those paths but is not proof of non-exploitability.
   Update the lock with a reviewed dependency slice, run Garage/read/ingest
   regressions, rebuild/rescan/redeploy an immutable app before closing SEC-09.
2. **App/base image:** refresh tested base OS packages, remove unused build tools
   where practical, rescan. Trivy also flags Mako (suggested 1.4.2) and base-image
   pip (suggested 26.2.0); pip-audit of the 33-package app venv only reports urllib3.
   The inventories/databases differ; these results are not contradictory and
   base interpreter packages are not silently excluded. Reported OS fixes include
   libpcre2 and OpenSSL; findings without vendor fixes remain visible.
3. **Postgres image:** two Critical rows are CVE-2026-6653 in libxml2 (no fixed
   version supplied by the scanner) and CVE-2025-68121 in gosu's bundled Go stdlib.
   The latter describes TLS session resumption; presence in a privilege-switching
   helper does not establish that affected TLS code is exercised. XML reachability
   and helper reachability need explicit review; no risk is waived. Select a
   patched Postgres-16 image, certify isolated restore/compatibility, then review
   any backend image update separately. No backend upgrade occurred here.
4. **Garage coverage:** image scan returns zero results because inventory was not
   detected, not because security is certified. Supplementary scan of the official
   [v1.0.1 Cargo.lock](https://raw.githubusercontent.com/deuxfleurs-org/garage/v1.0.1/Cargo.lock)
   reports High entries in aws-smithy-json, mio, parse_duration, rustls and
   rustls-webpki. Source-lock packages/features are not attested deployed binary
   contents. Obtain build SBOM/provenance or evaluate a supported patched release
   in an isolated storage migration/certification task; do not relabel the image clean.

Security release and R-020 remain open. No public exposure or wider pilot go/no-go
is approved by this review. Application rollback does not remedy dependencies.

## Executed rollback evidence

[Sanitized rehearsal record](TASK4_ROLLBACK_EVIDENCE.json) and private original
`deploy/pilot/private/task4-rollback.json` capture three successful checkpoints:
current before, previous rollback, current return. Total procedure: **31.2 seconds**
(includes checks; not a measured user-visible outage duration).

Each checkpoint downloaded the existing WebP and passed repeated cache-hit smoke:
655,296 bytes, SHA-256
`c5a299d6b8a05253e4eb072e016b9be2ac6c8cd7711ec2b4ce352c75ebef88bf`.
Outbound origin connection counters did not change during repeated smoke. Actual
container image IDs match the expected current/previous/current sequence.

All **6 retained payloads, 2,052,400 bytes** match sizes/checksums under old and
returned-current apps. Stable asset metadata/lifecycle/deadlines, 8 aliases,
2 bucket quotas, 3 partition quotas, tombstones and Alembic revision fingerprints
match. Existing audit rows through id 48 match unchanged; normal issuance/access
work appended audit rows (48 → 50 → 51). Read counters/access timestamps and
updated-at are excluded from stable asset fingerprints because HTTP acceptance
updates them normally. No requirement to suppress legitimate access telemetry.

Garage/Postgres container IDs remained unchanged. Their image versions, persistent
volumes, schema, protected configuration and backup copies were not changed.
Lifecycle was stopped during comparisons and resumed with zero-candidate/error
sweeps. Final APIs/backends healthy; manual monitor snapshot reported no alerts.
Per-minute monitor may observe the planned outage; no signal was suppressed.

One read-only precheck used an unsupported streaming method on the response type;
it stopped before rollback and was corrected to bounded `.read()` calls. It made
no registry mutations; accepted evidence comes from the corrected probe/rehearsal.

## Operator rollback runbook

Use the existing `pilot()` helper from deploy/pilot/README.md. Record the deployed
image and schema first; confirm selected old image is present and migrations
compatible. A schema mismatch stops this procedure: never downgrade automatically.
Use retained task-2 backup for recovery planning, without deleting or overwriting
pilot volumes. Quiesce other testers/writers during maintenance.

For this certified pair only, use shell process environment overrides; no editing
of protected pilot.env is needed:

```bash
pilot stop lifecycle
pilot stop fetcher asset-store
PILOT_APP_IMAGE=sha256:cf5736cb6147c223c13760945c76e593cc71213412ab6f3ce154f280e4fae2d7 pilot up -d --no-deps --force-recreate asset-store
# Wait for asset-store /readyz, then:
PILOT_APP_IMAGE=sha256:cf5736cb6147c223c13760945c76e593cc71213412ab6f3ce154f280e4fae2d7 pilot up -d --no-deps --force-recreate fetcher
# Wait for fetcher /readyz; verify cached reads/checksums with provisioned credentials.
```

Return even if old-image checks fail: stop fetcher/asset-store, recreate asset-store
with the current image (or the unchanged pilot.env default), wait ready, recreate
fetcher, wait ready, and verify cache bytes/metadata. Then run
`pilot --profile maintenance up -d --no-deps lifecycle` and check fresh worker
metrics/logs and monitor JSON. Keep schema/backend versions unchanged. Reusable
capabilities are reminted after API restart; single-use semantics remain deferred.
The previous UI lacks the disconnect fix and must not be left as the final image.

## Task boundary

Task-4 scan/review and rollback rehearsal are performed. Vulnerability remediation,
Garage build coverage and security release approval remain open. No product code
or backend image changes. Owner approved the evidence commit and resumed task 5;
no push. Browser acceptance remains pending in CLI.

Validation: **40 focused smoke/migration/pilot tests passed**, none skipped, using
separate development Garage/Postgres; two existing upstream deprecation warnings.
Ruff lint/format, strict mypy (88 files), whitespace checks, evidence JSON parsing
and retained raw-report checksum verification passed. No product code changed;
full 525-test suite was already green at the preceding task-3 checkpoint.
Compatibility inventories are included in the sanitized rollback record.
