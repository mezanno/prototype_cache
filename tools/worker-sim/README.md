# worker-sim

CLI for **SCN-002 worker reads** and **SCN-005 worker result writes** (B-012).

It verifies each input's SHA-256, copies the bytes into result artifacts, and
publishes a JSON manifest last. Omit `result_prefix` for a read-only run.

## Usage

Install the development tools with `uv sync --locked --group dev`. Start the
[local stack](../../deploy/compose/README.md), then preload an input using the
[bulk-loader](../bulk-loader/README.md) or fetcher. Create `task.json`:

```json
{
  "inputs": [
    {
      "alias": "cache/demo/input.bin",
      "checksum": "sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    }
  ],
  "result_prefix": "results/42/task-1/attempt-1/worker-1"
}
```

This example expects the five bytes `hello`; for another asset, use its committed
checksum from the task producer or registry. The input must exist before running.

```bash
# Local dev only; use the configured worker credential elsewhere.
export WORKER_SIM_SERVICE_SECRET=dev-secret:worker
uv run --locked python tools/worker-sim/worker_sim.py \
  --task task.json --base-url http://localhost:8000
```

Success produces `output-0001.bin` and `manifest.json` under the result prefix.
The JSON summary on stdout includes read/write counts, bytes, timing, correlation
id and manifest success; structured events go to stderr. Writes/bytes count
artifact payloads only (the manifest has its own success flag).

## Failure and security behavior

- Task validation rejects invalid paths, checksums, empty inputs and unknown fields.
- The simulator mints capabilities as `worker`, scoped per input alias and result
  prefix. It simulates dispatch; it is not the task engine or an end-user API.
- Failures exit nonzero and stop the run. Committed partial outputs are retained;
  the completion manifest is only attempted after every artifact succeeds.
- Reuse of an attempt prefix conflicts with immutable aliases. Choose a new
  attempt prefix after failure; writes are not automatically retried.
- A lost final upload response can mean the manifest committed despite a reported
  error; inspect that alias before retrying.
- Inputs are limited to 50 MiB each. Processing, concurrency/load tests, capability
  refresh and result TTL/cleanup are outside this simulator milestone.

See the [task and manifest contract](../../docs/services/worker-sim.md) and ADR-019.

## Tests

```bash
uv run --locked pytest tests/test_worker_sim.py -q
```

In-memory acceptance tests run in CI. Export `deploy/compose/.env.garage` and
`ASSET_STORE_PG_DSN` as in the [backend test recipe](../../deploy/compose/README.md)
to run the same tests on Garage/Postgres. Each durable test owns a temporary
schema and cleans up its objects; configured backend failures fail the test.
