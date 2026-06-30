# storage-guard

Future FastAPI capability broker (`FR-010`–`FR-015`, audit log).

**Prototype shortcut:** not implemented yet. Use `InMemoryAssetRegistry` and `assert_service_bucket_allowed()` from `asset_store_core` in tests. See [`docs/IMPLEMENTATION_NOTES.md`](../../docs/IMPLEMENTATION_NOTES.md).

The guard will wrap registry + object store: authenticate service identity, enforce bucket allowlist, mint presigned URLs, emit audit events.
