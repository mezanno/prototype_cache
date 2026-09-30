"""B-024/SCN-010: Gallica-shaped TLS origin, durable storage and facade restart.

Only this test maps approved origin DNS/port to loopback and allows private
addresses. TLS SNI/hostname verification and the production URL policy remain.
No live Gallica request. Configured backend failures fail rather than skip.
"""

from __future__ import annotations

import hashlib
import os
import socket
import ssl
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpcore
import httpx
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
from fetcher_service.transport import ValidatedTransport

_REQUIRED = (
    "ASSET_STORE_PG_DSN",
    "ASSET_STORE_S3_ENDPOINT",
    "ASSET_STORE_S3_ACCESS_KEY",
    "ASSET_STORE_S3_SECRET_KEY",
)
AUTH = {"Authorization": "Service task-api:dev-secret:task-api"}


@pytest.mark.skipif(
    not all(os.environ.get(k) for k in _REQUIRED),
    reason="export Garage credentials and ASSET_STORE_PG_DSN",
)
def test_gallica_https_preload_reads_and_durable_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = (Path(__file__).parent / "fixtures/gallica/image.jpg").read_bytes()
    cert, key = tmp_path / "origin.pem", tmp_path / "origin.key"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-subj",
            "/CN=gallica.bnf.fr",
            "-addext",
            "subjectAltName=DNS:gallica.bnf.fr",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    class Origin(BaseHTTPRequestHandler):
        calls = 0
        status = 200
        hosts: list[str] = []

        def log_message(self, *_args: object) -> None:
            pass

        def do_GET(self) -> None:  # noqa: N802
            Origin.calls += 1
            Origin.hosts.append(self.headers["Host"])
            self.send_response(Origin.status)
            self.send_header("Content-Length", str(len(image)))
            self.send_header("Content-Type", "image/jpeg")
            self.end_headers()
            self.wfile.write(image)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Origin)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, key)
    names: list[str | None] = []
    tls.set_servername_callback(lambda _sock, name, _ctx: names.append(name))
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    real_resolve = socket.getaddrinfo
    real_connect = httpcore.SyncBackend.connect_tcp

    def resolve(host: str, port: int, *args: Any, **kwargs: Any) -> Any:
        return real_resolve(
            "127.0.0.1" if host == "gallica.bnf.fr" else host, port, *args, **kwargs
        )

    def connect(self: Any, host: str, port: int, **kwargs: Any) -> httpcore.NetworkStream:
        assert host == "127.0.0.1" and port == 443
        return real_connect(self, host, server.server_port, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", connect)
    monkeypatch.setattr(
        httpcore, "default_ssl_context", lambda: ssl.create_default_context(cafile=cert)
    )
    monkeypatch.setenv("FETCHER_PILOT_MODE", "true")
    schema = "pilot_" + uuid.uuid4().hex
    identifier = "fixture" + uuid.uuid4().hex
    path = f"/iiif/ark:/12148/{identifier}/f1/full/800,/0/native.jpg"
    url, read_path = "https://gallica.bnf.fr" + path, "/gallica.bnf.fr" + path
    relative_alias = "gallica-pilot/" + path.lstrip("/")
    dsn = os.environ["ASSET_STORE_PG_DSN"]
    isolated_dsn = make_conninfo(dsn, options=f"-c search_path={schema}")
    store = S3ObjectStore(
        endpoint_url=os.environ["ASSET_STORE_S3_ENDPOINT"],
        region=os.environ.get("ASSET_STORE_S3_REGION", "garage"),
        access_key=os.environ["ASSET_STORE_S3_ACCESS_KEY"],
        secret_key=os.environ["ASSET_STORE_S3_SECRET_KEY"],
    )
    location: ObjectStoreLocation | None = None
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            with httpx.Client(
                transport=ValidatedTransport(allow_private_hosts=True), trust_env=False
            ) as origin_http:
                fetcher = HttpFetcher(client=origin_http, allow_private_hosts=True)
                with PostgresAssetRegistry.connect(isolated_dsn) as registry:
                    storage_app = asset_app(registry=registry, store=store)
                    with TestClient(storage_app) as storage:
                        client = AssetStoreClient(storage, service_secret="dev-secret:fetcher")
                        app = create_app(asset_store_client=client, fetcher=fetcher)
                        with TestClient(app, headers=AUTH) as api:
                            assert api.get(read_path).status_code == 404
                            assert Origin.calls == 0
                            first = api.post("/v1/cache/preload", json={"url": url})
                            resolved = client.resolve(space="cache", alias=relative_alias)
                            if resolved:
                                location = ObjectStoreLocation("cache", resolved["storage_key"])
                            assert first.status_code == 200, first.text
                            assert location is not None
                            assert store.get_object(location) == image
                            token = None
                            for _ in range(3):
                                response = api.get(read_path)
                                assert response.status_code == 200
                                assert response.content == image
                                assert response.headers["etag"] == (
                                    '"sha256:' + hashlib.sha256(image).hexdigest() + '"'
                                )
                                token = app.state.pilot._read_capability
                            # Concurrent callers reuse the committed asset without new origin GETs.
                            with ThreadPoolExecutor(max_workers=3) as pool:
                                responses = list(
                                    pool.map(
                                        lambda _: api.post("/v1/cache/preload", json={"url": url}),
                                        range(3),
                                    )
                                )
                            assert all(
                                r.status_code == 200 and r.json()["cache_hit"] for r in responses
                            )
                            assert Origin.calls == 1
                            storage_app.state.capabilities._capabilities.clear()
                            assert api.get(read_path).content == image
                            assert app.state.pilot._read_capability != token
                            Origin.status = 503
                            assert (
                                api.post(
                                    "/v1/cache/preload", json={"url": url, "no_cache": True}
                                ).status_code
                                == 502
                            )
                            assert api.get(read_path).content == image
                            assert Origin.calls == 2
                # Reopen metadata and create fresh apps: content remains, capabilities remint.
                with PostgresAssetRegistry.connect(isolated_dsn) as reopened:
                    with TestClient(asset_app(registry=reopened, store=store)) as storage:
                        app = create_app(
                            asset_store_client=AssetStoreClient(
                                storage, service_secret="dev-secret:fetcher"
                            ),
                            fetcher=fetcher,
                        )
                        with TestClient(app, headers=AUTH) as api:
                            response = api.get(read_path)
                            assert response.status_code == 200
                            assert response.content == image
                            assert (
                                api.post("/v1/cache/preload", json={"url": url}).json()["asset_id"]
                                == first.json()["asset_id"]
                            )
                            assert Origin.calls == 2
                            assert app.state.pilot._read_capability is not None
                assert Origin.hosts == ["gallica.bnf.fr"] * 2
                assert names and all(name == "gallica.bnf.fr" for name in names)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            if location is not None:
                store.delete_object(location)
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
