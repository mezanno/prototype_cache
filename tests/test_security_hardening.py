"""Negative regression tests for B-018 / ADR-022 bounded fixes."""

from __future__ import annotations

import hashlib
import ipaddress
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from asset_store_core.api import create_app, create_app_from_env
from asset_store_core.errors import ServiceAuthError, ValidationError
from asset_store_core.service_identity import ServiceCredentialStore
from fetcher_service.app import create_app as fetcher_app
from fetcher_service.client import AssetStoreClient
from fetcher_service.fetcher import HttpFetcher, SyntheticFetcher, _is_blocked_ip
from fetcher_service.rules import RuleSet


def auth(identity: str) -> dict[str, str]:
    return {"Authorization": f"Service {identity}:dev-secret:{identity}"}


def test_fail_closed_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError):
        ServiceCredentialStore.from_env({})
    for key in [
        "ASSET_STORE_DEV_MODE",
        "ASSET_STORE_SERVICE_CREDENTIALS",
        "ASSET_STORE_S3_ENDPOINT",
        "ASSET_STORE_PG_DSN",
    ]:
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValidationError):
        create_app()
    with pytest.raises(ValidationError):
        create_app_from_env()
    with pytest.raises(ValidationError):
        fetcher_app()


def test_unicode_credentials_reject_without_server_error() -> None:
    store = ServiceCredentialStore({"worker": "test"})
    with pytest.raises(ServiceAuthError):
        store.authenticate("worker", "\u2603")
    with pytest.raises(ValidationError) as exc:
        ServiceCredentialStore.from_env(
            {"ASSET_STORE_SERVICE_CREDENTIALS": "secret-material-without-colon"}
        )
    assert "secret-material" not in str(exc.value)


def test_control_plane_requires_identity_and_bucket_permission() -> None:
    with TestClient(create_app()) as client:
        body = {
            "space": "cache",
            "partition_id": "test",
            "aliases": [{"name": "a"}],
            "owner_service_id": "bulk-loader",
        }
        assert client.post("/assets", json=body).status_code == 401
        assert (
            client.post(
                "/assets/nope/commit",
                json={"size_bytes": 0, "checksum": "fake", "caller_service_id": "admin"},
            ).status_code
            == 401
        )
        assert (
            client.get("/resolve", params={"space": "cache", "alias": "test/a"}).status_code == 401
        )
        assert client.post("/assets", headers=auth("worker"), json=body).status_code == 403
        body["owner_service_id"] = "worker"
        assert client.post("/assets", headers=auth("worker"), json=body).status_code == 403
        assert (
            client.get(
                "/resolve", params={"space": "users", "alias": "42/a"}, headers=auth("fetcher")
            ).status_code
            == 403
        )


def test_bearer_redacted_from_audit_and_errors() -> None:
    app = create_app()
    with TestClient(app) as client:
        token = client.post(
            "/capabilities",
            headers=auth("worker"),
            json={"operation": "write", "scope_prefix": "results/42", "ttl_seconds": 60},
        ).json()["capability_id"]
        audit = client.get("/audit", headers=auth("admin"))
        assert token not in audit.text
        assert (
            audit.json()[-1]["after"]["capability_fingerprint"]
            == hashlib.sha256(token.encode()).hexdigest()
        )
        denied = client.put(
            "/objects/results/43/out",
            headers={"Authorization": "Capability " + token},
            content=b"x",
        )
        assert denied.status_code == 403
        assert token not in denied.text


def test_upload_limit_and_authorization_before_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSET_STORE_MAX_UPLOAD_BYTES", "4")
    app = create_app()
    with TestClient(app) as client:
        token = client.post(
            "/capabilities",
            headers=auth("worker"),
            json={"operation": "write", "scope_prefix": "results/42", "ttl_seconds": 60},
        ).json()["capability_id"]
        headers = {"Authorization": "Capability " + token}
        assert (
            client.put("/objects/results/42/large", headers=headers, content=b"12345").status_code
            == 413
        )
        assert (
            client.put(
                "/objects/results/42/chunks", headers=headers, content=iter([b"123", b"45"])
            ).status_code
            == 413
        )
        consumed = []

        def chunks() -> Iterator[bytes]:
            consumed.append(True)
            yield b"12345"

        assert (
            client.put("/objects/results/43/denied", headers=headers, content=chunks()).status_code
            == 403
        )
        assert not consumed
        assert not app.state.registry.list_assets()
        assert (
            client.put("/objects/results/42/ok", headers=headers, content=b"1234").status_code
            == 201
        )


def test_fetcher_ingress_auth() -> None:
    with TestClient(create_app()) as storage:
        client = AssetStoreClient(storage, service_secret="dev-secret:fetcher")
        app = fetcher_app(
            asset_store_client=client, rules=RuleSet(rules=()), fetcher=SyntheticFetcher()
        )
        with TestClient(app) as api:
            body = {"url": "https://example.test/content", "tmp_id": "test"}
            assert api.post("/v1/ensure-url", json=body).status_code == 401
            assert api.post("/v1/ensure-url", headers=auth("worker"), json=body).status_code == 403
            assert 'fetcher_ingress_auth_total{outcome="denied"} 2.0' in api.get("/metrics").text
            assert (
                api.post("/v1/ensure-url", headers=auth("task-api"), json=body).status_code == 200
            )


@pytest.mark.parametrize(
    "address", ["100.64.0.1", "127.0.0.1", "169.254.169.254", "::1", "fc00::1", "224.0.0.1"]
)
def test_nonpublic_destinations_rejected(address: str) -> None:
    assert _is_blocked_ip(ipaddress.ip_address(address))


def test_fetcher_disables_environment_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    fetcher = HttpFetcher()
    assert fetcher._client.trust_env is False
    fetcher._client.close()


def test_correlation_id_sanitized() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/healthz", headers={"X-Correlation-Id": "bad/id"})
        assert response.status_code == 200
        assert response.headers["X-Correlation-Id"] != "bad/id"
        response = client.get("/healthz", headers={"X-Correlation-Id": "a" * 129})
        assert len(response.headers["X-Correlation-Id"]) == 32
