"""B-014 / ADR-020: dry-run safety, retention, eviction and durable cleanup."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from prometheus_client import generate_latest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from asset_store_core.api import create_app
from asset_store_core.errors import (
    AssetDeletedError,
    AssetExpiredError,
    CapacityExceededError,
    InvalidStateTransitionError,
)
from asset_store_core.lifecycle import Action, SweepMetrics, SweepPolicy, plan_sweep, run_sweep
from asset_store_core.models import Asset, AssetState, EvictionPolicy, utcnow
from asset_store_core.object_store import LocalObjectStore, ObjectStoreBackend
from asset_store_core.pg_registry import PostgresAssetRegistry
from asset_store_core.registry import InMemoryAssetRegistry
from asset_store_core.registry_base import AssetRegistry
from asset_store_core.storage import ObjectStoreLocation


@dataclass
class Clock:
    now: datetime


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock(utcnow())
    for module in ("registry", "pg_registry", "guard", "api.app"):
        monkeypatch.setattr(f"asset_store_core.{module}.utcnow", lambda: clock.now)
    return clock


@pytest.fixture(params=["memory", "durable"])
def backend(request: pytest.FixtureRequest) -> Iterator[tuple[AssetRegistry, ObjectStoreBackend]]:
    if request.param == "memory":
        yield InMemoryAssetRegistry(), LocalObjectStore()
        return
    required = (
        "ASSET_STORE_PG_DSN",
        "ASSET_STORE_S3_ENDPOINT",
        "ASSET_STORE_S3_ACCESS_KEY",
        "ASSET_STORE_S3_SECRET_KEY",
    )
    if not all(os.environ.get(key) for key in required):
        pytest.skip("export Garage credentials and ASSET_STORE_PG_DSN")
    from asset_store_core.s3_object_store import S3ObjectStore

    dsn = os.environ["ASSET_STORE_PG_DSN"]
    schema = f"gc_test_{uuid.uuid4().hex}"
    store = S3ObjectStore(
        endpoint_url=os.environ["ASSET_STORE_S3_ENDPOINT"],
        region=os.environ.get("ASSET_STORE_S3_REGION", "garage"),
        access_key=os.environ["ASSET_STORE_S3_ACCESS_KEY"],
        secret_key=os.environ["ASSET_STORE_S3_SECRET_KEY"],
    )
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            with PostgresAssetRegistry.connect(
                make_conninfo(dsn, options=f"-c search_path={schema}")
            ) as registry:
                try:
                    yield registry, store
                finally:
                    for row in registry._conn.execute("SELECT space, storage_key FROM assets"):
                        store.delete_object(
                            ObjectStoreLocation(bucket=row["space"], key=row["storage_key"])
                        )
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def location(asset: Asset) -> ObjectStoreLocation:
    return ObjectStoreLocation(bucket=asset.space, key=asset.storage_key)


def seed(
    backend: tuple[AssetRegistry, ObjectStoreBackend],
    *,
    space: str = "cache",
    size: int = 10,
    ttl: int | None = None,
    exempt: bool = False,
    pending: bool = False,
) -> Asset:
    registry, store = backend
    asset = registry.reserve_asset(
        space=space,
        partition_id="test",
        aliases=[uuid.uuid4().hex],
        owner_service_id="admin",
        ttl_seconds=ttl,
        eviction_policy=EvictionPolicy.EXEMPT if exempt else EvictionPolicy.INHERIT,
    )
    stat = store.put_object(location(asset), b"x" * size)
    if pending:
        return asset
    return registry.commit_asset(
        asset_id=asset.asset_id, size_bytes=size, checksum=stat.checksum, caller_service_id="admin"
    )


def current(registry: AssetRegistry, asset: Asset) -> Asset:
    with registry.asset_lock(asset.asset_id) as result:
        return result


def test_ttl_dry_run_grace_and_idempotent_purge(
    backend: tuple[AssetRegistry, ObjectStoreBackend], clock: Clock
) -> None:
    registry, store = backend
    asset = seed(backend, space="tmp", ttl=60, exempt=True)
    clock.now += timedelta(seconds=61)
    metrics = SweepMetrics()
    snapshot = registry.audit_events
    report = run_sweep(registry, store, now=clock.now, metrics=metrics)
    assert report.candidates == 1 and report.applied == 0
    assert registry.audit_events == snapshot
    assert current(registry, asset).state is AssetState.AVAILABLE
    assert store.get_object(location(asset)) == b"x" * 10
    with pytest.raises(AssetExpiredError):
        registry.resolve_alias(space="tmp", alias=next(iter(asset.aliases)).split("/", 1)[1])
    assert run_sweep(registry, store, now=clock.now, dry_run=False, metrics=metrics).applied == 1
    assert registry.get_partition_quota(space="tmp", partition_id="test").used_bytes == 0
    expired_at = current(registry, asset).expired_at
    clock.now += timedelta(hours=23)
    registry.update_annotations(
        asset_id=asset.asset_id, patch={"note": "edited"}, caller_service_id="admin"
    )
    assert current(registry, asset).expired_at == expired_at
    assert run_sweep(registry, store, now=clock.now, dry_run=False).applied == 0
    clock.now += timedelta(hours=1)
    assert run_sweep(registry, store, now=clock.now, dry_run=False, metrics=metrics).applied == 1
    assert current(registry, asset).state is AssetState.DELETED
    assert store.stat_object(location(asset)) is None
    assert run_sweep(registry, store, now=clock.now, dry_run=False).candidates == 0
    text = generate_latest(metrics.registry).decode()
    assert 'reason="ttl_expired",space="tmp"} 2.0' in text
    with pytest.raises(AssetDeletedError):
        registry.resolve_alias(space="tmp", alias=next(iter(asset.aliases)).split("/", 1)[1])


def test_orphan_and_admin_deleted_cleanup(
    backend: tuple[AssetRegistry, ObjectStoreBackend], clock: Clock
) -> None:
    registry, store = backend
    pending = seed(backend, pending=True)
    deleted = seed(backend)
    registry.delete_asset(asset_id=deleted.asset_id, caller_service_id="admin")
    clock.now += timedelta(days=1)
    assert run_sweep(registry, store, now=clock.now, dry_run=False).applied == 2
    for asset in (pending, deleted):
        assert current(registry, asset).payload_deleted_at == clock.now
        assert store.stat_object(location(asset)) is None


def test_quota_scoring_exempt_and_protected_spaces(
    backend: tuple[AssetRegistry, ObjectStoreBackend], clock: Clock
) -> None:
    registry, store = backend
    large = seed(backend, size=50)
    fresh = seed(backend, size=40)
    protected = seed(backend, size=10, exempt=True)
    users = seed(backend, space="users", size=100)
    results = seed(backend, space="results", size=100)
    clock.now += timedelta(days=2)
    registry.record_read(fresh.asset_id)
    for space in ("cache", "users", "results"):
        registry.set_partition_quota(
            space=space, partition_id="test", quota_bytes=100, eviction_sweep_enabled=True
        )
    report = run_sweep(registry, store, now=clock.now, dry_run=False)
    assert report.applied == 1
    assert current(registry, large).state is AssetState.EXPIRED
    for asset in (fresh, protected, users, results):
        assert current(registry, asset).state is AssetState.AVAILABLE
    assert registry.get_partition_quota(space="cache", partition_id="test").used_bytes == 50
    assert current(registry, fresh).read_count == 1


def test_pressure_schedules_relief_without_overevicting(
    backend: tuple[AssetRegistry, ObjectStoreBackend], clock: Clock
) -> None:
    registry, store = backend
    seed(backend, size=30)
    seed(backend, size=65)
    clock.now += timedelta(days=1)
    policy = SweepPolicy(capacity_bytes={"cache": 100})
    first = run_sweep(registry, store, policy=policy, now=clock.now, dry_run=False)
    assert first.applied == 1
    # Still physically full during grace; the prior expiry counts as scheduled relief.
    assert run_sweep(registry, store, policy=policy, now=clock.now, dry_run=False).applied == 0


def test_exhaustion_and_disabled_partition(
    backend: tuple[AssetRegistry, ObjectStoreBackend], clock: Clock
) -> None:
    registry, store = backend
    seed(backend, size=95, exempt=True)
    policy = SweepPolicy(capacity_bytes={"cache": 100})
    metrics = SweepMetrics()
    report = run_sweep(
        registry, store, policy=policy, now=clock.now, dry_run=False, metrics=metrics
    )
    assert report.exhausted == ("cache",) and report.applied == 0
    assert 'gc_eviction_exhausted{space="cache"} 1.0' in generate_latest(metrics.registry).decode()
    registry.set_partition_quota(
        space="cache", partition_id="test", quota_bytes=100, eviction_sweep_enabled=False
    )
    assert run_sweep(registry, store, now=clock.now).candidates == 0


def test_failed_delete_retains_candidate_for_retry(
    backend: tuple[AssetRegistry, ObjectStoreBackend], clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, store = backend
    asset = seed(backend, pending=True)
    clock.now += timedelta(days=2)
    original = type(store).delete_object

    def fail(self: ObjectStoreBackend, loc: ObjectStoreLocation) -> None:
        raise OSError("simulated backend failure")

    monkeypatch.setattr(type(store), "delete_object", fail)
    metrics = SweepMetrics()
    assert run_sweep(registry, store, now=clock.now, dry_run=False, metrics=metrics).errors == 1
    assert current(registry, asset).state is AssetState.DELETED
    assert current(registry, asset).payload_deleted_at is None
    with pytest.raises(InvalidStateTransitionError):
        registry.commit_asset(
            asset_id=asset.asset_id,
            size_bytes=10,
            checksum="sha256:late",
            caller_service_id="admin",
        )
    monkeypatch.setattr(type(store), "delete_object", original)
    assert run_sweep(registry, store, now=clock.now, dry_run=False).applied == 1


def test_stale_plan_skips_changed_asset(
    backend: tuple[AssetRegistry, ObjectStoreBackend], clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, store = backend
    asset = seed(backend, size=95)
    original = plan_sweep

    def raced(
        reg: AssetRegistry, policy: SweepPolicy, now: datetime
    ) -> tuple[list[Action], set[str], dict[str, float]]:
        plan = original(reg, policy, now)
        reg.set_eviction_policy(
            asset_id=asset.asset_id,
            eviction_policy=EvictionPolicy.EXEMPT,
            caller_service_id="admin",
        )
        return plan

    monkeypatch.setattr("asset_store_core.lifecycle.plan_sweep", raced)
    report = run_sweep(
        registry,
        store,
        now=clock.now,
        dry_run=False,
        policy=SweepPolicy(capacity_bytes={"cache": 100}),
    )
    assert report.skipped == 1 and report.applied == 0


def test_zero_alias_expiry_releases_quota_once(
    backend: tuple[AssetRegistry, ObjectStoreBackend], clock: Clock
) -> None:
    registry, store = backend
    asset = seed(backend)
    registry.detach_alias(
        space="cache", alias=next(iter(asset.aliases)).split("/", 1)[1], caller_service_id="admin"
    )
    assert registry.get_bucket_quota(space="cache").used_bytes == 0
    clock.now += timedelta(days=7)
    assert run_sweep(registry, store, now=clock.now, dry_run=False).applied == 1
    assert registry.get_bucket_quota(space="cache").used_bytes == 0


def test_physical_capacity_counts_expired_bytes(
    backend: tuple[AssetRegistry, ObjectStoreBackend], clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, _ = backend
    old = seed(backend, size=90)
    registry.expire_asset(asset_id=old.asset_id, caller_service_id="admin")
    monkeypatch.setenv("ASSET_STORE_CAPACITY_BYTES", '{"cache":100}')
    with pytest.raises(CapacityExceededError):
        seed(backend, size=5)


def test_http_ttl_and_expired_status(
    backend: tuple[AssetRegistry, ObjectStoreBackend], clock: Clock
) -> None:
    registry, store = backend
    with TestClient(create_app(registry=registry, store=store)) as api:
        cap = api.post(
            "/capabilities",
            headers={"Authorization": "Service worker:dev-secret:worker"},
            json={"operation": "write", "scope_prefix": "results/42/task", "ttl_seconds": 3600},
        ).json()["capability_id"]
        response = api.put(
            "/objects/results/42/task/out",
            params={"ttl_seconds": 60},
            content=b"data",
            headers={"Authorization": f"Capability {cap}"},
        )
        assert response.status_code == 201, response.text
        assert response.json()["expires_at"] is not None
        clock.now += timedelta(seconds=61)
        assert (
            api.get("/resolve", params={"space": "results", "alias": "42/task/out"}).status_code
            == 410
        )
        assert (
            api.put(
                "/objects/results/42/task/bad",
                params={"ttl_seconds": 366 * 86400},
                content=b"bad",
                headers={"Authorization": f"Capability {cap}"},
            ).status_code
            == 400
        )


def test_deleted_payload_retry_after_metadata_failure(
    backend: tuple[AssetRegistry, ObjectStoreBackend], clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, store = backend
    asset = seed(backend, pending=True)
    clock.now += timedelta(days=2)
    original = type(registry).lifecycle_update

    def interrupted(
        self: AssetRegistry,
        asset: Asset,
        *,
        state: AssetState,
        now: datetime,
        reason: str,
        payload_deleted: bool = False,
    ) -> Asset:
        if payload_deleted:
            raise RuntimeError("simulate crash after S3 delete")
        return original(
            self, asset, state=state, now=now, reason=reason, payload_deleted=payload_deleted
        )

    monkeypatch.setattr(type(registry), "lifecycle_update", interrupted)
    assert run_sweep(registry, store, now=clock.now, dry_run=False).errors == 1
    assert store.stat_object(location(asset)) is None
    assert current(registry, asset).state is AssetState.DELETED
    assert current(registry, asset).payload_deleted_at is None
    monkeypatch.setattr(type(registry), "lifecycle_update", original)
    assert run_sweep(registry, store, now=clock.now, dry_run=False).applied == 1


@pytest.mark.parametrize("backend", ["durable"], indirect=True)
def test_postgres_lock_serializes_late_commit(
    backend: tuple[AssetRegistry, ObjectStoreBackend], clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, store = backend
    assert isinstance(registry, PostgresAssetRegistry)
    asset = seed(backend, pending=True)
    clock.now += timedelta(days=2)
    planned = threading.Event()
    original_plan = plan_sweep

    def notify_plan(
        reg: AssetRegistry, policy: SweepPolicy, now: datetime
    ) -> tuple[list[Action], set[str], dict[str, float]]:
        result = original_plan(reg, policy, now)
        planned.set()
        return result

    monkeypatch.setattr("asset_store_core.lifecycle.plan_sweep", notify_plan)
    row = registry._conn.execute("SELECT current_schema() AS name").fetchone()
    assert row is not None
    dsn = make_conninfo(os.environ["ASSET_STORE_PG_DSN"], options=f"-c search_path={row['name']}")
    with PostgresAssetRegistry.connect(dsn, bootstrap_schema=False) as other:
        with ThreadPoolExecutor(max_workers=1) as executor:
            with registry.asset_lock(asset.asset_id):
                future = executor.submit(run_sweep, other, store, now=clock.now, dry_run=False)
                assert planned.wait(5), "sweep did not plan the pending candidate"
                assert not future.done(), "sweep bypassed the upload/commit row lock"
                stat = store.stat_object(location(asset))
                assert stat is not None
                registry.commit_asset(
                    asset_id=asset.asset_id,
                    size_bytes=stat.size_bytes,
                    checksum=stat.checksum,
                    caller_service_id="admin",
                )
            report = future.result(timeout=5)
    assert report.applied == 0 and report.skipped == 1
    assert current(registry, asset).state is AssetState.AVAILABLE
    assert store.stat_object(location(asset)) is not None


def test_capacity_http_retry_after(
    backend: tuple[AssetRegistry, ObjectStoreBackend], monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, store = backend
    monkeypatch.setenv("ASSET_STORE_CAPACITY_BYTES", '{"cache":10}')
    with TestClient(create_app(registry=registry, store=store)) as api:
        pending = api.post(
            "/assets",
            json={
                "space": "cache",
                "partition_id": "test",
                "aliases": [{"name": "capacity"}],
                "owner_service_id": "admin",
            },
        )
        assert pending.status_code == 201
        response = api.post(
            f"/assets/{pending.json()['asset_id']}/commit",
            json={"size_bytes": 10, "checksum": "sha256:x", "caller_service_id": "admin"},
        )
        assert response.status_code == 503
        assert response.headers["Retry-After"] == "60"


def test_retention_defaults_and_configured_maximum(
    backend: tuple[AssetRegistry, ObjectStoreBackend], clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, _ = backend
    for space, days in (("tmp", 1), ("results", 365), ("cache", 0), ("users", 0)):
        asset = seed(backend, space=space)
        assert asset.expires_at == (clock.now + timedelta(days=days) if days else None)
    monkeypatch.setenv("ASSET_STORE_RESULTS_MAX_TTL_SECONDS", "120")
    result = seed(backend, space="results")
    assert result.expires_at == clock.now + timedelta(seconds=120)
    assert registry.resolve_alias(
        space="results", alias=next(iter(result.aliases)).split("/", 1)[1]
    )


def test_access_tracking_and_presign_ttl(
    backend: tuple[AssetRegistry, ObjectStoreBackend], clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from asset_store_core.capabilities import Capability, Operation
    from asset_store_core.guard import StorageGuard

    registry, store = backend
    asset = seed(backend, ttl=60)
    cap = Capability(
        capability_id="read-cap",
        operation=Operation.READ,
        scope_prefix="cache/test",
        expires_at=clock.now + timedelta(hours=1),
        caller_service_id="worker",
        single_use=False,
    )
    guard = StorageGuard(registry, store)
    alias = next(iter(asset.aliases))
    assert guard.read_bytes(capability=cap, alias=alias) == b"x" * 10
    assert current(registry, asset).read_count == 1
    assert current(registry, asset).last_read_at == clock.now

    def presign(self: ObjectStoreBackend, loc: ObjectStoreLocation, *, expires_in: int) -> str:
        assert expires_in == 60
        return "https://signed.invalid/object"

    monkeypatch.setattr(type(store), "presign_get_url", presign)
    result = guard.presign_read(capability=cap, alias=alias, expires_in=300)
    assert result.expires_in == 60
    assert current(registry, asset).read_count == 2


@pytest.mark.parametrize("backend", ["durable"], indirect=True)
def test_cli_defaults_to_dry_run_then_applies(
    backend: tuple[AssetRegistry, ObjectStoreBackend], clock: Clock, tmp_path: Path
) -> None:
    registry, store = backend
    assert isinstance(registry, PostgresAssetRegistry)
    clock.now -= timedelta(days=2)
    asset = seed(backend, pending=True)
    row = registry._conn.execute("SELECT current_schema() AS name").fetchone()
    assert row is not None
    env = {
        **os.environ,
        "ASSET_STORE_PG_DSN": make_conninfo(
            os.environ["ASSET_STORE_PG_DSN"], options=f"-c search_path={row['name']}"
        ),
    }
    command = [sys.executable, "-m", "asset_store_core.lifecycle"]
    before = registry.audit_events
    preview = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20)
    assert preview.returncode == 0, preview.stderr
    assert json.loads(preview.stdout)["dry_run"] is True
    assert json.loads(preview.stdout)["candidates"] == 1
    assert registry.audit_events == before
    assert store.stat_object(location(asset)) is not None
    metrics_path = tmp_path / "lifecycle.prom"
    applied = subprocess.run(
        command + ["--apply", "--metrics-file", str(metrics_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert applied.returncode == 0, applied.stderr
    assert json.loads(applied.stdout)["applied"] == 1
    assert current(registry, asset).state is AssetState.DELETED
    assert store.stat_object(location(asset)) is None
    assert 'reason="orphan",space="cache"} 1.0' in metrics_path.read_text()
