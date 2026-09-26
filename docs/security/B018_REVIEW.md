# B-018 — prototype security review

**Reviewed:** `9640116` (2026-09-26), including B-013 (`8d88b94`).
**Verdict:** suitable only for isolated development with trusted operators;
**not ready for wider exposure**. The review is performed; remediation and release
sign-off remain open. No finding is accepted on the owner's behalf. Application
code and dependencies were not changed during this review.

## Scope and evidence

Reviewed the FastAPI control/data/admin routes, service identities, capabilities,
registry transactions, S3 adapter interactions, fetcher HTTP/rules, admin frontend,
Compose/Docker configuration and CI. Requirements: FR-010..015, FR-022,
FR-040..042, FR-050..053, FR-064..069 and NFR-007..009.

- [Recorded probe results](B018_EVIDENCE.json): HTTP tests with configured
  non-default credentials, disposable memory fixtures, an isolated Postgres
  schema and one uniquely named Garage object. Schema/object removed afterward.
- [Repeatable probes](../../tools/security-review/reproduce_b018.py) require
  explicitly configured loopback Postgres/Garage endpoints. They demonstrate
  current findings, **not** a security pass/fail regression suite. See reproduction below.
- 3,600 generated scope/operation/expiry/path checks passed: sibling partitions,
  similar prefixes, wrong buckets/verbs, deadline equality, dot and empty segments.
  This is bounded generated testing, not exhaustive fuzzing;
  [generator](../../tools/security-review/check_scopes.py).
- Runtime dependencies plus `s3`/`pg` extras were exported from `uv.lock` and
  checked using `pip-audit`'s live advisory database. See SEC-09.
- The review reran **90 authorization/admin/fetcher tests**, all passed with
  no skips (one existing Starlette/httpx deprecation warning).
- The latest complete application suite had 326 passing tests. Passing functional
  tests do not establish security: the probes below exercise missing assertions.
- Limits: no external penetration test, live DNS-rebinding exploit, deployed TLS
  inspection, image/OS CVE scan, full Git-history secret scan or browser DOM test.
  No browser is connected. Findings labeled static/inference are not exploit claims.

## Findings, in remediation order

| ID | Severity / evidence | Finding | Required closure |
|---|---|---|---|
| SEC-01 | **High · reproduced** | Unauthenticated reserve, commit and resolve bypass the guard; commit trusts supplied metadata and actor | Authenticate and authorize all registry routes; derive actors; verify bytes server-side |
| SEC-02 | **High · reproduced** | Requests share one Postgres transaction context; a rollback can erase another acknowledged mutation | Connection per request/unit of work, or complete serialization; concurrent HTTP regression tests |
| SEC-03 | **High if reachable · reproduced/static** | Predictable dev credentials remain the default; no enforced deployment/TLS posture | Explicit dev opt-in; fail closed elsewhere; configured secrets and TLS termination |
| SEC-04 | **High if reachable · reproduced** | Unauthenticated fetcher acts using its privileged service credential and caller-selected tmp namespace | Authenticate callers and authorize destination scopes; ingress limits |
| SEC-05 | **High with attacker-controlled origins · static + unit probe** | SSRF validation is not bound to the connected address and misses shared non-global space | Bind validation to transport/egress policy; reject non-public destinations at every hop |
| SEC-06 | **High for resource abuse · reproduced/static** | Rejected uploads retain unaccounted bytes; request bodies/capability stores have no application bound | Bound/stream bodies, reserve capacity, clean failed writes, rate-limit and expire token state |
| SEC-07 | **Medium · reproduced** | Audit stores the live bearer credential as `capability_id` | Separate public audit identifier from secret; redact errors and retention/export paths |
| SEC-08 | **Medium · real Garage reproduction** | Expiry/deletion does not revoke already-issued presigned GETs immediately | Explicit revocation contract; strict-revocation reads through proxy; bounded URL lifetimes |
| SEC-09 | **Medium project priority · scanner + upstream advisories** | Locked AnyIO has three known advisories; image installation ignores the lock | Update/retest the lock; scan locked dependencies and actual images in CI |
| SEC-10 | **Medium · static** | Capability/single-use state is process-local and never retired; single-use check/use is not atomic | Define replica/restart/revocation semantics and atomic consumption before scaling |

Severity assumes an untrusted caller can reach the relevant interface or obtain a
limited service capability. Checked-in Compose publishes ports on loopback; this
reduces current exposure and is **not** evidence of an internet-exposed deployment.

### SEC-01 — unauthenticated control plane and forged commits

[API routes](../../src/asset_store_core/api/app.py#L157) accept `POST /assets`,
`POST /assets/{id}/commit` and `GET /resolve` without a credential. Bodies supply
`owner_service_id` / `caller_service_id`; the raw commit calls the registry rather
than checking S3. Configuring real service credentials does not close these paths.

**Observed:** no Authorization header; reserve in `users/victim` returned 201,
commit with zero bytes and checksum `invented` returned 200, resolve returned an
`available` asset and its metadata, and audit attributed the commit to `admin`.
No payload was uploaded. This allows alias occupation, fabricated metadata/quota
accounting and actor spoofing; resolve exposes metadata across tenants. It does
not, by itself, make guarded GET return real bytes that were never stored.

Authentication alone is insufficient: validate service→bucket and prefix/asset
ownership on each operation, and derive commit size/checksum from stored bytes.
Update the fetcher client's currently unauthenticated resolve call as part of this
change. Add negative tests for anonymous calls, spoofed actors, cross-bucket writes,
foreign reservations and missing/mismatched payloads. Existing R-012 (upstream
user→prefix trust) remains even after authenticating services.

### SEC-02 — shared connection crosses transaction boundaries

The [Postgres adapter](../../src/asset_store_core/pg_registry.py#L172) holds one
connection; the app captures one registry for all requests. Synchronous endpoints
can run concurrently. Nested `connection.transaction()` blocks on that connection
are savepoints in the same transaction, not independent request transactions.

**Observed on Postgres:** thread A opened an asset-lock transaction and waited;
thread B updated a different asset and returned successfully; A then rolled back.
B's acknowledged annotation disappeared. The probe deliberately orders operations
at adapter level; an HTTP timing exploit was not attempted. App wiring makes this
an actual integration risk, despite the adapter documenting that it is not thread-safe.
Row locks across *different connections* do not fix shared-connection coupling.

Use a request-scoped connection/transaction from a pool, or serialize the entire
unit of work across every entry point as an interim single-instance limitation.
Acceptance must show one request's rollback cannot erase another request's state,
audit or quota updates. The in-memory adapter has similar unsupported concurrency
assumptions and must remain a test/development adapter.

### SEC-03 — dev defaults are not a deployment security mode

[Service credentials](../../src/asset_store_core/service_identity.py) fall back to
`dev-secret:<id>` when unset. A default app accepted the known admin credential
and returned admin listings (200). [Compose](../../deploy/compose/docker-compose.yml)
intentionally includes fixed development database/S3 credentials and plain HTTP;
[the image](../../deploy/Dockerfile) listens on all container interfaces.

The fixed values are documented development fixtures, not evidence of leaked
production secrets. Nevertheless there is no non-development startup check,
required secret-provider configuration, TLS termination manifest, rotation overlap,
or verified least-privilege database/S3 role split. Do not reuse these defaults in
staging. Require an explicit development mode, fail closed without configured
credentials otherwise, and exercise secret rotation and proxy/TLS deployment.

### SEC-04 / SEC-05 — fetcher trust and SSRF boundaries

[ensure-url](../../src/fetcher_service/app.py#L139) has no caller-authentication
dependency. It mints capabilities using the configured fetcher identity and accepts
caller-selected `tmp_id` / alias suffix. A request without credentials created
`tmp/victim/chosen` (synthetic origin bytes in the probe). A reachable caller can
occupy another workflow's chosen tmp alias or drive fetch/storage work. Prefix
scoping inside asset-store does not identify the original fetcher caller.

[HTTP validation](../../src/fetcher_service/fetcher.py#L93) resolves the hostname,
checks addresses, then sends the original hostname to HTTPX. The mocked transport
probe confirmed the hostname remains unpinned; no live private host was contacted.
The code itself documents this DNS-rebinding gap. `100.64.0.1` also passed the
address predicate even though `ipaddress.is_global` is false. Redirect validation
and private/loopback rejection are useful existing controls, but not a complete
egress boundary. Environment-provided HTTP proxies and the explicit
`FETCHER_ALLOW_PRIVATE_HOSTS` override must be included in the threat model.

Authenticate inbound callers, authorize destination partitions, pin/validate the
actual connection destination while preserving TLS hostname verification, and
apply an independent egress policy. Test rebinding, proxy behavior, redirect chains,
IPv4/IPv6 special ranges and cloud metadata destinations in isolated fixtures.

### SEC-06 — resource limits do not cover failed uploads

[Uploads](../../src/asset_store_core/api/app.py#L377) read the whole body before
scope/expiry checks inside the guard. [The guard](../../src/asset_store_core/guard.py#L194)
reserves and writes bytes before commit enforces quota. A failed commit leaves the
object behind; pending metadata does not record those bytes in physical capacity
estimates. B-014 eventually removes old pending objects, but is not a synchronous
resource bound and must be scheduled separately.

**Observed:** a valid results capability with a zero-byte partition quota uploaded
11 fixture bytes. HTTP returned 413, but S3-seam bytes remained; registry state
was `pending` with `size_bytes=null`. No huge body or exhaustion attack was run.
Minted capabilities accumulate in an unbounded dictionary; the consumed-token
ledger also has no expiry cleanup. Fetcher per-body limits do not cap total request
concurrency or elapsed transfer time. Add streaming limits and admission control,
failed-upload cleanup with retry tracking, issuance rates and token garbage collection.

### SEC-07 / SEC-08 — bearer secrecy and revocation semantics

The capability ID returned by [mint](../../src/asset_store_core/api/app.py#L350)
is the token accepted by `Authorization: Capability …`. It is copied into audit
`after.capability_id`; the probe confirmed exact equality without recording the
secret. The operations spec's instruction to replace tokens with capability IDs
does not redact this implementation. Admin audit access is protected, so this is
not a new anonymous leak, but exports/backups/log-reader access can expose live grants.
Use a distinct non-secret identifier or digest; do not log/store the bearer as an identifier.

**Observed on Garage:** mint a 60-second GET, expire the asset in the registry,
then GET the previously issued URL: 200 with the original bytes. The guard caps
new URLs by known asset/capability deadlines, but cannot retroactively shorten an
issued URL after an admin action. Delete is asynchronous, so the same window can
exist until physical cleanup. The configured maximum URL TTL is one hour, default
five minutes. Operator docs now distinguish denial of new guarded reads from old
URLs; console wording and the final strict-revocation contract still need work.

### SEC-09 — dependency and build evidence

The runtime/extras lock scan reported **3 advisories in `anyio==4.14.1`**. All list
**4.14.2** as patched. Primary upstream references:

- [CVE-2026-63374 / GHSA-82r6-8w77-94w6](https://github.com/agronholm/anyio/security/advisories/GHSA-82r6-8w77-94w6): TLS hostname handling for internationalized names.
- [CVE-2026-64847 / GHSA-5p39-cfhj-2xmp](https://github.com/agronholm/anyio/security/advisories/GHSA-5p39-cfhj-2xmp): process-pool stderr can block workers.
- [CVE-2026-63349 / GHSA-3w57-8xmc-8v26](https://github.com/agronholm/anyio/security/advisories/GHSA-3w57-8xmc-8v26): subprocess supplementary-group handling.

The upstream TLS advisory is rated Critical; the project's exploitability is
**not demonstrated**. Source search found no direct use of these AnyIO APIs;
outbound clients here are synchronous HTTPX. This reduces evidence of current
reachability, not the need to update the vulnerable lock. The two process-related
features were not found in application code.

Docker uses `pip install .[s3,pg]` without `uv.lock`, so scanning the lock does not
certify an image built from it. CI has no dependency/image/SAST security jobs.
Upgrade within compatible constraints, run the suite, build from the lock and scan
the resulting image and its OS packages. No dependencies were updated in this review.

### SEC-10 and additional hardening

[Capabilities and single-use ledger](../../src/asset_store_core/capabilities.py)
are process-local; restart loses grants, replicas disagree, and checking a grant
then consuming it after a side effect is not atomic. No concurrent duplicate-write
HTTP exploit is claimed: current proxied writes run synchronously inside an async
endpoint. This assumption must not become a security guarantee when execution is
parallelized. Define atomic use/reservation and shared state or a deliberate
single-instance restriction before scaling.

Other follow-ups: no durable audit of failed service authentication; no per-human
admin actor; correlation IDs are accepted without bounded/encoding validation;
fetcher errors can include origin URLs; operator regex validation permits nested
quantifiers despite claiming a safe subset (acceptance reproduced, no CPU stress
test). Treat regex files as trusted and add bounded matching/input limits. These
are hardening gaps, not extra confirmed remote exploits.

## STRIDE map and controls that held

| Threat | Boundary / findings | Existing control |
|---|---|---|
| Spoofing | Anonymous control plane/fetcher; dev credentials (01/03/04) | Configured service secrets and protected admin routes reject wrong identities |
| Tampering | Forged commit; coupled transactions (01/02) | Guarded writes compute server-side checksum; immutable aliases and row locks exist |
| Repudiation | Body-supplied actors; shared admin identity (01/07) | Transactional audit for normal mutations; before/after quota/TTL history |
| Information disclosure | Anonymous metadata; audit bearer; old signed URLs (01/07/08) | Path-segment scoping, bucket allowlists, bounded presign TTL; admin CSP/text rendering |
| Denial of service | Upload/token growth, failed bytes, regex configuration (06/10) | Fetcher body/redirect/per-read timeout limits; eventual pending cleanup |
| Elevation of privilege | Fetcher deputy, upstream user→prefix trust, SSRF (04/05, R-012) | Capability operation/expiry checks; private-host and redirect validation |

## Remediation sequence / closure criteria

1. **Close SEC-01 first**, including server-verified commits and caller integration.
2. Isolate Postgres transactions (SEC-02); add a controlled concurrent-request test.
3. Enforce explicit deployment secrets/TLS and fetcher caller/egress boundaries
   (SEC-03..05); preserve loopback-only development defaults behind explicit opt-in.
4. Bound and clean upload/token resources (SEC-06/10), redact bearer identifiers
   (SEC-07), and decide the signed-URL revocation contract (SEC-08).
5. Update/retest dependencies and add reproducible image/security scans (SEC-09).

Each fix needs a negative regression test proving the formerly permitted behavior
is rejected or safely bounded, plus relevant metrics/audit. Until fixes or explicit
owner acceptance are recorded, B-018's **readiness exit criterion is open**.

## Reproduction

With local test backends and their development credentials configured:

```bash
set -a
source deploy/compose/.env.garage
set +a
export ASSET_STORE_PG_DSN=postgresql://asset:asset@127.0.0.1:5432/asset_store
PYTHONPATH=src uv run --locked python tools/security-review/reproduce_b018.py
```

The probe refuses non-loopback endpoints, does not send an origin request, prints
no credentials/signed URLs, and cleans its isolated backend fixtures in `finally`.
Its temporary fixed credentials exist only in injected in-memory app instances.
After remediation, observations should change; convert each into an assertion of
the secure behavior in the normal test suite.

Dependency scan used:

```bash
uv export --locked --no-dev --extra s3 --extra pg --no-emit-project --no-hashes \
  --format requirements-txt --output-file /tmp/asset-store-audit-requirements.txt
uvx pip-audit --disable-pip --no-deps -r /tmp/asset-store-audit-requirements.txt \
  --format json --output /tmp/asset-store-dependency-audit.json
```

This audits the exported runtime set under the review interpreter's markers, not
all operating systems, developer tools or container packages. Exit 1 indicated
reported advisories, not an incomplete scan. Dependency names/versions were sent
to the advisory service; application code and credentials were not.
