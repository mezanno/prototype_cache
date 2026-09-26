"""B-012 acceptance: scoped reads, verified result copies and manifest-last failure semantics."""

from __future__ import annotations

import json
import os
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import httpx
import psycopg
import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo
from pydantic import ValidationError

from asset_store_core.api import create_app
from asset_store_core.pg_registry import PostgresAssetRegistry
from asset_store_core.s3_object_store import S3ObjectStore
from asset_store_core.storage import ObjectStoreLocation

_TOOL_DIR = Path(__file__).resolve().parent.parent / "tools" / "worker-sim"
sys.path.insert(0, str(_TOOL_DIR))
import worker_sim  # noqa: E402

SECRET = "dev-secret:worker"
PREFIX = "results/42/task-1/attempt-1/worker-1"


@pytest.fixture(params=["memory", "durable"])
def client(request: pytest.FixtureRequest) -> Iterator[TestClient]:
    """Same acceptance tests on local adapters and isolated Postgres + Garage."""
    if request.param == "memory":
        with TestClient(create_app()) as http:
            yield http
        return
    required = (
        "ASSET_STORE_PG_DSN",
        "ASSET_STORE_S3_ENDPOINT",
        "ASSET_STORE_S3_ACCESS_KEY",
        "ASSET_STORE_S3_SECRET_KEY",
    )
    if not all(os.environ.get(k) for k in required):
        pytest.skip("export Garage credentials and ASSET_STORE_PG_DSN")
    schema = f"worker_test_{uuid.uuid4().hex}"
    dsn = os.environ["ASSET_STORE_PG_DSN"]
    isolated = make_conninfo(dsn, options=f"-c search_path={schema}")
    store = S3ObjectStore(
        endpoint_url=os.environ["ASSET_STORE_S3_ENDPOINT"],
        region=os.environ.get("ASSET_STORE_S3_REGION", "garage"),
        access_key=os.environ["ASSET_STORE_S3_ACCESS_KEY"],
        secret_key=os.environ["ASSET_STORE_S3_SECRET_KEY"],
    )
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            with PostgresAssetRegistry.connect(isolated) as registry:
                try:
                    with TestClient(create_app(registry=registry, store=store)) as http:
                        yield http
                finally:
                    # Only objects registered in this test's isolated schema.
                    for row in registry._conn.execute("SELECT space, storage_key FROM assets"):
                        store.delete_object(
                            ObjectStoreLocation(bucket=row["space"], key=row["storage_key"])
                        )
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def seed(client: httpx.Client, alias: str = "cache/demo/input.bin", data: bytes = b"hello") -> str:
    cap = client.post(
        "/capabilities",
        headers={"Authorization": "Service admin:dev-secret:admin"},
        json={"operation": "write", "scope_prefix": alias, "ttl_seconds": 300, "single_use": False},
    )
    assert cap.status_code == 201
    from urllib.parse import quote

    response = client.put(
        f"/objects/{quote(alias, safe='/')}",
        content=data,
        headers={"Authorization": f"Capability {cap.json()['capability_id']}"},
    )
    assert response.status_code == 201
    checksum: str = response.json()["checksum"]
    return checksum


def task(checksum: str, *, prefix: str | None = PREFIX) -> worker_sim.Task:
    return worker_sim.Task(
        inputs=[worker_sim.InputAsset(alias="cache/demo/input.bin", checksum=checksum)],
        result_prefix=prefix,
    )


def read_result(client: httpx.Client, alias: str) -> httpx.Response:
    cap = client.post(
        "/capabilities",
        headers={"Authorization": f"Service worker:{SECRET}"},
        json={"operation": "read", "scope_prefix": PREFIX, "ttl_seconds": 300, "single_use": False},
    )
    return client.get(
        f"/objects/{alias}", headers={"Authorization": f"Capability {cap.json()['capability_id']}"}
    )


@pytest.mark.parametrize("input_count", [1, 2])
def test_task_roundtrip_and_observability(client: TestClient, input_count: int) -> None:
    checksum = seed(client)
    events: list[dict[str, object]] = []
    spec = task(checksum)
    spec.inputs *= input_count
    report = worker_sim.run_task(client, spec, service_secret=SECRET, emit=events.append)
    assert report.status == "ok"
    assert report.reads == report.writes == input_count
    assert report.bytes_read == report.bytes_written == 5 * input_count
    assert report.manifest_written
    assert report.elapsed_seconds >= report.read_seconds > 0
    assert [e["event"] for e in events] == ["worker.read", "worker.write"] * input_count + [
        "worker.manifest"
    ]
    assert all(e["correlation_id"] == report.correlation_id for e in events)
    assert read_result(client, f"{PREFIX}/output-0001.bin").content == b"hello"
    manifest = read_result(client, f"{PREFIX}/manifest.json").json()
    assert manifest["version"] == 1
    assert len(manifest["outputs"]) == input_count
    output = manifest["outputs"][0]
    assert output["checksum"] == checksum
    assert output["source_alias"] == "cache/demo/input.bin"
    assert output["size_bytes"] == 5
    committed = client.get(
        "/audit",
        headers={"Authorization": "Service admin:dev-secret:admin"},
        params={"action": "asset.commit", "caller_service_id": "worker"},
    ).json()
    assert len(committed) == input_count + 1
    assert committed[0]["target"] == output["asset_id"]
    grants = client.get(
        "/audit",
        headers={"Authorization": "Service admin:dev-secret:admin"},
        params={"action": "capability.issue", "caller_service_id": "worker"},
    ).json()
    assert grants[0]["target"] == PREFIX
    assert grants[1]["target"] == "cache/demo/input.bin"


@pytest.mark.parametrize(
    "alias", ["cache/demo/input.bin", "users/42/in?x=1", "tmp/task-1/input.bin"]
)
def test_read_only(client: TestClient, alias: str) -> None:
    checksum = seed(client, alias)
    spec = worker_sim.Task(inputs=[worker_sim.InputAsset(alias=alias, checksum=checksum)])
    report = worker_sim.run_task(client, spec, service_secret=SECRET)
    assert report.status == "ok"
    assert report.reads == 1 and report.writes == 0
    assert not report.manifest_written


def test_checksum_failure_has_no_outputs(client: TestClient) -> None:
    seed(client)
    report = worker_sim.run_task(client, task("sha256:" + "0" * 64), service_secret=SECRET)
    assert report.status == "failed" and report.error == "input checksum mismatch"
    assert report.writes == 0 and not report.manifest_written
    assert read_result(client, f"{PREFIX}/manifest.json").status_code == 404


def test_partial_failure_does_not_publish_manifest(client: TestClient) -> None:
    checksum = seed(client)
    spec = task(checksum)
    spec.inputs.append(worker_sim.InputAsset(alias="cache/demo/missing.bin", checksum=checksum))
    report = worker_sim.run_task(client, spec, service_secret=SECRET)
    assert report.status == "failed" and report.error == "HTTP 404"
    assert report.writes == 1 and not report.manifest_written
    assert read_result(client, f"{PREFIX}/output-0001.bin").content == b"hello"
    assert read_result(client, f"{PREFIX}/manifest.json").status_code == 404


def test_repeated_attempt_conflicts(client: TestClient) -> None:
    checksum = seed(client)
    first = worker_sim.run_task(client, task(checksum), service_secret=SECRET)
    second = worker_sim.run_task(client, task(checksum), service_secret=SECRET)
    assert first.status == "ok"
    assert second.status == "failed" and second.error == "HTTP 409"
    assert second.writes == 0 and not second.manifest_written


def test_wrong_secret_denied(client: TestClient) -> None:
    report = worker_sim.run_task(client, task("sha256:" + "0" * 64), service_secret="sensitive")
    assert report.status == "failed" and report.error == "HTTP 401"
    assert report.reads == report.writes == 0


def test_quota_failure_no_manifest(client: TestClient) -> None:
    checksum = seed(client)
    assert (
        client.put(
            "/quotas/partition",
            headers={"Authorization": "Service admin:dev-secret:admin"},
            json={"space": "results", "partition_id": "42", "quota_bytes": 0},
        ).status_code
        == 200
    )
    report = worker_sim.run_task(client, task(checksum), service_secret=SECRET)
    assert report.status == "failed" and report.error == "HTTP 413"
    assert report.writes == 0 and not report.manifest_written


@pytest.mark.parametrize(
    "prefix",
    [
        "cache/42/task/attempt/worker",
        "results/42",
        "results/42/task/../worker",
        "results/42/task/attempt/worker/",
    ],
)
def test_invalid_result_scope(prefix: str) -> None:
    with pytest.raises(ValidationError):
        task("sha256:" + "0" * 64, prefix=prefix)


def test_input_size_limit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    checksum = seed(client)
    monkeypatch.setattr(worker_sim, "MAX_INPUT_BYTES", 4)
    report = worker_sim.run_task(client, task(checksum), service_secret=SECRET)
    assert report.status == "failed" and report.writes == 0


def test_transport_error_is_sanitized() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret token in url", request=request)

    with httpx.Client(base_url="http://test", transport=httpx.MockTransport(fail)) as client:
        report = worker_sim.run_task(client, task("sha256:" + "0" * 64), service_secret=SECRET)
    assert report.error == "HTTP transport failure"


def test_manifest_failure_is_not_retried(client: TestClient) -> None:
    checksum = seed(client)
    attempts = 0
    correlation_ids: set[str] = set()

    def route(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        correlation_ids.add(request.headers["X-Correlation-Id"])
        if request.url.path.endswith("/manifest.json"):
            attempts += 1
            return httpx.Response(503)
        return cast(
            httpx.Response,
            client.request(
                request.method, str(request.url), headers=request.headers, content=request.read()
            ),
        )

    with httpx.Client(base_url="http://testserver", transport=httpx.MockTransport(route)) as proxy:
        report = worker_sim.run_task(proxy, task(checksum), service_secret=SECRET)
    assert report.status == "failed" and report.error == "HTTP 503"
    assert report.writes == 1 and not report.manifest_written
    assert attempts == 1
    assert correlation_ids == {report.correlation_id}
    assert read_result(client, f"{PREFIX}/manifest.json").status_code == 404


def test_read_scope_denied(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    checksum = seed(client)
    original_mint = worker_sim._mint

    def wrong_scope(
        http: httpx.Client, secret: str, operation: str, scope: str, correlation_id: str
    ) -> str:
        return original_mint(
            http,
            secret,
            operation,
            "cache/other/input.bin" if operation == "read" else scope,
            correlation_id,
        )

    monkeypatch.setattr(worker_sim, "_mint", wrong_scope)
    report = worker_sim.run_task(client, task(checksum), service_secret=SECRET)
    assert report.status == "failed" and report.error == "HTTP 403"
    assert report.reads == report.writes == 0


def test_expired_input(client: TestClient) -> None:
    checksum = seed(client)
    asset = client.get("/resolve", params={"space": "cache", "alias": "demo/input.bin"}).json()
    response = client.post(
        f"/assets/{asset['asset_id']}/expire",
        headers={"Authorization": "Service admin:dev-secret:admin"},
        json={"caller_service_id": "admin"},
    )
    assert response.status_code == 200
    report = worker_sim.run_task(client, task(checksum), service_secret=SECRET)
    assert report.status == "failed" and report.error == "HTTP 410"
    assert report.writes == 0


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"inputs": []},
        {"inputs": [{"alias": "../bad", "checksum": "x"}]},
        {"inputs": [], "secret": "not allowed"},
    ],
)
def test_invalid_task(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        worker_sim.Task.model_validate(body)


def test_malformed_service_response() -> None:
    with httpx.Client(
        base_url="http://testserver",
        transport=httpx.MockTransport(lambda request: httpx.Response(201, json={})),
    ) as client:
        report = worker_sim.run_task(client, task("sha256:" + "0" * 64), service_secret=SECRET)
    assert report.status == "failed" and report.error == "invalid asset-store response"


def test_cli_success_and_error_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = TestClient(create_app())
    checksum = seed(api)
    path = tmp_path / "task.json"
    path.write_text(task(checksum).model_dump_json())
    monkeypatch.setenv("WORKER_SIM_SERVICE_SECRET", SECRET)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: api)
    result = CliRunner().invoke(worker_sim.main, ["--task", str(path)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["manifest_written"] is True
    assert SECRET not in result.output and "cap-" not in result.output
    failed = CliRunner().invoke(worker_sim.main, ["--task", str(path)])
    assert failed.exit_code == 1
    assert json.loads(failed.stdout)["error"] == "HTTP 409"
    path.write_text('{"inputs": []}')
    invalid = CliRunner().invoke(worker_sim.main, ["--task", str(path)])
    assert invalid.exit_code != 0
