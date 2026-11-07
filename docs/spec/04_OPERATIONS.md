# 04 — Pilot operations and verification

**M-002, 2026-11-07.** Operations support the three releases in
[the plan](../WORKPLAN.md). The old Swarm/HA/SLO and comprehensive fault programme
is deferred, not passed. These are requirements for future implementation, not
new installed monitoring, backups or jobs.

## Deployment

Use one host/Compose with collection API/admin, Postgres, the existing S3 approach,
and the selected IIIF Image server. The Gallica proxy can initially be another
module in the app. Publish only intended service routes; keep database/backend
administration and credentials private. Document browser and worker reachable
base URLs/CORS, disk/resource limits and startup/restart for the actual host.
Do not assume the protected old pilot deployment exists on a new machine.

Restricted admin writes use configured operator credentials; no end-user identity
platform is required. Use TLS for remote secret-bearing/admin access. Published
test content is deliberately public; draft/unpublished routes must be inaccessible,
including image-server routes. Unpublication cannot recall downloaded copies or
previously issued links; document cache invalidation/expiry behavior.

## Data protection

- Raw uploaded files are retained and immutable; separately store disposable image
  derivatives and proxy responses. Do not put collections under legacy cache TTL
  or pressure eviction. Import failure may clean only its own unpublished artifacts.
- Preserve metadata and matching raw files in a documented coherent backup.
  Before R2 shared use, restore the chosen collection in isolation and verify its
  metadata/order/checksums. Same-host copies do not establish disaster recovery.
- Existing runtime data, private reports/configuration, original test observations,
  untracked owner images and migration history are preserved. No pivot cleanup or
  host/network/fault execution is implicit.
- Review applicable known findings in the [security closeout](../security/B018_CLOSEOUT.md)
  for the code/images/routes actually reused. The pivot neither closes findings
  nor demands completion of every legacy platform goal before any implementation.

## Minimal signals

| Path | Operator must see | Acceptance |
|---|---|---|
| Import/publication | Item status/error, imported bytes/count, dimensions/checksum, duration, publication changes and operator credential identity | Diagnose interrupted/invalid import; retry remaining items; no partial published content. |
| IIIF/local processing | Image route failures/latency, storage or transform errors, actual input representation and dimensions | Explain a UI failure and correlate a real processing input/export. |
| Gallica proxy | Cache hit/miss, origin request/429/error, bytes/duration, inflight work, local overload and upstream backoff | Distinguish local overload from BnF throttling and verify recovery/cache reuse. |
| Storage/runtime | Health, disk use, backend/DB failures and resource bounds | Saturation is explicit; no silent data loss, unbounded queue or repeated uncontrolled origin work. |

Use existing JSON logging/metrics patterns; specify concrete metric names with the
implementation. IDs belong in logs, not unbounded metric labels. Never log admin
credentials, signed URL tokens, API keys or upstream credential-bearing queries.
Full tracing, dashboards, per-user billing and a new audit platform are deferred.

## Release checks

1. **R1:** import a representative approved collection and invalid/interrupted
   items; verify restricted writes, path safety, finite limits, unpublished access
   denial, repeat import behavior, checksums and reopen/restart persistence.
2. **R2:** validate chosen-version manifests/image information; exercise actual
   Corpusense browsing/import and existing real worker input access; verify browser
   disconnect/reconnect does not cancel the job and results remain retrievable; verify one
   source-coordinate mapping and an isolated metadata/raw-data restore.
3. **R3:** use isolated origin fixtures for misses/hits, different renditions,
   redirects/unsafe destinations, 429/timeout/partial-body/storage failure and
   healthy follow-up. Verify released resources, prior-cache preservation, finite
   upstream demand, freshness and key redaction. Perform a bounded real UI smoke
   with the approved BnF configuration; never inject faults into real BnF.

Tests accompany changed behavior; run relevant CI checks in implementation work.
Documentation-only changes need link/consistency checks, not application workloads.
Do not start a new soak, benchmark or broad randomized harness solely because it
was required in the previous plan. Larger failure/scale/security certification is
tracked separately; selected releases still need honest, bounded failure evidence.

## Release record

For each increment record source/image identity, host/configured limits (no secrets),
corpus/formats, measured outcomes, errors, operator instructions, rollback and
remaining limitations. Do not inherit old “542 tests” or cache soak results as
collection/IIIF acceptance. Prototype public access is not production approval.
