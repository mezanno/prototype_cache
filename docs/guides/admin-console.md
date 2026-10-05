# Using the asset-store console

For operators managing stored content. Open **`/admin`** on your asset-store
instance and enter the admin secret supplied by your administrator, then choose
**Connect**. For local setup, see the [run instructions](../services/admin-ui.md#run-and-verify).

## Find and inspect content

1. Choose a **Space**: `cache` for remote mirrors, `tmp` for temporary inputs,
   `users` for uploads, or `results` for worker outputs.
2. Optionally enter a **Partition** (for example, user `42`), state, creation dates
   or an **Alias prefix** such as `results/42/task-17`. A partition requires a space.
3. Select **Apply filters**, then click an asset in the table. **Next page** shows
   more results; applying filters again starts at the first page.
4. The inspection panel shows metadata, aliases, access statistics and recent
   audit events. **View recent global audit** shows activity across the repository.

## Change an asset

Select an asset first. Each change asks for confirmation and refreshes its details.

| Action | Effect |
|---|---|
| **Set TTL / restore expired** | Set a deadline in seconds **from now**. Can restore an expired asset before cleanup, if quota permits. `tmp` is capped at 7 days; `results` uses the operator's maximum (365 days by default). |
| **Expire** | Stop new guarded reads now; keep bytes until the lifecycle worker's grace period ends. |
| **Delete** | Stop new guarded reads now and make the asset terminal. The lifecycle worker removes bytes later; **TTL cannot undo deletion**. |
| **Attach / Detach alias** | Add or remove a name. Enter the partition and path, e.g. `42/uploads/photo.jpg`, without the space. Removing the last alias schedules cleanup. |
| **Save annotations** | Replace annotations with the entered JSON map, e.g. `{"note":"checked"}`. Payload bytes stay unchanged. |
| **Save policy** | `exempt` protects against capacity/quota eviction, **not TTL expiry**. |

**Already-issued download URLs can still work** until their expiry or physical
payload deletion, even after Expire/Delete. Default URL lifetime is five minutes,
with a one-hour maximum. Use the guarded proxy when immediate revocation is required.

TTL changes affect every alias of the selected asset. If the console reports
“asset changed”, select the asset again, review its current details and retry.
Deleted metadata remains visible even after its payload has been removed.

## Quotas and bulk expiry

**Partition quota:** choose a space and partition in the filters, then expand the
quota section. Empty byte/count limits mean unlimited; zero means no allowance.
**Save quota** replaces that partition's configuration. Automatic quota eviction
applies only to `cache` and `tmp`; it does not evict `users` or `results`.

**Bulk expiry:** enter a qualified alias prefix such as `results/42/task-17`,
expand the bulk section, and select **Preview matching assets**. Check the prefix
and candidate count before selecting **Expire previewed assets**. This action
uses the alias prefix, not the other list filters. It expires only available
assets; changed candidates are skipped and reported. Narrow the prefix if more
than 500 assets match. A preview changes nothing.

## Finish or troubleshoot

- **Disconnect** clears the credential and displayed data. Refreshing the page
  also requires reconnecting; the credential is not saved in browser storage.
  Disconnect also clears quota/edit fields and ignores responses from the previous
  connection. It does not undo actions already submitted to the server.
- **Unauthorized / forbidden:** check the admin secret with your administrator.
- **Quota exceeded when restoring:** increase the quota or free capacity first.
- **Bytes still present after deletion:** ask the operator to check the
  [lifecycle worker](../services/lifecycle-worker.md); cleanup is asynchronous.
