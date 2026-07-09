# bulk-loader

CLI for **SCN-001** bulk preload — warms the `cache` bucket with a batch of
assets ahead of processing (B-011).

## What it does

1. Authenticates as the `bulk-loader` service (`Authorization: Service <id>:<secret>`,
   FR-014).
2. Mints one **write** capability scoped to `cache/{mirror-id}` (the capability
   model requires a bucket plus at least one segment, so a bare-bucket `cache/`
   scope is not representable; the per-mirror scope still covers every row of a
   run and is tighter than a bucket-wide grant). FR-015 additionally confines this
   service to `cache`.
3. Streams each manifest row through the guarded data plane
   (`PUT /objects/cache/{mirror-id}/{alias}`), which performs reserve → PUT →
   commit server-side (FR-004/FR-020/FR-022).
4. Prints a summary (`N ok, M failed, bytes, elapsed`).

## Manifest format

A CSV file with an `alias,mime,path` header:

```csv
alias,mime,path
bnf/ark-123/default.jpg,image/jpeg,images/ark-123.jpg
bnf/ark-124/default.jpg,image/jpeg,images/ark-124.jpg
```

- `alias` — relative to the mirror; the stable citation name becomes
  `cache/{mirror-id}/{alias}`. There is **no batch-id in the path**, so re-running
  a manifest resolves to the same aliases and only re-creates missing rows.
- `path` — local file, absolute or relative to the manifest's directory.

## Batch semantics — best-effort per row (Q-001)

Assets are immutable and committed independently, so there is no cross-asset
transaction. The loader tries every row:

- good rows commit and are immediately resolvable;
- failed rows are reported and cause a **non-zero exit**;
- `--report failures.csv` writes failed rows (`alias,path,error`) for retrying;
- `--fail-fast` stops at the first failure (earlier rows stay committed) for
  interactive manifest debugging;
- transient (5xx / transport) errors are retried per row (`--max-retries`).

## Usage

```bash
export BULK_LOADER_SERVICE_SECRET=...   # never pass secrets on the command line
uv run python tools/bulk-loader/bulk_loader.py \
    --manifest batch.csv \
    --mirror-id gallica \
    --base-url http://localhost:8080 \
    --report failures.csv
```

## Notes / future work

- The loader authenticates only as a **service** identity. Attributing a batch to
  an initiating admin/user principal (on top of the service identity) is tracked
  as **Q-030**.
- The SCN-001 sketch scopes the capability to `cache/{mirror}/{batch-id}/`; that
  prefix would not cover `cache/{mirror}/…` aliases, so the loader scopes to
  `cache/{mirror-id}` instead (see WORKPLAN B-011).

