"""M-001 HTTP smoke artifact: real cache socket and meaningful failure checks."""

from __future__ import annotations

import hashlib
import socket
import sys
import threading
from pathlib import Path
from time import monotonic, sleep

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from asset_store_core.api import create_app as asset_app
from fetcher_service.app import create_app
from fetcher_service.client import AssetStoreClient
from fetcher_service.fetcher import FetchedContent

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/cache-pilot"))
from cache_smoke import SmokeFailure, main, run_smoke  # noqa: E402

URL = "https://gallica.bnf.fr/iiif/ark:/12148/fixture1/f1/full/800,/0/native.jpg"


def test_smoke_over_real_cache_http_socket() -> None:
    image = (Path(__file__).parent / "fixtures/gallica/image.jpg").read_bytes()

    class Origin:
        calls = 0

        def fetch(self, url: str) -> FetchedContent:
            self.calls += 1
            return FetchedContent(image, "image/jpeg")

    origin = Origin()
    with TestClient(asset_app()) as storage:
        app = create_app(
            asset_store_client=AssetStoreClient(storage, service_secret="dev-secret:fetcher"),
            fetcher=origin,
        )
        server = uvicorn.Server(uvicorn.Config(app, log_level="critical"))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            thread = threading.Thread(
                target=server.run, kwargs={"sockets": [listener]}, daemon=True
            )
            thread.start()
            try:
                deadline = monotonic() + 5
                while not server.started and thread.is_alive() and monotonic() < deadline:
                    sleep(0.01)
                assert server.started
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{port}",
                    trust_env=False,
                    headers={"Authorization": "Service task-api:dev-secret:task-api"},
                ) as http:
                    result = run_smoke(http, URL, max_bytes=1024)
                assert result.size_bytes == len(image)
                assert result.checksum == "sha256:" + hashlib.sha256(image).hexdigest()
                assert result.first_cache_hit is False
                assert origin.calls == 1
            finally:
                server.should_exit = True
                thread.join(timeout=5)
                assert not thread.is_alive()


@pytest.mark.parametrize("failure", ["status", "checksum", "cap", "repeat"])
def test_smoke_reports_failed_contract(failure: str) -> None:
    preloads = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal preloads
        if request.method == "POST":
            preloads += 1
            return httpx.Response(
                200, json={"asset_id": "asset", "cache_hit": (preloads > 1 and failure != "repeat")}
            )
        return httpx.Response(
            404 if failure == "status" else 200,
            content=b"image",
            headers={
                "Content-Type": "image/jpeg",
                "ETag": '"sha256:'
                + ("bad" if failure == "checksum" else hashlib.sha256(b"image").hexdigest())
                + '"',
            },
        )

    with httpx.Client(base_url="http://localhost", transport=httpx.MockTransport(respond)) as http:
        with pytest.raises(SmokeFailure):
            run_smoke(http, URL, max_bytes=1 if failure == "cap" else 1024)


def test_main_failure_does_not_print_credentials_or_source_query(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CACHE_PILOT_BASE_URL", "http://localhost:8081")
    monkeypatch.setenv("CACHE_PILOT_ORIGIN_URL", URL + "?secret=origin-secret")
    monkeypatch.setenv("CACHE_PILOT_SERVICE_SECRET", "service-secret")
    assert main() == 1
    output = capsys.readouterr().out
    assert "FAIL:" in output
    assert "origin-secret" not in output and "service-secret" not in output


def test_smoke_uses_v3_host_and_webp_type() -> None:
    url = (
        "https://openapi.bnf.fr/iiif/image/v3/ark:/12148/bd6t543024772/f18/full/max/0/default.webp"
    )
    calls: list[str] = []
    preloads = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal preloads
        if request.method == "POST":
            preloads += 1
            return httpx.Response(200, json={"asset_id": "asset", "cache_hit": preloads > 1})
        calls.append(request.url.path)
        return httpx.Response(
            200,
            content=b"webp",
            headers={
                "Content-Type": "image/webp",
                "ETag": '"sha256:' + hashlib.sha256(b"webp").hexdigest() + '"',
            },
        )

    with httpx.Client(base_url="http://localhost", transport=httpx.MockTransport(respond)) as http:
        result = run_smoke(http, url, max_bytes=1024)
    assert calls == ["/" + url.removeprefix("https://")] * 2
    assert result.size_bytes == 4
