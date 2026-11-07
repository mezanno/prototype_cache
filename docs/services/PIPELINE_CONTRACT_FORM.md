> **Superseded integration form.** The [active workplan](../WORKPLAN.md) and [collection contract](collections-service.md) replace this six-section form and its pause/authorization/next-task instructions. Keep the current job system unchanged; obtain only the real UI/job examples needed for integration. This body remains historical context, not a requirement to adopt aliases/capabilities or implement a new pipeline.

# First pipeline integration — owner review form

Created 2026-10-12. **Status: awaiting owner answers; proposals are not decisions.**
Purpose: define the first real pipeline sufficiently to implement correlated
observability, operator guidance and bounded failure acceptance before integration.
Processing and task orchestration remain outside asset-store.

**How to fill:** replace every `ANSWER:` placeholder. For proposals, write
`Accept` or describe the change. Rough estimates and `Unknown` are useful;
existing payload examples can replace prose. Do not paste credentials, capability
tokens, signed URLs or personal data. No need to design future pipelines.

## Existing rules to retain

- An **alias** is a logical file name; workers use aliases, never S3 object keys.
  Inputs include a trusted SHA-256 checksum, verified after download (SCN-002).
- A **capability** is short-lived read/write permission for an alias prefix.
  Service credentials identify callers; workers have a distinct identity (FR-010–015).
- Results live under `results/{user-or-anon}/{task}/{attempt}/{worker}/`.
  An **attempt** is one execution of a job, including a fresh execution after failure.
- Outputs commit individually. Publish `manifest.json` last as the completion
  marker; this is not an atomic bundle. Failed runs may leave partial outputs.
  A lost upload response can hide a successful commit; inspect before retrying.
- Pilot reads are cache-only: a miss returns 404 without contacting the origin.
  Explicit preload fetches/stores content; changed forced refetch returns 409.

Sources: [worker protocol](worker-sim.md), [fetcher contract](fetcher-service.md),
[SCN-002/005/007/009](../spec/01_SCOPE.md),
[FR-010–015/022/050–052/069](../spec/02_REQUIREMENTS.md).

## 1. One real job and its components

**Background:** the dispatcher prepares inputs and starts work; the processor
performs your actual computation. The current worker simulator only copies bytes.
The diagram is a proposed first flow, not a new service design.

```mermaid
flowchart LR
    Submit[Job submission] --> Dispatch[Existing dispatcher]
    Dispatch --> Preload[Fetcher: explicit preload]
    Preload --> Store[Asset-store: input aliases]
    Dispatch --> Worker[Existing processing worker]
    Store -->|Verified inputs| Worker
    Worker -->|Outputs then manifest| Results[Asset-store: results]
    Results --> Consumer[Result consumer]
```

**Question:** what is the first real job, who submits/dispatches/processes it,
and who consumes its results? Include component names and how work reaches the
worker (HTTP, queue, CLI, etc.). Existing documentation links are welcome.

**ANSWER:** _Job example; component names; dispatch mechanism; consumer._

## 2. Input and output payload

**Background:** the simulator accepts `inputs: [{alias, checksum}]` and
`result_prefix`. The real worker additionally needs processing instructions.
Its result manifest currently lists output alias, asset id, size and checksum
([schema and example](worker-sim.md)).

**Proposal:** dispatcher preloads all required remote inputs before dispatch,
resolves their checksums, and supplies aliases/checksums plus processing options.
Keep scoped result prefixes and manifest-last publication. Describe the external
task envelope separately; the current simulator rejects unknown fields.

**Question:** what operation/options does the worker need, and what artifacts
must exist for this job to count as successful? Are partial input successes useful?

**ANSWER:** _Accept/change proposal; sanitized task example or fields; required
outputs and formats; whether all inputs are required._

## 3. Job identity and correlation

**Background:** a **job id** persists across retries; an **attempt id** distinguishes
executions; a **correlation id** links logs across HTTP calls. Current service
requests support `X-Correlation-Id`; the simulator creates one per run, but the
whole preload-to-processing chain is not defined ([operations](../spec/04_OPERATIONS.md)).

**Proposal:** dispatcher owns job/attempt ids and result prefixes. Carry job and
attempt context through dispatch; propagate an attempt correlation id through
internal calls. Keep unique ids in logs/reports, not Prometheus metric labels
(each unique label creates another stored time series).

**Question:** do your components already create these ids or use a tracing convention?

**ANSWER:** _Accept/change proposal; existing id fields/creator and conventions._

## 4. Permissions and long jobs

**Background:** the simulator mints one-hour capabilities using its worker service
identity. Real dispatch and capability refresh are deferred. User authentication
and mapping a user to an authorized prefix belong upstream of asset-store.

**Proposal:** retain the trusted-service pilot boundary and distinct worker
credential. Inputs and result access stay narrowly scoped. Decide capability
issuance/refresh at the integration boundary; do not put service secrets in tasks.

**Question:** will workers mint capabilities or receive them from the dispatcher?
Who renews them, and can jobs run longer than an hour? Does the first integration
stay within trusted testers/public content?

**ANSWER:** _Issuance/renewal owner; expected longest job; trusted/public boundary
or intended change. No secret values._

## 5. Completion, retries and cancellation

**Background:** a manifest means one worker's outputs committed, not necessarily
that the whole job finished. Current simulator failures stop execution, retain
partial outputs and require a new attempt prefix. No automatic write retries.
Fetcher upstream failures map to 502; timeouts to 504. Admission overload is
503 with retry guidance; rate admission can return 429. These do not define an
end-to-end job retry policy ([worker](worker-sim.md), [fetcher](fetcher-service.md)).

**Proposal:** dispatcher owns job status and retry decisions. Before treating an
ambiguous final upload as failure, inspect the manifest. Bound retries/deadlines;
do not blindly retry writes or overwrite immutable aliases. Cancellation stops
new work; already committed content follows normal retention policy.

**Question:** how is completion reported today (polling, callback, queue ack,
etc.)? Who selects the successful attempt? Specify existing retry limits,
deadlines and cancellation behavior, including any multi-worker aggregation.

**ANSWER:** _Accept/change proposal; completion channel/owner; retry and deadline
rules or Unknown; cancellation; single or multiple workers per job._

## 6. Workload and operator visibility

**Background:** current pilot transfers are capped at 50 MiB per object by default.
The local demo has a shared 64 MiB results budget; this is not a real-workload
capacity promise. Existing acceptance used three URLs/two cached resources.
Processing duration and memory requirements remain unspecified.

**Proposal:** measure retrieval, processing, output upload and manifest publication
separately; report total job time, bytes, failures/retries and overload. Record
resource pressure and distinguish origin failures from local/backend failures.
Logs omit credentials and source URLs. Essential signals reuse existing metrics
and JSON logs; a new dashboard/tracing platform is not required for this slice.

**Question:** estimate typical/maximum inputs per job, input/output sizes, job
duration and simultaneous jobs. Who investigates failures, where can they read
logs/status, and what must they be able to diagnose first?

**ANSWER:** _Workload estimates; operator and available log/status tools;
top diagnostic needs. Unknown values are fine._

## Fixed acceptance scope and deferred choices

The [failure prerequisite](../history/asset-store/WORKPLAN.md#fetcher-fault-injection-acceptance-prerequisite--2026-10-06)
already requires deterministic coverage plus seeded random client, origin,
network/TLS and internal failures. Verify recovery, preserved cached bytes, no
partial available assets, released resources and safe correlated telemetry.
No new origin retry policy is implied. Live injection must be separately approved;
do not disrupt the running pilot, weaken SSRF/TLS or contact real BnF for faults.

Deferred unless answers show a concrete need: atomic bundles (Q-008), broader
capability verbs (Q-032), distributed orchestration, full tracing/dashboards,
read-through caching (B-025), HA and full-scale load certification.

## Session handoff

- **Current task:** owner completes this form; agent then reconciles answers with
  active specs and identifies only consequential remaining ambiguities.
- **Next deliverable:** agreed first-integration contract, bounded telemetry and
  operator-guidance plan, and a failure coverage matrix mapped to existing tests.
  Record accepted major choices in architecture ADRs before implementation.
- **Authorization:** this session authorizes this form and handoff documentation
  only. No runtime changes, implementation, workloads or fault injection.
- Existing operational evidence and release gates remain unchanged. Read the
  newest [workplan checkpoint](../WORKPLAN.md) before resuming; preserve owner
  images under untracked `tmp/` and protected pilot state.
