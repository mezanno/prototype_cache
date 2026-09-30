"""SEC-06 / FR-022/060: failed proxy writes are fenced and reclaimed."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import psycopg
import pytest
from prometheus_client import CollectorRegistry, generate_latest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from asset_store_core.capabilities import Capability, Operation
from asset_store_core.errors import ChecksumMismatchError, QuotaExceededError
from asset_store_core.guard import StorageGuard
from asset_store_core.lifecycle import run_sweep
from asset_store_core.models import AssetState, utcnow
from asset_store_core.object_store import LocalObjectStore, StoredObjectStat
from asset_store_core.pg_registry import PostgresAssetRegistry
from asset_store_core.registry import InMemoryAssetRegistry
from asset_store_core.registry_base import AssetRegistry
from asset_store_core.storage import ObjectStoreLocation


@pytest.fixture(params=["memory", "postgres"])
def registry(request: pytest.FixtureRequest) -> Iterator[AssetRegistry]:
    if request.param == "memory":
        yield InMemoryAssetRegistry()
        return
    dsn = os.environ.get("ASSET_STORE_PG_DSN")
    if not dsn:
        pytest.skip("ASSET_STORE_PG_DSN required")
    schema = "failed_upload_" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            with PostgresAssetRegistry.connect(
                make_conninfo(dsn, options=f"-c search_path={schema}")
            ) as pg:
                yield pg
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


class FaultStore(LocalObjectStore):
    fail_put = False
    fail_delete = False
    delete_calls = 0

    def put_object(self, location: ObjectStoreLocation, data: bytes) -> StoredObjectStat:
        stat = super().put_object(location, data)
        if self.fail_put:
            raise RuntimeError("interrupted after storing bytes")
        return stat

    def delete_object(self, location: ObjectStoreLocation) -> None:
        self.delete_calls += 1
        if self.fail_delete:
            raise RuntimeError("delete unavailable")
        super().delete_object(location)


def capability() -> Capability:
    return Capability(
        capability_id="failed-write",
        operation=Operation.WRITE,
        scope_prefix="cache/gallica",
        expires_at=utcnow() + timedelta(minutes=5),
        caller_service_id="bulk-loader",
        single_use=True,
    )


def location_for(registry: AssetRegistry) -> ObjectStoreLocation:
    asset = registry.list_assets()[0]
    return ObjectStoreLocation(bucket=asset.space, key=asset.storage_key)


@pytest.mark.parametrize("failure", ["quota", "checksum", "interrupted"])
def test_failure_reclaims_bytes_and_preserves_error(registry: AssetRegistry, failure: str) -> None:
    store = FaultStore()
    metrics = CollectorRegistry()
    guard = StorageGuard(registry, store, metrics_registry=metrics)
    expected: type[Exception] = ChecksumMismatchError
    kwargs: dict[str, Any] = {}
    if failure == "quota":
        registry.set_partition_quota(space="cache", partition_id="gallica", quota_bytes=1)
        expected = QuotaExceededError
    elif failure == "checksum":
        kwargs["expected_checksum"] = "sha256:wrong"
    else:
        store.fail_put = True
        expected = RuntimeError
    with pytest.raises(expected):
        guard.write_object(
            capability=capability(), alias="cache/gallica/a", data=b"bytes", **kwargs
        )
    if failure == "quota":
        # Exact-size reservation rejects before creating aliases or storing bytes.
        assert registry.list_assets() == ()
        assert not any(e.action == "alias.create" for e in registry.audit_events)
        assert store._objects == {}
        assert 'outcome="denied",space="cache"} 1.0' in generate_latest(metrics).decode()
    else:
        # get_asset also sees purged assets, while list_assets omits them.
        events = registry.audit_events
        asset_id = next(e.target for e in events if e.action == "asset.delete")
        asset = registry.get_asset(asset_id)
        assert asset.state is AssetState.DELETED
        assert asset.payload_deleted_at is not None
        assert (
            store.stat_object(ObjectStoreLocation(bucket=asset.space, key=asset.storage_key))
            is None
        )
        assert registry.get_bucket_quota(space="cache").used_bytes == 0
        assert (
            registry.get_partition_quota(space="cache", partition_id="gallica").used_asset_count
            == 0
        )
        assert any(e.action == "asset.payload_delete" and e.target == asset_id for e in events)
        assert 'outcome="reclaimed",space="cache"} 1.0' in generate_latest(metrics).decode()
    # Failed use did not consume the single-use token.
    store.fail_put = False
    registry.set_partition_quota(space="cache", partition_id="gallica", quota_bytes=100)
    assert (
        guard.write_object(capability=capability(), alias="cache/gallica/b", data=b"ok").state
        is AssetState.AVAILABLE
    )


def test_delete_failure_is_durable_and_sweep_retries(registry: AssetRegistry) -> None:
    store = FaultStore()
    store.fail_delete = True
    metrics = CollectorRegistry()
    guard = StorageGuard(registry, store, metrics_registry=metrics)
    with pytest.raises(ChecksumMismatchError):
        guard.write_object(
            capability=capability(),
            alias="cache/gallica/a",
            data=b"bytes",
            expected_checksum="sha256:wrong",
        )
    asset = registry.list_assets()[0]
    assert asset.state is AssetState.DELETED
    assert asset.payload_deleted_at is None
    location = location_for(registry)
    assert store.get_object(location) == b"bytes"
    assert 'outcome="deferred",space="cache"} 1.0' in generate_latest(metrics).decode()
    store.fail_delete = False
    report = run_sweep(registry, store, dry_run=False)
    assert report.applied == 1 and report.errors == 0
    assert store.stat_object(location) is None
    assert registry.get_asset(asset.asset_id).payload_deleted_at is not None


def test_cleanup_preserves_successful_commit(registry: AssetRegistry) -> None:
    store = FaultStore()
    metrics = CollectorRegistry()
    guard = StorageGuard(registry, store, metrics_registry=metrics)
    asset = guard.write_object(capability=capability(), alias="cache/gallica/a", data=b"bytes")
    location = ObjectStoreLocation(bucket=asset.space, key=asset.storage_key)
    # Recheck a stale failure/cleanup intent after a successful commit.
    guard._cleanup_failed_upload(asset.asset_id, location)
    assert store.delete_calls == 0
    assert store.get_object(location) == b"bytes"
    assert registry.get_asset(asset.asset_id).state is AssetState.AVAILABLE
    assert registry.get_bucket_quota(space="cache").used_bytes == 5
    assert 'outcome="preserved",space="cache"} 1.0' in generate_latest(metrics).decode()


def test_fence_is_committed_before_storage_deletion(registry: AssetRegistry) -> None:
    from concurrent.futures import ThreadPoolExecutor

    class FenceCheckingStore(FaultStore):
        def delete_object(self, location: ObjectStoreLocation) -> None:
            asset_id = location.key.rsplit("/", 1)[1]
            # A separate thread obtains a separate PG transaction. It must see
            # DELETED even while cleanup holds its second asset lock.
            with ThreadPoolExecutor(max_workers=1) as executor:
                observed = executor.submit(registry.get_asset, asset_id).result(timeout=5)
            assert observed.state is AssetState.DELETED
            assert observed.payload_deleted_at is None
            super().delete_object(location)

    store = FenceCheckingStore()
    guard = StorageGuard(registry, store)
    with pytest.raises(ChecksumMismatchError):
        guard.write_object(
            capability=capability(),
            alias="cache/gallica/a",
            data=b"bytes",
            expected_checksum="sha256:wrong",
        )
    assert store.delete_calls == 1
    assert registry.list_assets() == ()


def test_fence_failure_keeps_bytes_for_orphan_sweep(
    registry: AssetRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FaultStore()
    guard = StorageGuard(registry, store)
    original = type(registry).lifecycle_update

    def unavailable(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("registry unavailable during fencing")

    monkeypatch.setattr(type(registry), "lifecycle_update", unavailable)
    with pytest.raises(ChecksumMismatchError):
        guard.write_object(
            capability=capability(),
            alias="cache/gallica/a",
            data=b"bytes",
            expected_checksum="sha256:wrong",
        )
    asset = registry.list_assets()[0]
    location = location_for(registry)
    assert asset.state is AssetState.PENDING
    assert store.delete_calls == 0
    assert store.get_object(location) == b"bytes"
    monkeypatch.setattr(type(registry), "lifecycle_update", original)
    report = run_sweep(registry, store, dry_run=False, now=utcnow() + timedelta(days=2))
    assert report.applied == 1 and report.errors == 0
    assert store.stat_object(location) is None


def test_failed_upload_reclaims_real_garage_object(registry: AssetRegistry) -> None:
    from asset_store_core.s3_object_store import S3ObjectStore

    endpoint = os.environ.get("ASSET_STORE_S3_ENDPOINT")
    access = os.environ.get("ASSET_STORE_S3_ACCESS_KEY")
    secret = os.environ.get("ASSET_STORE_S3_SECRET_KEY")
    if not (endpoint and access and secret):
        pytest.skip("Garage configuration required")
    store = S3ObjectStore(
        endpoint_url=endpoint,
        region=os.environ.get("ASSET_STORE_S3_REGION", "garage"),
        access_key=access,
        secret_key=secret,
    )
    guard = StorageGuard(registry, store)
    alias = "cache/gallica/cleanup-" + uuid.uuid4().hex
    try:
        with pytest.raises(ChecksumMismatchError):
            guard.write_object(
                capability=capability(),
                alias=alias,
                data=b"real garage bytes",
                expected_checksum="sha256:wrong",
            )
        asset_id = next(e.target for e in registry.audit_events if e.action == "asset.delete")
        asset = registry.get_asset(asset_id)
        assert asset.state is AssetState.DELETED
        assert asset.payload_deleted_at is not None
        assert (
            store.stat_object(ObjectStoreLocation(bucket=asset.space, key=asset.storage_key))
            is None
        )
    finally:
        # A cleanup failure should not leave a test object behind.
        for asset in registry.list_assets():
            store.delete_object(ObjectStoreLocation(bucket=asset.space, key=asset.storage_key))


def test_http_failure_keeps_problem_response_and_exports_cleanup_metric(
    registry: AssetRegistry,
) -> None:
    from fastapi.testclient import TestClient

    from asset_store_core.api import create_app

    store = FaultStore()
    with TestClient(create_app(registry=registry, store=store)) as client:
        minted = client.post(
            "/capabilities",
            headers={"Authorization": "Service bulk-loader:dev-secret:bulk-loader"},
            json={"operation": "write", "scope_prefix": "cache/gallica", "ttl_seconds": 300},
        )
        assert minted.status_code == 201
        response = client.put(
            "/objects/cache/gallica/a",
            params={"expected_checksum": "sha256:wrong"},
            headers={"Authorization": "Capability " + minted.json()["capability_id"]},
            content=b"bytes",
        )
        assert response.status_code == 409
        assert response.json()["title"] == "ChecksumMismatchError"
        assert registry.list_assets() == ()
        assert 'outcome="reclaimed",space="cache"} 1.0' in client.get("/metrics").text


def test_failed_delete_retains_physical_budget_until_sweep(
    registry: AssetRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    from asset_store_core.errors import CapacityExceededError

    monkeypatch.setenv("ASSET_STORE_CAPACITY_BYTES", '{"cache": 10}')
    store = FaultStore()
    store.fail_delete = True
    guard = StorageGuard(registry, store)
    with pytest.raises(ChecksumMismatchError):
        guard.write_object(
            capability=capability(),
            alias="cache/gallica/a",
            data=b"123456",
            expected_checksum="sha256:wrong",
        )
    assert registry.reserved_upload_bytes("cache") == 6
    assert registry.get_bucket_quota(space="cache").used_bytes == 0
    with pytest.raises(CapacityExceededError):
        guard.write_object(capability=capability(), alias="cache/gallica/b", data=b"1234")
    assert len(registry.list_assets()) == 1
    store.fail_delete = False
    report = run_sweep(registry, store, dry_run=False)
    assert report.applied == 1 and report.errors == 0
    assert registry.reserved_upload_bytes("cache") == 0
    assert (
        guard.write_object(capability=capability(), alias="cache/gallica/b", data=b"1234").state
        is AssetState.AVAILABLE
    )
