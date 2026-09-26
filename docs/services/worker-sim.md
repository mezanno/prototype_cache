# Worker simulator (B-012)

Implements SCN-002 and SCN-005: guarded reads with checksum verification, followed
by deterministic result writes and a final manifest marker. Requirements:
FR-002, FR-010..015, FR-021/022, FR-050 and NFR-005. ADR-019 defines this slice.

The standalone Click CLI accepts `--task task.json` and `--base-url` (default
`http://localhost:8000`). `WORKER_SIM_SERVICE_SECRET` supplies the worker service
credential; secrets are not accepted in task files or command-line options.
The simulator includes dispatch setup: it mints a read capability per input alias
and, when writing results, a write capability scoped to the supplied result prefix.
Each lasts one hour. Actual task orchestration and capability refresh are deferred.

Task JSON:

```json
{
  "inputs": [
    {"alias": "cache/demo/image.jpg", "checksum": "sha256:<64 lowercase hex digits>"}
  ],
  "result_prefix": "results/42/task-1/attempt-1/worker-1"
}
```

`inputs` must be nonempty. Each alias names an asset within a known bucket and
partition. Checksums come from the trusted task producer. `result_prefix` is
optional: omit it for a read-only SCN-002 run; otherwise it must have exactly the
five components `results/{userid-or-anon}/{task}/{attempt}/{worker}`. Paths must
already be normalized. Unknown JSON fields are rejected.

For each input, the simulator downloads through `GET /objects/{alias}` with its
read capability, computes SHA-256, and checks the task checksum. In write mode it
copies those bytes to `{result_prefix}/output-0001.bin` (one-based input order),
using a guarded PUT with `expected_checksum`. After every output succeeds, it
uploads `{result_prefix}/manifest.json` containing `version: 1` and `outputs`
entries with `source_alias`, `alias`, `asset_id`, `size_bytes`, and `checksum`.
The manifest is the completion marker; it is not an atomic multi-asset transaction.

All errors stop the run. Already committed outputs stay committed; no manifest
is deliberately written after a failure. Use a **new attempt prefix** on retry:
immutable aliases conflict on reuse. A lost response to the final PUT can leave
a committed manifest despite a reported transport failure; inspect the alias
before deciding whether the attempt completed. No automatic write retries.
Missing/expired/denied reads, checksum errors, quota errors and network failures
produce a nonzero exit. Reads are limited to 50 MiB per input for this simulator;
large-object throughput and concurrent workers belong to B-015.

Observability: JSON events on stderr report `worker.read`, `worker.write`, and
`worker.manifest` successes and failures, with a per-run correlation id forwarded
to asset-store. A final JSON summary on stdout reports status, read/write counts,
bytes, total and read latency, and manifest success. Service-side metrics and
issuance/commit audit events come from the existing guarded paths. Logs omit
credentials, capabilities, source URLs, alias text, and backend response bodies.

Result TTL hints and defaults are now supported by the guarded API (B-014,
FR-069). This simulator uses the service default (365 days unless configured);
its task JSON does not expose a TTL override. Cleanup runs in the separate
[lifecycle worker](lifecycle-worker.md). Q-008 remains open for transactional
bundle semantics. The expired-read status gap found by B-012 is closed: reads now
return 410 as specified by SCN-002.
