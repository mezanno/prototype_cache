"""Forced refetch preserves immutable assets (B-020, R-011, FR-022)."""

import logging

import pytest
from fastapi.testclient import TestClient

from asset_store_core.api import create_app as asset_app
from fetcher_service.app import create_app
from fetcher_service.client import AssetStoreClient
from fetcher_service.errors import UpstreamError, UpstreamTimeoutError
from fetcher_service.fetcher import FetchedContent
from fetcher_service.rules import HostPassthroughRule, RuleSet


class MutableOrigin:
    data = b"original"
    calls = 0
    error: Exception | None = None

    def fetch(self, url: str) -> FetchedContent:
        self.calls += 1
        if self.error:
            raise self.error
        return FetchedContent(data=self.data, mime="application/octet-stream")


@pytest.mark.parametrize("cacheable", [True, False])
def test_refetch_preserves_asset_and_reports_mismatch(
    cacheable: bool, caplog: pytest.LogCaptureFixture
) -> None:
    store = asset_app()
    origin = MutableOrigin()
    rules = RuleSet(
        rules=(HostPassthroughRule(host="example.org", mirror_id="test"),) if cacheable else ()
    )
    with TestClient(store) as storage:
        client = AssetStoreClient(storage, service_secret="dev-secret:fetcher")
        with TestClient(
            create_app(asset_store_client=client, rules=rules, fetcher=origin),
            headers={"Authorization": "Service task-api:dev-secret:task-api"},
        ) as api:
            body = {"url": "https://example.org/image?secret=hidden", "tmp_id": "test"}
            first = api.post("/v1/ensure-url", json=body)
            assert first.status_code == 200
            snapshot = store.state.registry.audit_events
            hit = api.post("/v1/ensure-url", json=body)
            assert hit.json()["cache_hit"] is True
            assert origin.calls == 1
            same = api.post("/v1/ensure-url", json={**body, "no_cache": True})
            assert same.status_code == 200
            assert same.json() == first.json()
            assert origin.calls == 2
            origin.data = b"changed"
            with caplog.at_level(logging.WARNING, logger="fetcher_service"):
                changed = api.post("/v1/ensure-url", json={**body, "no_cache": True})
            assert changed.status_code == 409
            assert changed.headers["content-type"] == "application/problem+json"
            assert store.state.registry.audit_events == snapshot
            bucket = "cache" if cacheable else "tmp"
            metrics = api.get("/metrics").text
            for outcome in ("match", "mismatch"):
                assert f'bucket="{bucket}",outcome="{outcome}"}} 1.0' in metrics
            warning = next(r for r in caplog.records if r.name == "fetcher_service")
            assert getattr(warning, "event") == "fetch.checksum_mismatch"
            assert first.json()["asset_id"] in warning.getMessage()
            assert "hidden" not in warning.getMessage()
            assert (
                api.post("/v1/ensure-url", json=body).json()["asset_id"] == first.json()["asset_id"]
            )


@pytest.mark.parametrize(
    "error,status", [(UpstreamError("failed"), 502), (UpstreamTimeoutError("timeout"), 504)]
)
def test_failed_refetch_preserves_existing_asset(error: Exception, status: int) -> None:
    store = asset_app()
    origin = MutableOrigin()
    with TestClient(store) as storage:
        client = AssetStoreClient(storage, service_secret="dev-secret:fetcher")
        with TestClient(
            create_app(asset_store_client=client, fetcher=origin),
            headers={"Authorization": "Service task-api:dev-secret:task-api"},
        ) as api:
            body = {"url": "https://example.org/image", "tmp_id": "test", "no_cache": True}
            first = api.post("/v1/ensure-url", json=body)
            assert first.status_code == 200  # forced fetch of an absent alias ingests
            snapshot = store.state.registry.audit_events
            origin.error = error
            assert api.post("/v1/ensure-url", json=body).status_code == status
            assert store.state.registry.audit_events == snapshot
            body["no_cache"] = False
            assert (
                api.post("/v1/ensure-url", json=body).json()["asset_id"] == first.json()["asset_id"]
            )
