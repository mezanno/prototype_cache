"""B-024 exact-rendition policy and authenticated cache-only HTTP contracts."""

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from asset_store_core.api import create_app as asset_app
from fetcher_service.app import create_app
from fetcher_service.errors import PilotDeniedError
from fetcher_service.fetcher import FetchedContent, HttpFetcher
from fetcher_service.pilot_policy import GallicaPolicy

URL = "https://gallica.bnf.fr/iiif/ark:/12148/btv1b90017179/f15/full/800,/0/native.jpg"
READ = "/" + URL.removeprefix("https://")
AUTH = {"Authorization": "Service task-api:dev-secret:task-api"}


class Origin:
    data = b"image fixture"
    mime = "image/jpeg"
    calls = 0

    def fetch(self, url: str) -> FetchedContent:
        self.calls += 1
        return FetchedContent(self.data, self.mime)


@pytest.mark.parametrize(
    "url",
    [
        URL.replace("https:", "http:"),
        URL.replace("gallica.bnf.fr", "gallica.bnf.fr.evil"),
        URL.replace("gallica.bnf.fr", "user@gallica.bnf.fr"),
        URL.replace("gallica.bnf.fr", "gallica.bnf.fr:443"),
        URL + "?token=secret",
        URL + "#fragment",
        URL.replace("native.jpg", "info.json"),
        URL.replace("/f15/", "/f0/"),
        URL.replace("/full/", "/../"),
        URL.replace("btv1", "%2fbtv1"),
        URL.replace("btv1", "%252fbtv1"),
        URL.replace("btv1", "%ggbtv1"),
        URL.replace("btv1", "%5cbtv1"),
    ],
)
def test_policy_denies_unapproved_urls(url: str) -> None:
    with pytest.raises(PilotDeniedError):
        GallicaPolicy().require(url)


def test_policy_mapping_preserves_renditions_and_decodes_once() -> None:
    policy = GallicaPolicy()
    target = policy.require(URL)
    assert policy.require(URL.replace("btv1", "%62tv1")) == target
    assert policy.require_read(READ.encode(), b"") == target
    assert policy.require(URL.replace("native", "default")) != target
    assert policy.require(URL.replace("800,", "400,")) != target
    with pytest.raises(PilotDeniedError):
        policy.require_read(READ.encode(), b"secret=value")


Stack = tuple[TestClient, Origin, FastAPI, FastAPI]


@pytest.fixture
def stack() -> Iterator[Stack]:
    from fetcher_service.client import AssetStoreClient

    store = asset_app()
    origin = Origin()
    with TestClient(store) as storage:
        client = AssetStoreClient(storage, service_secret="dev-secret:fetcher")
        app = create_app(asset_store_client=client, fetcher=origin)
        with TestClient(app, headers=AUTH) as api:
            yield api, origin, store, app


def test_preload_read_hit_refetch_and_restart(stack: Stack) -> None:
    api, origin, store, app = stack
    assert api.get(READ).status_code == 404
    assert origin.calls == 0
    first = api.post("/v1/cache/preload", json={"url": URL})
    assert first.status_code == 200, first.text
    assert first.json()["partition_id"] == "gallica-pilot"
    assert api.get(READ).content == origin.data
    token = app.state.pilot._read_capability
    assert api.get(READ).headers["content-type"] == "image/jpeg"
    assert app.state.pilot._read_capability == token
    store.state.capabilities._capabilities.clear()  # process-local token loss on restart
    assert api.get(READ).content == origin.data
    assert app.state.pilot._read_capability != token
    assert api.post("/v1/cache/preload", json={"url": URL}).json()["cache_hit"]
    assert origin.calls == 1
    assert api.post("/v1/cache/preload", json={"url": URL, "no_cache": True}).status_code == 200
    origin.data = b"changed"
    assert api.post("/v1/cache/preload", json={"url": URL, "no_cache": True}).status_code == 409
    assert api.get(READ).content == b"image fixture"
    metrics = api.get("/metrics").text
    assert 'operation="read",outcome="miss"} 1.0' in metrics
    assert 'bucket="cache",outcome="mismatch"} 1.0' in metrics


def test_policy_and_auth_rejections_do_not_fetch(stack: Stack) -> None:
    api, origin, _, _ = stack
    for url in (URL + "?secret=hidden", URL.replace("native.jpg", "info.json")):
        assert api.post("/v1/cache/preload", json={"url": url}).status_code == 403
    assert api.get(READ + "?secret=hidden").status_code == 403
    assert api.get(READ, headers={"Authorization": ""}).status_code == 401
    assert api.post("/v1/cache/preload", json={"url": URL, "tmp_id": "x"}).status_code == 422
    assert origin.calls == 0


def test_renditions_are_distinct(stack: Stack) -> None:
    api, origin, _, _ = stack
    first = api.post("/v1/cache/preload", json={"url": URL}).json()
    second = api.post("/v1/cache/preload", json={"url": URL.replace("native", "default")}).json()
    assert first["asset_id"] != second["asset_id"]
    assert origin.calls == 2


@pytest.mark.parametrize("mime", ["text/html", "application/json"])
def test_non_image_origin_does_not_publish(stack: Stack, mime: str) -> None:
    api, origin, _, _ = stack
    origin.mime = mime
    assert api.post("/v1/cache/preload", json={"url": URL}).status_code == 502
    assert api.get(READ).status_code == 404


def test_redirect_policy_checked_before_following(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.example/image.jpg"})

    monkeypatch.setattr("fetcher_service.fetcher._assert_host_allowed", lambda *a, **kw: None)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        fetcher = HttpFetcher(client=client)
        with pytest.raises(PilotDeniedError):
            fetcher.fetch_with_policy(URL, GallicaPolicy().require)
    assert requests == [URL]


def test_pilot_mode_removes_generic_ingestion(
    monkeypatch: pytest.MonkeyPatch, stack: Stack
) -> None:
    api, _, _, app = stack
    monkeypatch.setenv("FETCHER_PILOT_MODE", "true")
    pilot_app = create_app(asset_store_client=app.state.asset_store_client, fetcher=Origin())
    with TestClient(pilot_app, headers=AUTH) as pilot:
        assert pilot.post("/v1/ensure-url", json={"url": URL}).status_code in {404, 405}
        assert "/v1/ensure-url" not in pilot.get("/openapi.json").json()["paths"]


def test_expired_read_is_cache_only(stack: Stack) -> None:
    api, origin, store, _ = stack
    asset = api.post("/v1/cache/preload", json={"url": URL}).json()
    store.state.registry.expire_asset(asset_id=asset["asset_id"], caller_service_id="admin")
    assert api.get(READ).status_code == 404
    assert origin.calls == 1


def test_read_rejects_invalid_registered_metadata(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    api, origin, _, app = stack
    api.post("/v1/cache/preload", json={"url": URL})
    original = app.state.pilot.client.resolve

    def corrupt(**kwargs: Any) -> dict[str, Any]:
        asset = original(**kwargs)
        return {**asset, "checksum": "sha256:invalid"}

    monkeypatch.setattr(app.state.pilot.client, "resolve", corrupt)
    assert api.get(READ).status_code == 502
    assert origin.calls == 1


def test_backend_rate_response_is_sanitized(stack: Stack, monkeypatch: pytest.MonkeyPatch) -> None:
    from fetcher_service.client import AssetStoreError

    api, origin, _, app = stack

    def overloaded(**kwargs: Any) -> None:
        raise AssetStoreError("secret upstream details", status=429, retry_after="7")

    monkeypatch.setattr(app.state.pilot.client, "resolve", overloaded)
    response = api.get(READ)
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "7"
    assert "secret" not in response.text
    assert origin.calls == 0


def test_preload_and_reads_apply_byte_cap(stack: Stack) -> None:
    api, origin, _, app = stack
    app.state.pilot.fetcher.max_bytes = 1
    assert api.post("/v1/cache/preload", json={"url": URL}).status_code == 502
    assert api.get(READ).status_code == 404
    app.state.pilot.fetcher.max_bytes = 100
    assert api.post("/v1/cache/preload", json={"url": URL}).status_code == 200
    app.state.pilot.max_bytes = 1
    assert api.get(READ).status_code == 413
    assert origin.calls == 2


def test_concurrent_commit_reuses_winner(stack: Stack, monkeypatch: pytest.MonkeyPatch) -> None:
    from fetcher_service.client import AssetStoreError

    api, _, _, app = stack
    winner = api.post("/v1/cache/preload", json={"url": URL}).json()

    def conflict(*args: Any, **kwargs: Any) -> None:
        raise AssetStoreError("alias conflict", status=409)

    monkeypatch.setattr("fetcher_service.pilot.ensure_url", conflict)
    retry = api.post("/v1/cache/preload", json={"url": URL})
    assert retry.status_code == 200
    assert retry.json()["asset_id"] == winner["asset_id"]
    assert retry.json()["cache_hit"]
