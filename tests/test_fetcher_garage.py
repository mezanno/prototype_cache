"""B-020 / SCN-007: real origin HTTP, Garage bytes and durable Postgres metadata.

Requires ASSET_STORE_PG_DSN and the variables in deploy/compose/.env.garage.
Missing configuration skips; configured but broken backends fail. Each test owns
a temporary database schema and unique object partition, cleaned up on exit.
"""

from __future__ import annotations

import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from asset_store_core.api import create_app as asset_app
from asset_store_core.pg_registry import PostgresAssetRegistry
from asset_store_core.s3_object_store import S3ObjectStore
from asset_store_core.storage import ObjectStoreLocation
from fetcher_service.app import create_app
from fetcher_service.client import AssetStoreClient
from fetcher_service.fetcher import HttpFetcher
from fetcher_service.rules import HostPassthroughRule, RuleSet

_REQUIRED = (
    "ASSET_STORE_PG_DSN",
    "ASSET_STORE_S3_ENDPOINT",
    "ASSET_STORE_S3_ACCESS_KEY",
    "ASSET_STORE_S3_SECRET_KEY",
)


@pytest.mark.skipif(
    not all(os.environ.get(k) for k in _REQUIRED),
    reason="export Garage credentials and ASSET_STORE_PG_DSN",
)
def test_remote_fetch_cache_refetch_and_restart() -> None:
    """FR-010..015/FR-022: write once, read by capability, compare on refetch."""

    class Origin(BaseHTTPRequestHandler):
        payload = b"remote image bytes"
        calls = 0
        status = 200

        def log_message(self, *args: object) -> None:
            pass

        def do_GET(self) -> None:  # noqa: N802
            Origin.calls += 1
            self.send_response(Origin.status)
            self.send_header("Content-Length", str(len(Origin.payload)))
            self.send_header("Content-Type", "image/jpeg")
            self.end_headers()
            self.wfile.write(Origin.payload)

    partition = f"fetchtest-{uuid.uuid4().hex}"
    schema = f"fetchtest_{uuid.uuid4().hex}"
    dsn = os.environ["ASSET_STORE_PG_DSN"]
    isolated_dsn = make_conninfo(dsn, options=f"-c search_path={schema}")
    store = S3ObjectStore(
        endpoint_url=os.environ["ASSET_STORE_S3_ENDPOINT"],
        region=os.environ.get("ASSET_STORE_S3_REGION", "garage"),
        access_key=os.environ["ASSET_STORE_S3_ACCESS_KEY"],
        secret_key=os.environ["ASSET_STORE_S3_SECRET_KEY"],
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), Origin)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    locations: list[ObjectStoreLocation] = []
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            with PostgresAssetRegistry.connect(isolated_dsn) as registry:
                with TestClient(asset_app(registry=registry, store=store)) as storage:
                    client = AssetStoreClient(storage, service_secret="dev-secret:fetcher")
                    rules = RuleSet(
                        rules=(HostPassthroughRule(host="127.0.0.1", mirror_id=partition),)
                    )
                    app = create_app(
                        asset_store_client=client,
                        rules=rules,
                        fetcher=HttpFetcher(allow_private_hosts=True),
                    )
                    with TestClient(app) as api:
                        body = {"url": f"http://127.0.0.1:{server.server_port}/image.jpg"}
                        first = api.post("/v1/ensure-url", json=body)
                        # Register any committed bytes before assertions, even on failure.
                        resolved = client.resolve(space="cache", alias=f"{partition}/image.jpg")
                        if resolved is not None:
                            locations.append(
                                ObjectStoreLocation(bucket="cache", key=resolved["storage_key"])
                            )
                        assert first.status_code == 200, first.text
                        original = Origin.payload
                        assert store.get_object(locations[0]) == original
                        assert first.json()["cache_hit"] is False
                        assert api.post("/v1/ensure-url", json=body).json()["cache_hit"] is True
                        assert Origin.calls == 1
                        assert (
                            api.post("/v1/ensure-url", json={**body, "no_cache": True}).json()
                            == first.json()
                        )
                        assert Origin.calls == 2
                        audit_count = len(registry.audit_events)
                        Origin.payload = b"changed upstream"
                        mismatch = api.post("/v1/ensure-url", json={**body, "no_cache": True})
                        assert mismatch.status_code == 409
                        Origin.status = 503
                        assert (
                            api.post("/v1/ensure-url", json={**body, "no_cache": True}).status_code
                            == 502
                        )
                        assert len(registry.audit_events) == audit_count
                        assert store.get_object(locations[0]) == original
                        quota = registry.get_partition_quota(space="cache", partition_id=partition)
                        assert quota.used_asset_count == 1
                        assert quota.used_bytes == len(original)
                        assert 'outcome="mismatch"} 1.0' in api.get("/metrics").text

            # New registry connection and app prove the result survives a restart.
            with PostgresAssetRegistry.connect(isolated_dsn) as reopened:
                with TestClient(asset_app(registry=reopened, store=store)) as storage:
                    cap = storage.post(
                        "/capabilities",
                        headers={"Authorization": "Service fetcher:dev-secret:fetcher"},
                        json={
                            "operation": "read",
                            "scope_prefix": f"cache/{partition}",
                            "ttl_seconds": 300,
                            "single_use": False,
                        },
                    )
                    assert cap.status_code == 201
                    read = storage.get(
                        f"/objects/cache/{partition}/image.jpg",
                        headers={"Authorization": f"Capability {cap.json()['capability_id']}"},
                    )
                    assert read.status_code == 200
                    assert read.content == original
                    assert (
                        reopened.resolve_alias(
                            space="cache", alias=f"{partition}/image.jpg"
                        ).asset_id
                        == first.json()["asset_id"]
                    )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            for location in locations:
                store.delete_object(location)
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
