# Bulk-loader — preload the cache

The `bulk-loader` CLI ([`tools/bulk-loader/bulk_loader.py`](../../tools/bulk-loader/bulk_loader.py))
warms the `cache` bucket with a batch of assets ahead of processing (SCN-001,
backlog item B-011).

## What it does

1. Authenticates as the `bulk-loader` **service identity**
   (`Authorization: Service <id>:<secret>`, FR-014).
2. Mints **one** short-lived (1 h) **write capability** scoped to
   `cache/{mirror-id}` (see [Permissions](#permissions-per-mirror) below).
3. Streams each manifest row through the guarded data plane
   (`PUT /objects/cache/{mirror-id}/{alias}`); the server performs
   reserve → PUT → commit atomically (FR-004/FR-020/FR-022).
4. Prints a summary: `N ok, M failed, bytes, elapsed`.

## Manifest format

A CSV file with an `alias,mime,path` header:

```csv
alias,mime,path
bnf/ark-123/default.jpg,image/jpeg,images/ark-123.jpg
bnf/ark-124/default.jpg,image/jpeg,images/ark-124.jpg
```

- **`alias`** — relative to the mirror. The stable citation name becomes
  `cache/{mirror-id}/{alias}`. There is **no batch id in the path**, so re-running
  a manifest resolves to the same aliases and only re-creates missing rows
  (idempotent from the caller's view).
- **`mime`** — content type recorded on commit (may be empty).
- **`path`** — local file, absolute or relative to the manifest's directory.

## Usage

```bash
export BULK_LOADER_SERVICE_SECRET=...   # never pass a secret on the command line

uv run python tools/bulk-loader/bulk_loader.py \
    --manifest batch.csv \
    --mirror-id gallica \
    --base-url http://localhost:8080 \
    --report failures.csv
```

Key options:

| Option | Purpose |
|--------|---------|
| `--manifest` | CSV manifest (`alias,mime,path`). Required. |
| `--mirror-id` | Partition under `cache/` (e.g. `gallica`). Required. |
| `--service-id` | Service identity used to mint (default `bulk-loader`). |
| `--service-secret` | Secret, or env `BULK_LOADER_SERVICE_SECRET`. Required. |
| `--fail-fast` | Stop at the first failing row (earlier rows stay committed). |
| `--report FILE` | Write failed rows (`alias,path,error`) for retrying. |
| `--max-retries` | Retries per row for transient (5xx / transport) errors. |

## Batch semantics — best-effort per row

Assets are immutable and committed independently, so there is **no cross-asset
transaction** (open question Q-001, resolved for the prototype). The loader:

- commits every good row immediately (each becomes resolvable at once);
- collects failed rows and exits **non-zero** if any failed;
- with `--report`, writes failed rows so you can retry just those;
- with `--fail-fast`, stops on the first failure (for manifest debugging);
- retries transient errors per row before giving up.

A re-run of the same manifest simply re-creates the rows that are still missing.

## Permissions per mirror

The loader's write capability is scoped to `cache/{mirror-id}` — the capability
model requires a bucket **plus at least one segment**, so a bucket-wide `cache/`
scope is not representable. The per-mirror scope is the least-privilege grant that
still covers a whole run.

What this means operationally today:

- The `bulk-loader` service identity is allowed to **write the entire `cache`
  bucket** (FR-015 service→bucket allowlist). Any `--mirror-id` therefore works
  with **no extra per-mirror configuration** — the per-mirror scoping happens
  automatically at capability-mint time, per run.
- You only need to configure the **service credential** (the `id:secret` pair):
  - default (dev): every known service id maps to `dev-secret:<id>` (zero-config
    for the compose stack and tests);
  - production: set `ASSET_STORE_SERVICE_CREDENTIALS="bulk-loader:<secret>,..."`
    on the asset-store service, and pass the matching `--service-secret` (via
    `BULK_LOADER_SERVICE_SECRET`) to the loader.

> **Future:** if you later want to restrict the loader to *specific* mirrors (not
> the whole `cache` bucket), that is a policy extension to the service→bucket
> allowlist, not a change to the loader. Attributing a batch to an initiating
> admin/user principal on top of the service identity is tracked as **Q-030**.

## How it is tested

- **Unit / contract** ([`tests/test_bulk_loader.py`](../../tests/test_bulk_loader.py)):
  drives the full HTTP ingestion path (mint → PUT → reserve/commit → resolve)
  against the in-memory object store — covers manifest parsing, happy path,
  partial failure, `--fail-fast`, the failure report, and auth/allowlist denials.
- **End-to-end down to S3** ([`tests/test_bulk_loader_garage.py`](../../tests/test_bulk_loader_garage.py)):
  runs the loader against an app backed by `S3ObjectStore` + live **Garage** and
  reads the bytes back out of the bucket. **Skipped** unless Garage is running and
  its credentials are exported (see
  [`deploy/compose/README.md`](../../deploy/compose/README.md)):

  ```bash
  cd deploy/compose
  docker compose -f docker-compose.garage.yml up -d && ./garage-init.sh
  set -a && source .env.garage && set +a
  uv run pytest tests/test_bulk_loader_garage.py -q
  ```
