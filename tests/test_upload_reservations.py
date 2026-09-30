"""ADR-029 / FR-064/066/068: durable pre-PUT byte admission."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from asset_store_core.api import create_app
from asset_store_core.errors import CapacityExceededError, QuotaExceededError, ValidationError
from asset_store_core.models import Asset, AssetState
from asset_store_core.pg_registry import PostgresAssetRegistry
from asset_store_core.registry import InMemoryAssetRegistry
from asset_store_core.registry_base import AssetRegistry


@pytest.fixture(params=["memory", "postgres"])
def registry(request: pytest.FixtureRequest) -> Iterator[AssetRegistry]:
    if request.param == "memory":
        yield InMemoryAssetRegistry()
        return
    dsn = os.environ.get("ASSET_STORE_PG_DSN")
    if not dsn:
        pytest.skip("ASSET_STORE_PG_DSN required")
    schema = "upload_reservations_" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            with PostgresAssetRegistry.connect(
                make_conninfo(dsn, options=f"-c search_path={schema}")
            ) as pg:
                yield pg
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def reserve(registry: AssetRegistry, name: str, size: int | None, partition: str = "test") -> Asset:
    return registry.reserve_asset(
        space="cache",
        partition_id=partition,
        aliases=[name],
        owner_service_id="bulk-loader",
        reserved_bytes=size,
    )


@pytest.mark.parametrize("scope", ["partition", "bucket", "count"])
def test_pending_reservations_prevent_oversubscription(registry: AssetRegistry, scope: str) -> None:
    if scope == "bucket":
        registry.set_bucket_quota(space="cache", quota_bytes=100)
    else:
        registry.set_partition_quota(
            space="cache",
            partition_id="test",
            quota_bytes=100 if scope == "partition" else None,
            quota_asset_count=1 if scope == "count" else None,
        )
    asset = reserve(registry, "a", 60)
    before = registry.audit_events
    with pytest.raises(QuotaExceededError):
        reserve(registry, "b", 50 if scope != "count" else 0)
    assert registry.list_assets() == (asset,)
    assert registry.audit_events == before
    assert registry.reserved_upload_bytes("cache") == 60
    assert registry.get_bucket_quota(space="cache").used_bytes == 0
    assert registry.get_partition_quota(space="cache", partition_id="test").used_asset_count == 0
    committed = registry.commit_asset(
        asset_id=asset.asset_id,
        size_bytes=60,
        checksum="sha256:test",
        caller_service_id="bulk-loader",
    )
    assert committed.state is AssetState.AVAILABLE
    assert committed.reserved_bytes is None
    assert registry.reserved_upload_bytes("cache") == 0
    assert registry.get_bucket_quota(space="cache").used_bytes == 60
    with pytest.raises(QuotaExceededError):
        reserve(registry, "b", 50 if scope != "count" else 0)


def test_physical_capacity_counts_pending_and_commit_once(
    registry: AssetRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ASSET_STORE_CAPACITY_BYTES", '{"cache": 100}')
    asset = reserve(registry, "a", 60)
    with pytest.raises(CapacityExceededError):
        reserve(registry, "b", 40, partition="other")
    registry.commit_asset(
        asset_id=asset.asset_id,
        size_bytes=60,
        checksum="sha256:test",
        caller_service_id="bulk-loader",
    )
    with pytest.raises(CapacityExceededError):
        reserve(registry, "b", 40, partition="other")
    assert reserve(registry, "c", 30, partition="other").reserved_bytes == 30


def test_commit_must_match_reserved_size(registry: AssetRegistry) -> None:
    asset = reserve(registry, "a", 0)
    with pytest.raises(ValidationError, match="match upload reservation"):
        registry.commit_asset(
            asset_id=asset.asset_id,
            size_bytes=1,
            checksum="sha256:test",
            caller_service_id="bulk-loader",
        )
    assert registry.get_asset(asset.asset_id).state is AssetState.PENDING
    registry.commit_asset(
        asset_id=asset.asset_id,
        size_bytes=0,
        checksum="sha256:test",
        caller_service_id="bulk-loader",
    )
    assert registry.get_asset(asset.asset_id).state is AssetState.AVAILABLE


def test_raw_unknown_size_reservation_keeps_legacy_behavior(registry: AssetRegistry) -> None:
    registry.set_partition_quota(space="cache", partition_id="test", quota_bytes=1)
    asset = reserve(registry, "raw", None)
    assert asset.reserved_bytes is None
    with pytest.raises(QuotaExceededError):
        registry.commit_asset(
            asset_id=asset.asset_id,
            size_bytes=5,
            checksum="sha256:test",
            caller_service_id="bulk-loader",
        )


def test_expired_restore_does_not_double_count_physical_bytes(
    registry: AssetRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ASSET_STORE_CAPACITY_BYTES", '{"cache": 100}')
    asset = reserve(registry, "a", 60)
    registry.commit_asset(
        asset_id=asset.asset_id,
        size_bytes=60,
        checksum="sha256:test",
        caller_service_id="bulk-loader",
    )
    registry.expire_asset(asset_id=asset.asset_id, caller_service_id="admin")
    restored = registry.set_asset_ttl(
        asset_id=asset.asset_id, ttl_seconds=60, caller_service_id="admin"
    )
    assert restored.state is AssetState.AVAILABLE
    assert registry.get_bucket_quota(space="cache").used_bytes == 60


def test_reservation_metric_and_audit(registry: AssetRegistry) -> None:
    asset = reserve(registry, "a", 60)
    event = next(e for e in registry.audit_events if e.action == "asset.upload_reserve")
    assert event.target == asset.asset_id
    assert event.caller_service_id == "bulk-loader"
    assert event.after["reserved_bytes"] == "60"
    with TestClient(create_app(registry=registry)) as api:
        assert 'asset_store_reserved_upload_bytes{space="cache"} 60.0' in api.get("/metrics").text
