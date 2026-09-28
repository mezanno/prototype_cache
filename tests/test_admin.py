"""B-013 / SCN-004 contracts against memory and durable registry adapters."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from asset_store_core.api import create_app
from asset_store_core.models import Asset, AssetState, utcnow
from asset_store_core.registry import InMemoryAssetRegistry
from asset_store_core.registry_base import AssetRegistry
from asset_store_core.service_identity import dev_secret

AUTH = {"Authorization": f"Service admin:{dev_secret('admin')}"}


@pytest.fixture(params=["memory", "postgres"])
def registry(request: pytest.FixtureRequest) -> Iterator[AssetRegistry]:
    if request.param == "memory":
        yield InMemoryAssetRegistry()
        return
    from asset_store_core.pg_registry import PostgresAssetRegistry

    dsn = os.environ.get("ASSET_STORE_PG_DSN")
    if not dsn:
        pytest.skip("set ASSET_STORE_PG_DSN")
    schema = "admin_test_" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            with PostgresAssetRegistry.connect(
                make_conninfo(dsn, options=f"-c search_path={schema}")
            ) as backend:
                yield backend
        finally:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def client(registry: AssetRegistry) -> Iterator[TestClient]:
    with TestClient(create_app(registry=registry), headers=AUTH) as client:
        yield client


def seed(registry: AssetRegistry, name: str = "42/task/a", space: str = "results") -> Asset:
    asset = registry.reserve_asset(
        space=space, partition_id=name.split("/")[0], aliases=[name], owner_service_id="worker"
    )
    return registry.commit_asset(
        asset_id=asset.asset_id, size_bytes=10, checksum="sha256:test", caller_service_id="worker"
    )


def action(client: TestClient, asset: Asset, name: str, **kwargs: Any) -> Any:
    return client.post(
        f"/admin/api/assets/{asset.asset_id}/actions",
        json={"action": name, "expected_updated_at": asset.updated_at.isoformat(), **kwargs},
    )


def test_list_cursor_filters_quota_and_deleted(registry: AssetRegistry, client: TestClient) -> None:
    rows = [seed(registry, f"42/task/{i}") for i in range(3)]
    seed(registry, "420/task/no")
    registry.delete_asset(asset_id=rows[2].asset_id, caller_service_id="admin")
    with registry.asset_lock(rows[2].asset_id) as a:
        registry.lifecycle_update(
            a, state=AssetState.DELETED, now=utcnow(), reason="test", payload_deleted=True
        )
    params: dict[str, Any] = {
        "space": "results",
        "partition_id": "42",
        "prefix": "results/42",
        "limit": 1,
    }
    ids = []
    while True:
        response = client.get("/admin/api/assets", params=params)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["quota"]["used_bytes"] == 20
        assert all("storage_key" not in a for a in data["items"])
        ids += [a["asset_id"] for a in data["items"]]
        if not data["next_cursor"]:
            break
        params["cursor"] = data["next_cursor"]
    assert ids == [a.asset_id for a in rows]
    params["state"] = "pending"
    assert client.get("/admin/api/assets", params=params).status_code == 400
    assert client.get("/admin/api/assets", params={"partition_id": "42"}).status_code == 422
    assert client.get("/admin/api/assets", params={"cursor": "bad!"}).status_code == 400
    assert (
        client.get(
            "/admin/api/assets", params={"created_from": (utcnow() + timedelta(days=1)).isoformat()}
        ).json()["items"]
        == []
    )
    assert (
        client.get("/admin/api/assets", params={"created_from": "2020-01-01T00:00:00"}).status_code
        == 422
    )


def test_lifecycle_restore_quota_conflict_and_audit(
    registry: AssetRegistry, client: TestClient
) -> None:
    asset = seed(registry)
    assert action(client, asset, "expire").status_code == 200
    assert action(client, asset, "delete").status_code == 409
    expired = registry.get_asset(asset.asset_id)
    registry.set_partition_quota(space="results", partition_id="42", quota_bytes=0)
    assert action(client, expired, "ttl", ttl_seconds=100).status_code == 413
    assert registry.get_asset(asset.asset_id).state is AssetState.EXPIRED
    registry.set_partition_quota(space="results", partition_id="42", quota_bytes=100)
    assert action(client, expired, "ttl", ttl_seconds=100).status_code == 200
    assert registry.get_partition_quota(space="results", partition_id="42").used_bytes == 10
    current = registry.get_asset(asset.asset_id)
    assert action(client, current, "ttl", ttl_seconds=366 * 86400).status_code == 400
    assert action(client, current, "delete").status_code == 200
    deleted = registry.get_asset(asset.asset_id)
    assert deleted.payload_deleted_at is None
    assert action(client, deleted, "ttl", ttl_seconds=100).status_code == 409
    data = client.get(f"/admin/api/assets/{asset.asset_id}").json()
    assert any(
        e["action"] == "admin.ttl_set" and e["caller_service_id"] == "admin" for e in data["audit"]
    )
    assert (
        'asset_store_admin_actions_total{action="ttl",outcome="error"}'
        in client.get("/metrics").text
    )


def test_alias_annotations_and_inspection(registry: AssetRegistry, client: TestClient) -> None:
    asset = seed(registry)
    assert action(client, asset, "attach", alias="42/task/second").status_code == 200
    current = registry.get_asset(asset.asset_id)
    assert action(client, current, "attach", alias="42/task/second").status_code == 409
    assert (
        action(
            client, current, "annotations", annotations={"note": "<script>alert(1)</script>"}
        ).status_code
        == 200
    )
    current = registry.get_asset(asset.asset_id)
    assert action(client, current, "detach", alias="42/task/second").status_code == 200
    data = client.get(f"/admin/api/assets/{asset.asset_id}").json()
    assert any(e["action"] == "alias.detach" for e in data["audit"])
    assert (
        action(client, registry.get_asset(asset.asset_id), "detach", alias="42/other").status_code
        == 400
    )
    assert (
        action(
            client, registry.get_asset(asset.asset_id), "eviction", eviction_policy="exempt"
        ).status_code
        == 200
    )


def test_bulk_preview_segment_boundary_stale_and_dedup(
    registry: AssetRegistry, client: TestClient
) -> None:
    first = seed(registry)
    registry.attach_alias(
        asset_id=first.asset_id, alias="42/task/another", mutable=False, caller_service_id="admin"
    )
    second = seed(registry, "42/task/b")
    other = seed(registry, "42/task-other/c")
    url = "/admin/api/aliases/expire?prefix=results/42/task"
    candidates = client.get(url).json()["candidates"]
    assert len(candidates) == 2
    registry.update_annotations(
        asset_id=second.asset_id, patch={"changed": "yes"}, caller_service_id="admin"
    )
    result = client.post(url, json={"candidates": candidates})
    assert result.status_code == 200, result.text
    assert result.json() == {"applied": 1, "skipped": 1}
    assert registry.get_asset(other.asset_id).state is AssetState.AVAILABLE
    assert client.get("/admin/api/aliases/expire?prefix=results").status_code == 400
    assert client.post(url, json={"candidates": [candidates[0], candidates[0]]}).status_code == 400
    assert client.post(url, json={"candidates": candidates}).json() == {"applied": 0, "skipped": 2}


def test_quota_configuration_audited(registry: AssetRegistry, client: TestClient) -> None:
    seed(registry)
    response = client.put(
        "/admin/api/quotas/partition",
        json={
            "space": "results",
            "partition_id": "42",
            "quota_bytes": 100,
            "quota_asset_count": 10,
        },
    )
    assert response.status_code == 200
    assert response.json()["used_bytes"] == 10
    event = registry.audit_events[-1]
    assert event.action == "admin.quota_set" and event.caller_service_id == "admin"
    assert event.before["quota_bytes"] == "None" and event.after["quota_bytes"] == "100"


@pytest.mark.parametrize(
    "path", ["/admin/api/assets", "/admin/api/audit", "/audit", "/quotas/bucket?space=cache"]
)
def test_auth_denies_missing_and_nonadmin(path: str) -> None:
    with TestClient(create_app()) as client:
        assert client.get(path).status_code == 401
        assert (
            client.get(
                path, headers={"Authorization": f"Service worker:{dev_secret('worker')}"}
            ).status_code
            == 403
        )
        assert client.get(path, headers={"Authorization": "Service admin:wrong"}).status_code == 401


def test_legacy_mutation_auth_and_ui_security() -> None:
    with TestClient(create_app()) as client:
        assert (
            client.post("/assets/nope/delete", json={"caller_service_id": "admin"}).status_code
            == 401
        )
        assert (
            client.post(
                "/assets/nope/delete", headers=AUTH, json={"caller_service_id": "worker"}
            ).status_code
            == 403
        )
        page = client.get("/admin")
        assert page.status_code == 200
        assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
        script = client.get("/admin/admin.js")
        assert script.status_code == 200
        assert "innerHTML" not in script.text and "localStorage" not in script.text
        assert client.get("/admin/admin.css").status_code == 200


def test_mutable_detach_revision_and_bounded_history(
    registry: AssetRegistry, client: TestClient
) -> None:
    asset = seed(registry)
    assert action(client, asset, "attach", alias="42/task/mutable", mutable=True).status_code == 200
    before = registry.get_asset(asset.asset_id)
    assert action(client, before, "detach", alias="42/task/mutable").status_code == 200
    assert action(client, before, "expire").status_code == 409
    assert len(registry.recent_audit(asset_id=asset.asset_id, limit=1)) == 1
    event = registry.recent_audit(asset_id=asset.asset_id, limit=1)[0]
    assert event.action == "alias.detach_mutable"
    if hasattr(registry, "unit_of_work"):
        from asset_store_core.pg_registry import PostgresAssetRegistry

        assert isinstance(registry, PostgresAssetRegistry)
        with registry.unit_of_work() as conn:
            schema = conn.execute("SELECT current_schema()").fetchone()
        assert schema is not None
        with PostgresAssetRegistry.connect(
            make_conninfo(
                os.environ["ASSET_STORE_PG_DSN"],
                options=f"-c search_path={schema['current_schema']}",
            ),
            bootstrap_schema=False,
        ) as reopened:
            assert reopened.get_asset(asset.asset_id) == registry.get_asset(asset.asset_id)
            assert reopened.recent_audit(asset_id=asset.asset_id, limit=1) == (event,)


def test_prefix_literals_and_forged_bulk_candidate(
    registry: AssetRegistry, client: TestClient
) -> None:
    matching = seed(registry, "42/percent%/a")
    other = seed(registry, "42/percentX/a")
    response = client.get("/admin/api/assets", params={"prefix": "results/42/percent%"})
    assert [a["asset_id"] for a in response.json()["items"]] == [matching.asset_id]
    result = client.post(
        "/admin/api/aliases/expire",
        params={"prefix": "results/42/percent%"},
        json={
            "candidates": [
                {"asset_id": other.asset_id, "expected_updated_at": other.updated_at.isoformat()}
            ]
        },
    )
    assert result.json() == {"applied": 0, "skipped": 1}


def test_bulk_limit_no_silent_truncation() -> None:
    registry = InMemoryAssetRegistry()
    for i in range(501):
        seed(registry, f"42/task/{i}")
    with TestClient(create_app(registry=registry), headers=AUTH) as client:
        response = client.get("/admin/api/aliases/expire", params={"prefix": "results/42/task"})
        assert response.status_code == 400
        assert "500" in response.json()["detail"]
    assert all(a.state is AssetState.AVAILABLE for a in registry.list_assets())


def test_new_mutation_auth_and_missing_fields() -> None:
    registry = InMemoryAssetRegistry()
    asset = seed(registry)
    with TestClient(create_app(registry=registry)) as client:
        assert action(client, asset, "expire").status_code == 401
        client.headers.update({"Authorization": f"Service worker:{dev_secret('worker')}"})
        assert action(client, asset, "expire").status_code == 403
        client.headers.update(AUTH)
        assert action(client, asset, "ttl").status_code == 400
        assert action(client, asset, "expire", caller_service_id="worker").status_code == 422
    assert registry.get_asset(asset.asset_id).state is AssetState.AVAILABLE


def test_uncommitted_orphan_cannot_be_restored(registry: AssetRegistry, client: TestClient) -> None:
    asset = registry.reserve_asset(
        space="cache", partition_id="demo", aliases=["orphan"], owner_service_id="bulk-loader"
    )
    registry.detach_alias(space="cache", alias="demo/orphan", caller_service_id="admin")
    orphan = registry.get_asset(asset.asset_id)
    assert orphan.state is AssetState.EXPIRED
    assert action(client, orphan, "ttl", ttl_seconds=3600).status_code == 409
    assert registry.get_partition_quota(space="cache", partition_id="demo").used_asset_count == 0


def test_raw_commit_verifies_payload_and_owner(registry: AssetRegistry, client: TestClient) -> None:
    from http_fixtures import stage_payload

    owner = {"Authorization": "Service fetcher:dev-secret:fetcher"}
    reservation = client.post(
        "/assets",
        headers=owner,
        json={
            "space": "cache",
            "partition_id": "review",
            "aliases": [{"name": "raw"}],
            "owner_service_id": "fetcher",
        },
    )
    assert reservation.status_code == 201
    asset_id = reservation.json()["asset_id"]
    body = {"size_bytes": 3, "checksum": "fake", "caller_service_id": "fetcher"}
    url = f"/assets/{asset_id}/commit"
    assert client.post(url, headers=owner, json=body).status_code == 404
    assert registry.get_asset(asset_id).state is AssetState.PENDING
    checksum = stage_payload(client, asset_id, 3)
    assert client.post(url, headers=owner, json=body).status_code == 409
    body["checksum"] = checksum
    body["caller_service_id"] = "bulk-loader"
    assert (
        client.post(
            url, headers={"Authorization": "Service bulk-loader:dev-secret:bulk-loader"}, json=body
        ).status_code
        == 403
    )
    body["caller_service_id"] = "admin"
    assert client.post(url, headers=owner, json=body).status_code == 403
    body["caller_service_id"] = "fetcher"
    assert client.post(url, headers=owner, json=body).status_code == 200
    assert registry.get_partition_quota(space="cache", partition_id="review").used_bytes == 3
    assert registry.audit_events[-1].caller_service_id == "fetcher"
