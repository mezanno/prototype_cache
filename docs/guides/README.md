# User Guide

Practical, task-oriented documentation for operators and client-service authors
using the **asset-store** module. For requirements and architecture, see
[`../spec/README.md`](../spec/README.md); for code-vs-spec status, see
[`../IMPLEMENTATION_NOTES.md`](../IMPLEMENTATION_NOTES.md).

## Contents

- [Bulk-loader — preload the cache](bulk-loader.md)
- [Admin console](admin-console.md) — find assets, change retention, manage quotas and preview bulk expiry.

## Concepts you need

- **Bucket** — a top-level storage space: `cache`, `tmp`, `users`, `results`.
- **Partition** — the second path segment, scoping data within a bucket (e.g. a
  mirror id like `gallica`, or a user id like `42`).
- **Alias** — a stable, immutable citation name for an asset,
  `{bucket}/{partition}/{name...}` (e.g. `cache/gallica/bnf/ark-123/default.jpg`).
- **Service identity** — a client service authenticates with
  `Authorization: Service <service_id>:<secret>` (FR-014). Each identity is
  allowed a fixed set of buckets (FR-015).
- **Capability** — a short-lived, prefix-scoped grant for `read` or `write`,
  presented as `Authorization: Capability <id>`. Its `scope_prefix` must be at
  least `bucket/segment` (a bare bucket is not allowed).

## Capability limits

Reuse a live capability for its permitted scope until it expires. The service
retains at most `ASSET_STORE_MAX_CAPABILITIES` live tokens (default 10,000).
Issuance returns 503 with `Retry-After: 1` when full; clients should retry with
backoff or reuse an existing token. Expired entries are removed automatically.
Restart invalidates all tokens, so clients must mint replacements.
