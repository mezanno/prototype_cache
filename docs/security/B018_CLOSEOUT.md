# B-018 security checkpoint — 2026-09-27

The review and bounded remediation are committed in `acc445e`. **Security
release approval remains open.** The original [review](B018_REVIEW.md) and
[evidence](B018_EVIDENCE.json) describe baseline `9640116`; they are retained as
historical evidence. No outstanding risk has been accepted on the owner's behalf.

Requirements: FR-010..015 (authorization), FR-022 (verified checksum),
FR-050..052 (audit), NFR-008 (scoping). Decision: ADR-022.

## Subsequent remediation — 2026-09-28

**SEC-02 / R-015 is closed:** [pooled transaction isolation and acceptance
evidence](SEC02_TRANSACTION_ISOLATION.md), ADR-023. The original checkpoint validation below remains
historical; the isolation milestone passes 354 tests.

## Subsequent remediation — 2026-09-29

**SEC-05 DNS race is closed in the default transport:** [connection-bound validation
and acceptance evidence](SEC05_OUTBOUND_CONNECTIONS.md), ADR-025. R-017's remaining
origin/destination-policy and deployment boundaries stay open. Next milestone gate
is M-001/P2: resource bounds and failed-upload cleanup.

ADR-026 now bounds process-local capability storage (default 10,000 live tokens),
retires expired bearer/consumed state, and returns retryable 503 on saturation
without evicting live tokens. Audit failure cannot publish a grant. This is a
partial SEC-06/SEC-10 remediation: issuance rate, audit growth, atomic single-use
consumption and replica support remain open.

## Subsequent remediation — 2026-09-30

ADR-027 implements immediate best-effort failed proxy-upload cleanup with
committed deletion fencing, successful-asset preservation, lifecycle retry and
cleanup metrics/logs. ADR-028 adds no-wait aggregate upload/fetch admission and cancellation-safe
thread completion. SEC-06 remains partial: pending-byte accounting and issuance
rate limits are still open. Process termination relies on pending-orphan sweeps.

## Implemented

| Finding | Result at this checkpoint |
|---|---|
| SEC-01 | Raw reserve/commit/resolve require service authentication and bucket authorization. Reservation actor must match the caller; commit requires owner/admin and verifies size/checksum against stored bytes. |
| SEC-03 | Factories fail closed without configured credentials or explicit development opt-in. Unicode secrets reject cleanly; configuration errors do not echo secret values. Deployment TLS/rotation remains open. |
| SEC-04 | Fetcher ingress requires task-api/admin authentication; its asset-store resolve calls authenticate too. End-user destination policy remains the dispatcher's responsibility (R-012). |
| SEC-05 | Fetcher rejects non-global/multicast addresses, including CGNAT, and disables environment proxies. Connection-time DNS validation and numeric dialing are now implemented (ADR-025); see the subsequent evidence above. |
| SEC-06 | Proxy uploads authorize before reading the body and enforce a configurable byte cap for declared and streamed bodies. Failed-write cleanup is implemented (ADR-027); aggregate admission is implemented (ADR-028); pending-byte accounting and issuance rate limits remain open. |
| SEC-07 | New audit records contain a SHA-256 capability fingerprint, not the bearer. Capability errors omit bearer values; correlation IDs are bounded and sanitized. Historical audit rows are not rewritten. |
| SEC-08 | Console and user guide explain that issued signed URLs survive metadata expiry until URL expiry or physical deletion. Strict revocation design remains open. |
| SEC-09 | AnyIO updated to 4.15.1 (minimum 4.14.2); typing-extensions updated where required. Docker installs locked runtime extras using pinned uv 0.12.19. CI checks lock consistency and scans runtime dependencies. Image/OS scanning remains open. |

Existing request metrics and structured logs cover rejected requests; registry
mutation and capability-issuance audit remain active. Fetcher ingress emits
`fetcher_ingress_auth_total` outcomes and structured denial logs without credentials. No database migration is
needed. New fingerprints change the capability audit JSON field from
`capability_id` to `capability_fingerprint`.

## Run and upgrade

- Configure `ASSET_STORE_SERVICE_CREDENTIALS="service-id:secret,..."` on each
  service, including the inbound task-api/admin identity on fetcher. Supply its
  outbound `FETCHER_SERVICE_SECRET` separately. Use independently managed secrets
  and TLS before exposing the services outside local development.
- Local development only: `ASSET_STORE_DEV_MODE=1` enables predictable
  `dev-secret:<id>` values. Development Compose and tests opt in explicitly.
  Explicitly configured weak secrets are not automatically rejected.
- Raw registry calls and fetcher ensure-url calls now require
  `Authorization: Service <id>:<secret>`; unauthenticated legacy callers receive
  401. Service authority is bucket-wide, not an end-user ACL.
- `ASSET_STORE_MAX_UPLOAD_BYTES` defaults to 52,428,800 (50 MiB), must be positive,
  and returns 413 for oversized proxy uploads. This bounds retained request data,
  but is not a total process-memory or concurrency budget. Multipart/resumable
  large-file support remains future work.
- `ASSET_STORE_MAX_CAPABILITIES` defaults to 10,000 and must be a positive integer.
  Saturated issuance returns 503 with `Retry-After: 1`; reuse a live capability
  or retry with backoff after expiry. `asset_store_active_capabilities` reports
  retained live tokens; issuance outcome `capacity_denied` counts overload.
- Restarting invalidates process-local capabilities. Older audit rows/exports may
  contain previously issued bearer values; new redaction does not scrub history.
  Restrict access and define retention/export cleanup before deployment.

## Deferred work, in priority order

| Priority / finding | Required follow-up and acceptance evidence |
|---|---|
| P1 · SEC-06 / R-018 | Fence and reclaim failed uploads, reserve capacity before writes, bound aggregate concurrency and issuance. Test quota rejection, interrupted writes and cleanup races without deleting successful payloads. |
| P0 before exposure · SEC-03/04 / R-012, R-016, R-017 | Define trusted user-to-prefix authorization, deployment TLS, secret rotation and ingress limits; demonstrate unauthorized tenant destinations are rejected at the responsible upstream boundary. |
| P2 · SEC-10 / R-020 | Local token bounds/retirement are implemented (ADR-026). Define replica semantics and atomic single-use consumption. Concurrent replay must permit at most one successful use; expired state must remain bounded. |
| P2 · SEC-07 / R-019 | Decide retention and cleanup of historical audit rows/exports containing bearer values, preserving audit integrity. Verify new exports contain no usable credentials. |
| P2 · SEC-08 / R-019 | Choose signed-URL lifetime versus strict proxy revocation contract, then test expiry/deletion with previously issued URLs. Current behavior is documented, not changed. |
| P2 · SEC-09 / R-020 | Add image/OS scanning and broader interpreter/platform dependency coverage; retain dated reports and remediate findings. Runtime Python scanning is not image certification. |

Browser acceptance for B-013, load/SLO certification, Swarm deployment and
operational readiness remain separate open tasks.

## Validation

- Full suite with local Postgres and Garage: **342 passed, none skipped**.
- Default Docker-free suite: **269 passed, 73 infrastructure tests skipped**.
- 3,600 generated capability scope/operation/expiry/path checks: zero failures.
- Ruff lint/format, strict mypy (68 source files), and whitespace checks pass.
- Patched locked runtime dependency audit: **no known vulnerabilities** on
  2026-09-27, using Python 3.13 marker selection. See
  [sanitized scanner output](B018_PATCHED_DEPENDENCIES.json).
- Container build from the lockfile succeeds on Python 3.12. Startup smoke checks
  verify unconfigured credentials fail closed and explicit dev mode constructs
  the app as non-root. This is not a deployed-stack or image vulnerability scan.

Regression coverage is in `tests/test_security_hardening.py`, the memory/Postgres
commit verification cases in `tests/test_admin.py`, and adapted integration tests.
Two upstream deprecation warnings (Starlette/httpx and AnyIO BlockingPortal) remain;
there are no test failures. Historical exploit probes must run at `14b1f59`, not
against this hardened tree. Current validation uses the regression suite.
