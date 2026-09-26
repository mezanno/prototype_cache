"""Disposable B-018 probes; synthetic bytes, isolated database schema."""

import ipaddress
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlsplit

import httpx
import psycopg
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from asset_store_core.api import create_app
from asset_store_core.capabilities import Capability, Operation
from asset_store_core.guard import StorageGuard
from asset_store_core.models import utcnow
from asset_store_core.object_store import LocalObjectStore
from asset_store_core.pg_registry import PostgresAssetRegistry
from asset_store_core.registry import InMemoryAssetRegistry
from asset_store_core.s3_object_store import S3ObjectStore
from asset_store_core.service_identity import ServiceCredentialStore
from asset_store_core.storage import ObjectStoreLocation
from fetcher_service.app import create_app as fetcher_app
from fetcher_service.client import AssetStoreClient
from fetcher_service.config import load_rule_set
from fetcher_service.fetcher import HttpFetcher, SyntheticFetcher, _is_blocked_ip
from fetcher_service.rules import RuleSet

# These probes intentionally demonstrate vulnerabilities in disposable fixtures.
# Refuse non-loopback backends rather than risking an operator database or store.
if conninfo_to_dict(os.environ.get("ASSET_STORE_PG_DSN", "")).get("host") not in {
    "127.0.0.1",
    "localhost",
    "::1",
}:
    raise SystemExit("Use an explicitly configured loopback ASSET_STORE_PG_DSN")
if urlsplit(os.environ.get("ASSET_STORE_S3_ENDPOINT", "")).hostname not in {
    "127.0.0.1",
    "localhost",
    "::1",
}:
    raise SystemExit("Use an explicitly configured loopback ASSET_STORE_S3_ENDPOINT")

results = {}
registry = InMemoryAssetRegistry()
store = LocalObjectStore()
credentials = ServiceCredentialStore(
    {"admin": "review-admin", "fetcher": "review-fetcher", "worker": "review-worker"}
)
app = create_app(registry=registry, store=store, credentials=credentials)
with TestClient(app) as client:
    reserve = client.post(
        "/assets",
        json={
            "space": "users",
            "partition_id": "victim",
            "aliases": [{"name": "forged"}],
            "owner_service_id": "admin",
        },
    )
    asset_id = reserve.json()["asset_id"]
    commit = client.post(
        f"/assets/{asset_id}/commit",
        json={"size_bytes": 0, "checksum": "invented", "caller_service_id": "admin"},
    )
    lookup = client.get("/resolve", params={"space": "users", "alias": "victim/forged"})
    results["unauthenticated_control_plane"] = {
        "reserve_status": reserve.status_code,
        "commit_status": commit.status_code,
        "resolve_status": lookup.status_code,
        "state": lookup.json()["state"],
        "claimed_checksum": lookup.json()["checksum"],
        "audit_actor": registry.audit_events[-1].caller_service_id,
    }
    mint = client.post(
        "/capabilities",
        headers={"Authorization": "Service worker:review-worker"},
        json={"operation": "write", "scope_prefix": "results/42", "ttl_seconds": 60},
    )
    token = mint.json()["capability_id"]
    results["audit_contains_live_bearer"] = (
        registry.audit_events[-1].after.get("capability_id") == token
    )
    registry.set_partition_quota(space="results", partition_id="42", quota_bytes=0)
    rejected = client.put(
        "/objects/results/42/rejected",
        headers={"Authorization": "Capability " + token},
        content=b"review-only",
    )
    pending = [a for a in registry.list_assets() if a.space == "results"][0]
    location = ObjectStoreLocation.for_asset(
        space=pending.space, partition_id=pending.partition_id, asset_id=pending.asset_id
    )
    results["quota_rejection_leaves_bytes"] = {
        "status": rejected.status_code,
        "state": pending.state.value,
        "metadata_size": pending.size_bytes,
        "stored_size": len(store.get_object(location)),
    }
    fetch_client = AssetStoreClient(client, service_secret="review-fetcher")
    with TestClient(
        fetcher_app(
            asset_store_client=fetch_client, rules=RuleSet(rules=()), fetcher=SyntheticFetcher()
        )
    ) as fc:
        response = fc.post(
            "/v1/ensure-url",
            json={
                "url": "https://example.test/file",
                "tmp_id": "victim",
                "preferred_alias_suffix": "chosen",
            },
        )
        results["unauthenticated_fetcher"] = {
            "status": response.status_code,
            "alias": response.json()["qualified_alias"],
        }
with TestClient(create_app()) as client:
    results["default_admin_credential_status"] = client.get(
        "/admin/api/assets", headers={"Authorization": "Service admin:dev-secret:admin"}
    ).status_code

ip = ipaddress.ip_address("100.64.0.1")
results["ssrf_shared_address_range"] = {"is_global": ip.is_global, "blocked": _is_blocked_ip(ip)}
# No sockets contacted: observe that transport still receives a hostname after preflight DNS.
seen = []
with patch(
    "fetcher_service.fetcher.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("8.8.8.8", 80))]
):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: seen.append(request.url.host) or httpx.Response(200, content=b"x")
        )
    ) as hc:
        HttpFetcher(client=hc).fetch("http://rebind.example.test/data")
results["transport_receives_unpinned_hostname"] = seen == ["rebind.example.test"]
load_rule_set("""[[rule]]
type="regex"
host="example.test"
mirror_id="test"
path_match='^(?P<id>(a+)+)$'
alias_template="{id}"
""")
results["nested_quantifier_rule_accepted"] = True

# Seed two committed assets in an isolated schema; no existing rows are touched.
dsn = os.environ["ASSET_STORE_PG_DSN"]
schema = "security_review_" + uuid.uuid4().hex
with psycopg.connect(dsn, autocommit=True) as admin:
    admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        with PostgresAssetRegistry.connect(
            make_conninfo(dsn, options=f"-c search_path={schema}")
        ) as pg:
            assets = []
            for name in ["first", "second"]:
                a = pg.reserve_asset(
                    space="cache", partition_id="review", aliases=[name], owner_service_id="admin"
                )
                assets.append(
                    pg.commit_asset(
                        asset_id=a.asset_id,
                        size_bytes=1,
                        checksum="sha256:fixture",
                        caller_service_id="admin",
                    )
                )
            entered = threading.Event()
            updated = threading.Event()

            def outer():
                try:
                    with pg.asset_lock(assets[0].asset_id):
                        entered.set()
                        assert updated.wait(5)
                        raise RuntimeError("intentional rollback")
                except RuntimeError:
                    pass

            def inner():
                assert entered.wait(5)
                pg.update_annotations(
                    asset_id=assets[1].asset_id,
                    patch={"acknowledged": "yes"},
                    caller_service_id="admin",
                )
                updated.set()
                return True

            with ThreadPoolExecutor(max_workers=2) as pool:
                a = pool.submit(outer)
                b = pool.submit(inner)
                acknowledged = b.result(timeout=10)
                a.result(timeout=10)
            results["shared_connection_rollback"] = {
                "other_operation_returned_success": acknowledged,
                "annotation_persisted": "acknowledged"
                in pg.get_asset(assets[1].asset_id).annotations,
            }
    finally:
        admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

# Real Garage signed URL; only a fresh uniquely named test object is created/deleted.

s3 = S3ObjectStore(
    endpoint_url=os.environ["ASSET_STORE_S3_ENDPOINT"],
    region=os.environ.get("ASSET_STORE_S3_REGION", "garage"),
    access_key=os.environ["ASSET_STORE_S3_ACCESS_KEY"],
    secret_key=os.environ["ASSET_STORE_S3_SECRET_KEY"],
)
r = InMemoryAssetRegistry()
guard = StorageGuard(r, s3)
alias = "cache/security-review-" + uuid.uuid4().hex + "/probe"
write = Capability(
    "probe-write", Operation.WRITE, alias, utcnow() + timedelta(minutes=2), "bulk-loader"
)
read = Capability("probe-read", Operation.READ, alias, utcnow() + timedelta(minutes=2), "worker")
asset = guard.write_object(capability=write, alias=alias, data=b"disposable security review bytes")
location = ObjectStoreLocation.for_asset(
    space=asset.space, partition_id=asset.partition_id, asset_id=asset.asset_id
)
try:
    signed = guard.presign_read(capability=read, alias=alias, expires_in=60)
    r.expire_asset(asset_id=asset.asset_id, caller_service_id="admin")
    response = httpx.get(signed.url, timeout=10)
    results["presigned_get_after_expire"] = {
        "status": response.status_code,
        "payload_matches": response.content == b"disposable security review bytes",
    }
finally:
    s3.delete_object(location)
print(json.dumps(results, indent=2, sort_keys=True))
