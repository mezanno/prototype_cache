"""SEC-02 / ADR-023: deterministic rollback isolation and bounded pool lifecycle."""

from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import Mock

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from asset_store_core.api import create_app, create_app_from_env
from asset_store_core.errors import RegistryUnavailableError, ValidationError
from asset_store_core.object_store import LocalObjectStore
from asset_store_core.pg_registry import PostgresAssetRegistry
from asset_store_core.storage import ObjectStoreLocation

ADMIN = {"Authorization": "Service admin:dev-secret:admin"}


@pytest.fixture
def isolated_dsn() -> Iterator[str]:
    dsn = os.environ.get("ASSET_STORE_PG_DSN")
    if not dsn:
        pytest.skip("ASSET_STORE_PG_DSN required")
    schema = "isolation_" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            yield make_conninfo(dsn, options=f"-c search_path={schema}")
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_http_rollback_cannot_erase_acknowledged_commit(
    isolated_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with PostgresAssetRegistry.connect(isolated_dsn, pool_min_size=2, pool_max_size=2) as registry:
        a, b = [
            registry.reserve_asset(
                space="cache", partition_id="test", aliases=[name], owner_service_id="admin"
            )
            for name in ("a", "b")
        ]
        store = LocalObjectStore()
        stat = store.put_object(
            ObjectStoreLocation.for_asset(
                space=b.space, partition_id=b.partition_id, asset_id=b.asset_id
            ),
            b"verified",
        )
        entered, release = threading.Event(), threading.Event()
        original = registry._write_audit

        def interrupted_audit(**kwargs: Any) -> None:
            if kwargs["target"] == a.asset_id:
                entered.set()
                assert release.wait(10), "test did not release failing request"
                raise ValidationError("controlled rollback")
            original(**kwargs)

        monkeypatch.setattr(registry, "_write_audit", interrupted_audit)
        with TestClient(create_app(registry=registry, store=store)) as client:
            with ThreadPoolExecutor(max_workers=1) as executor:
                failed = executor.submit(
                    client.patch,
                    f"/assets/{a.asset_id}/annotations",
                    headers=ADMIN,
                    json={"patch": {"rolled_back": "yes"}, "caller_service_id": "admin"},
                )
                try:
                    assert entered.wait(5), "first request never entered its transaction"
                    committed = client.post(
                        f"/assets/{b.asset_id}/commit",
                        headers=ADMIN,
                        json={
                            "size_bytes": stat.size_bytes,
                            "checksum": stat.checksum,
                            "caller_service_id": "admin",
                        },
                    )
                    assert committed.status_code == 200, committed.text
                    assert not failed.done()  # success was acknowledged before A rolled back
                finally:
                    release.set()
                assert failed.result(timeout=5).status_code == 400
            metrics = client.get("/metrics").text
            assert 'asset_store_registry_transactions_total{outcome="rolled_back"} 1.0' in metrics
            assert "asset_store_registry_checkout_seconds_count" in metrics
        # A new pool proves persistence, not just an in-transaction observation.
        with PostgresAssetRegistry.connect(isolated_dsn, bootstrap_schema=False) as reopened:
            assert dict(reopened.get_asset(a.asset_id).annotations) == {}
            assert reopened.get_asset(b.asset_id).checksum == stat.checksum
            quota = reopened.get_partition_quota(space="cache", partition_id="test")
            assert (quota.used_bytes, quota.used_asset_count) == (len(b"verified"), 1)
            assert reopened.get_bucket_quota(space="cache").used_bytes == len(b"verified")
            events = reopened.audit_events
            assert any(e.action == "asset.commit" and e.target == b.asset_id for e in events)
            assert not any(
                e.action == "asset.annotations_update" and e.target == a.asset_id for e in events
            )


def test_nested_asset_lock_rolls_back_data_quota_and_audit(isolated_dsn: str) -> None:
    with PostgresAssetRegistry.connect(isolated_dsn, pool_max_size=1) as registry:
        asset = registry.reserve_asset(
            space="cache", partition_id="test", aliases=["a"], owner_service_id="admin"
        )
        before = registry.audit_events
        with pytest.raises(ValidationError):
            with registry.asset_lock(asset.asset_id):
                registry.commit_asset(
                    asset_id=asset.asset_id,
                    size_bytes=7,
                    checksum="sha256:test",
                    caller_service_id="admin",
                )
                with registry.asset_lock(asset.asset_id):
                    registry.update_annotations(
                        asset_id=asset.asset_id,
                        patch={"nested": "yes"},
                        caller_service_id="admin",
                    )
                raise ValidationError("rollback outer unit")
        assert registry.get_asset(asset.asset_id) == asset
        assert registry.audit_events == before
        assert registry.get_bucket_quota(space="cache").used_bytes == 0
        assert registry.get_partition_quota(space="cache", partition_id="test").used_bytes == 0
        # The same one-slot pool can be reused after failure.
        registry.update_annotations(
            asset_id=asset.asset_id, patch={"ok": "yes"}, caller_service_id="admin"
        )
        assert registry.get_asset(asset.asset_id).annotations["ok"] == "yes"


def test_pool_timeout_is_retryable_and_recovers(isolated_dsn: str) -> None:
    with PostgresAssetRegistry.connect(
        isolated_dsn, pool_max_size=1, pool_timeout=0.15
    ) as registry:
        held, release = threading.Event(), threading.Event()

        def hold() -> None:
            with registry.unit_of_work():
                held.set()
                assert release.wait(5)

        with TestClient(create_app(registry=registry)) as client:
            with ThreadPoolExecutor(max_workers=1) as executor:
                holder = executor.submit(hold)
                try:
                    assert held.wait(3)
                    response = client.get("/audit", headers=ADMIN)
                    assert response.status_code == 503
                    assert response.headers["retry-after"] == "1"
                    assert response.json()["detail"] == "registry temporarily unavailable"
                    assert isolated_dsn not in response.text
                    assert (
                        "asset_store_registry_unavailable_total 1.0" in client.get("/metrics").text
                    )
                finally:
                    release.set()
                holder.result(timeout=3)
            assert client.get("/audit", headers=ADMIN).status_code == 200
        assert registry.audit_events == ()  # injected registries stay caller-owned
    with pytest.raises(RegistryUnavailableError):
        registry.list_assets()


def test_environment_app_closes_owned_pool(
    isolated_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ASSET_STORE_PG_DSN", isolated_dsn)
    monkeypatch.delenv("ASSET_STORE_S3_ENDPOINT", raising=False)
    app = create_app_from_env()
    with TestClient(app) as client:
        assert client.get("/audit", headers=ADMIN).status_code == 200
    with pytest.raises(RegistryUnavailableError):
        app.state.registry.list_assets()


def test_factory_failure_closes_created_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = Mock()
    monkeypatch.setattr(PostgresAssetRegistry, "connect", Mock(return_value=registry))
    monkeypatch.setenv("ASSET_STORE_PG_DSN", "unused")
    monkeypatch.delenv("ASSET_STORE_S3_ENDPOINT", raising=False)
    monkeypatch.setenv("ASSET_STORE_MAX_UPLOAD_BYTES", "0")
    with pytest.raises(ValidationError):
        create_app_from_env()
    registry.close.assert_called_once_with()


@pytest.mark.parametrize(
    "key,value",
    [
        ("ASSET_STORE_PG_POOL_MIN", "0"),
        ("ASSET_STORE_PG_POOL_MAX", "0"),
        ("ASSET_STORE_PG_POOL_TIMEOUT", "nan"),
        ("ASSET_STORE_PG_POOL_TIMEOUT", "bad"),
        ("ASSET_STORE_PG_POOL_MAX_WAITING", "0"),
    ],
)
def test_pool_rejects_invalid_bounds(key: str, value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(key, value)
    with pytest.raises(ValidationError):
        PostgresAssetRegistry.connect("unused")


def test_pool_queue_is_bounded(isolated_dsn: str) -> None:
    from time import monotonic, sleep

    with PostgresAssetRegistry.connect(
        isolated_dsn, pool_max_size=1, pool_max_waiting=1, pool_timeout=3
    ) as registry:
        with ThreadPoolExecutor(max_workers=2) as executor:
            with registry.unit_of_work():
                queued = executor.submit(registry.list_assets)
                deadline = monotonic() + 2
                while registry._pool.get_stats().get("requests_waiting", 0) != 1:
                    assert monotonic() < deadline, "caller did not enter pool queue"
                    sleep(0.01)
                rejected = executor.submit(registry.list_assets)
                with pytest.raises(RegistryUnavailableError):
                    rejected.result(timeout=1)
                assert not queued.done()
            assert queued.result(timeout=2) == ()


def test_concurrent_commits_preserve_quota_ceiling(isolated_dsn: str) -> None:
    from asset_store_core.errors import QuotaExceededError

    with PostgresAssetRegistry.connect(isolated_dsn, pool_min_size=2, pool_max_size=2) as registry:
        registry.set_partition_quota(space="cache", partition_id="test", quota_asset_count=1)
        assets = [
            registry.reserve_asset(
                space="cache", partition_id="test", aliases=[name], owner_service_id="admin"
            )
            for name in ("a", "b")
        ]
        barrier = threading.Barrier(2)

        def commit(asset_id: str) -> bool:
            barrier.wait(timeout=3)
            try:
                registry.commit_asset(
                    asset_id=asset_id,
                    size_bytes=7,
                    checksum="sha256:test",
                    caller_service_id="admin",
                )
            except QuotaExceededError:
                return False
            return True

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(commit, [a.asset_id for a in assets]))
        assert sorted(results) == [False, True]
        quota = registry.get_partition_quota(space="cache", partition_id="test")
        assert (quota.used_bytes, quota.used_asset_count) == (7, 1)
        assert registry.get_bucket_quota(space="cache").used_bytes == 7
        assert sum(e.action == "asset.commit" for e in registry.audit_events) == 1


def test_upload_gate_keeps_other_requests_responsive_during_storage_put(
    isolated_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-06: blocking storage PUT runs outside the HTTP event loop."""
    from asset_store_core.object_store import StoredObjectStat

    class PausingStore(LocalObjectStore):
        def __init__(self) -> None:
            super().__init__()
            self.entered = threading.Event()
            self.release = threading.Event()

        def put_object(self, location: ObjectStoreLocation, data: bytes) -> StoredObjectStat:
            self.entered.set()
            assert self.release.wait(5)
            return super().put_object(location, data)

    monkeypatch.setenv("ASSET_STORE_MAX_INFLIGHT_UPLOADS", "1")
    store = PausingStore()
    with PostgresAssetRegistry.connect(isolated_dsn, pool_min_size=2, pool_max_size=2) as registry:
        app = create_app(registry=registry, store=store)
        with TestClient(app) as client:
            minted = client.post(
                "/capabilities",
                headers=ADMIN,
                json={"operation": "write", "scope_prefix": "cache/test", "ttl_seconds": 300},
            )
            assert minted.status_code == 201
            headers = {"Authorization": "Capability " + minted.json()["capability_id"]}
            with ThreadPoolExecutor(max_workers=1) as executor:
                upload = executor.submit(
                    client.put, "/objects/cache/test/a", headers=headers, content=b"bytes"
                )
                try:
                    assert store.entered.wait(5)
                    assert client.get("/healthz").status_code == 200
                    denied = client.put("/objects/cache/test/b", headers=headers, content=b"other")
                    assert denied.status_code == 503
                    assert denied.headers["Retry-After"] == "1"
                    assert not upload.done()
                finally:
                    store.release.set()
                assert upload.result(timeout=5).status_code == 201
            assert registry.get_bucket_quota(space="cache").used_bytes == 5
            assert app.state.uploads.active() == 0
            retry = client.put("/objects/cache/test/b", headers=headers, content=b"other")
            assert retry.status_code == 201
            assert registry.get_bucket_quota(space="cache").used_bytes == 10


@pytest.mark.parametrize("budget", ["bucket", "physical", "partition", "count"])
def test_concurrent_pending_reservations_cannot_overbook(
    isolated_dsn: str, monkeypatch: pytest.MonkeyPatch, budget: str
) -> None:
    from asset_store_core.errors import CapacityExceededError, QuotaExceededError

    with PostgresAssetRegistry.connect(isolated_dsn, pool_min_size=2, pool_max_size=2) as registry:
        if budget == "physical":
            monkeypatch.setenv("ASSET_STORE_CAPACITY_BYTES", '{"cache": 100}')
        elif budget == "bucket":
            registry.set_bucket_quota(space="cache", quota_bytes=100)
        else:
            registry.set_partition_quota(
                space="cache",
                partition_id="test",
                quota_bytes=100 if budget == "partition" else None,
                quota_asset_count=1 if budget == "count" else None,
            )
        start = threading.Barrier(2)

        def attempt(name: str) -> str:
            start.wait(timeout=5)
            try:
                asset = registry.reserve_asset(
                    space="cache",
                    partition_id=name if budget in {"bucket", "physical"} else "test",
                    aliases=[name],
                    owner_service_id="bulk-loader",
                    reserved_bytes=60,
                )
                return asset.asset_id
            except (CapacityExceededError, QuotaExceededError):
                return "denied"

        with ThreadPoolExecutor(max_workers=2) as executor:
            jobs = [executor.submit(attempt, name) for name in ("a", "b")]
            results = [job.result(timeout=5) for job in jobs]
        assert results.count("denied") == 1
        assert registry.reserved_upload_bytes("cache") == 60
        assert len(registry.list_assets()) == 1
        assert registry.get_bucket_quota(space="cache").used_bytes == 0
        # A separate registry/pool proves persistence of admission, not local state.
        with PostgresAssetRegistry.connect(isolated_dsn, bootstrap_schema=False) as reopened:
            assert reopened.reserved_upload_bytes("cache") == 60
            with pytest.raises((CapacityExceededError, QuotaExceededError)):
                reopened.reserve_asset(
                    space="cache",
                    partition_id="test",
                    aliases=["c"],
                    owner_service_id="bulk-loader",
                    reserved_bytes=60,
                )


def test_rate_rejection_needs_no_registry_checkout_or_audit(
    isolated_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-030: rate denial remains available while the Postgres pool is saturated."""
    monkeypatch.setenv("ASSET_STORE_CAPABILITY_RATE_BURST", "1")
    monkeypatch.setenv("ASSET_STORE_CAPABILITY_RATE_PER_MINUTE", "1")
    with PostgresAssetRegistry.connect(isolated_dsn, pool_max_size=1, pool_timeout=0.1) as registry:
        held, release = threading.Event(), threading.Event()
        body = {"operation": "write", "scope_prefix": "cache/test", "ttl_seconds": 60}
        app = create_app(registry=registry)
        with TestClient(app) as client:
            first = client.post("/capabilities", headers=ADMIN, json=body)
            assert first.status_code == 201
            before = registry.audit_events

            def hold() -> None:
                with registry.unit_of_work():
                    held.set()
                    assert release.wait(5)

            with ThreadPoolExecutor(max_workers=1) as executor:
                holder = executor.submit(hold)
                try:
                    assert held.wait(3)
                    for _ in range(5):
                        denied = client.post("/capabilities", headers=ADMIN, json=body)
                        assert denied.status_code == 429
                        assert denied.headers["Retry-After"] == "60"
                    assert client.get("/healthz").status_code == 200
                finally:
                    release.set()
                holder.result(timeout=5)
            assert registry.audit_events == before
            assert len(app.state.capabilities) == 1
