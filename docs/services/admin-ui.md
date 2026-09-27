# Admin console (B-013)

Operator walkthrough: [Using the console](../guides/admin-console.md).

Implements SCN-004, FR-040..042, FR-005..007 and FR-051..053. The console is
served by asset-store at `/admin` with no separate frontend build or service.
A small same-origin JavaScript client uses `/admin/api`; credentials stay in
page memory, never browser storage or URLs. Use an explicitly configured `admin`
service credential and HTTPS outside local development. This is a trusted operator
console, not end-user authentication or a task-engine delegation endpoint.

## Contract (ADR-021)

- List assets with space, partition, state, creation range and qualified alias
  prefix filters. Cursor pagination orders by `(created_at, asset_id)` and binds
  the cursor to its filters. Includes deleted/purged metadata. A partition filter
  requires a space and includes quota usage. Prefixes match complete path segments.
- Inspect metadata, aliases, access statistics and recent related audit events.
  Raw storage keys are omitted from the admin representation.
- Asset mutations require the inspected `updated_at` revision. Partition quota
  configuration is an explicit replacement (last write wins), with before/after audit. Conflicts return 409.
  TTL seconds count from the action time and obey the existing bucket maxima.
  An expired asset can be restored if its payload is unpurged and quota allows;
  deleted assets cannot be restored. Alias deadlines remain shared per asset.
- Previously issued presigned URLs remain usable until URL expiry or physical
  deletion; expiry/delete immediately deny new guarded reads, not old S3 URLs.
- Delete marks metadata terminal; B-014 removes bytes asynchronously. The UI makes
  pending payload cleanup explicit. Expire preserves bytes through the grace period.
- Attach/detach aliases, edit annotations and eviction policy, configure partition
  quotas. Bulk expiry uses a qualified prefix containing a partition; previews are
  bounded to 500 assets, and applying rechecks each asset revision and prefix.
  Changed candidates are skipped and reported; one asset with several matches is
  processed once. Larger selections must be narrowed. No silent truncation.
- Admin API requires `Authorization: Service admin:<secret>`. Existing legacy
  administrative mutation/audit/quota routes also require admin authentication;
  legacy body caller identities must match the authenticated identity.
  Reserve/commit/resolve control-plane hardening remains B-018.
- Mutation audit events record authenticated `admin`; counters and structured logs
  record action/outcome without credentials or alias text. Existing per-request
  metrics cover reads and authorization failures.

## Deliberate limits

No persistent browser sessions, SSO, asynchronous bulk job engine, per-partition
tmp default-TTL overrides, batch eviction-policy reset or per-human attribution.
The tmp override needs a separate policy configuration contract; it is not an
implicit change to partition quota settings. General deployment/security review,
remains B-018; see the [security checkpoint](../security/B018_CLOSEOUT.md).

## Run and verify

Use the existing [Compose setup](../../deploy/compose/README.md), or run an
in-memory development instance:

```bash
ASSET_STORE_DEV_MODE=1 uv run uvicorn asset_store_core.api:create_app_from_env --factory --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/admin`. When `ASSET_STORE_DEV_MODE=1` and `ASSET_STORE_SERVICE_CREDENTIALS` is unset,
the development admin secret is `dev-secret:admin`. Configured environments must
include an `admin` entry alongside their existing service credentials.
The static page is public; every data read and mutation requires authentication.
Use **Disconnect** to clear the credential and displayed data.

API summary:

| Method | Path under `/admin/api` | Purpose |
|---|---|---|
| GET | `/assets` | Filtered, cursor-paginated list and optional partition quota |
| GET | `/assets/{asset_id}` | Metadata and last 100 related audit events |
| POST | `/assets/{asset_id}/actions` | Revision-checked `expire`, `delete`, `ttl`, `attach`, `detach`, `annotations`, `eviction` |
| PUT | `/quotas/partition` | Audited quota configuration |
| GET | `/aliases/expire?prefix=…` | Bulk-expiry preview |
| POST | `/aliases/expire?prefix=…` | Apply explicit preview candidates |
| GET | `/audit` | Last 100 events (limit 1..500) |

Tests: `tests/test_admin.py` runs against memory and isolated Postgres schemas
(the latter requires `ASSET_STORE_PG_DSN`). Existing lifecycle-worker tests cover
physical deletion after the admin metadata transition. No cleanup is run against
operator data by the console tests.

Metrics: `asset_store_admin_actions_total{action,outcome}` counts accepted
mutation attempts and their success/error result; HTTP counters include auth
rejections. JSON event `admin.action` carries action/outcome and correlation id.
Bulk success means the request completed; its response reports applied/skipped
counts. Audit records each applied asset transition, not a fictitious atomic batch.
