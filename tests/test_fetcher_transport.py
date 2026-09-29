"""SEC-05 / ADR-025 connection-bound SSRF and TLS regression coverage."""

from __future__ import annotations

import socket
import ssl
import subprocess
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpcore
import httpx
import pytest
from prometheus_client import CollectorRegistry, generate_latest

from fetcher_service.errors import UpstreamError
from fetcher_service.fetcher import HttpFetcher
from fetcher_service.transport import ValidatedNetworkBackend, ValidatedTransport


def answers(*ips: str) -> list[tuple[Any, ...]]:
    return [
        (
            socket.AF_INET6 if ":" in ip else socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            (ip, 443),
        )
        for ip in ips
    ]


def test_connect_pins_numeric_address_without_second_hostname_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved: list[str] = []
    dialed: list[str] = []

    def resolve(host: str, *_args: Any, **_kwargs: Any) -> list[tuple[Any, ...]]:
        resolved.append(host)
        # A second lookup of the attacker-controlled hostname would rebind.
        return answers("93.184.216.34" if len(resolved) == 1 else "127.0.0.1")

    def dial(host: str, *_args: Any, **_kwargs: Any) -> httpcore.NetworkStream:
        dialed.append(host)
        assert host == "93.184.216.34"
        return httpcore.MockStream([])

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    backend = ValidatedNetworkBackend()
    monkeypatch.setattr(backend._backend, "connect_tcp", dial)
    backend.connect_tcp("attacker.test", 443)
    assert resolved == ["attacker.test"]
    assert dialed == ["93.184.216.34"]
    # A later connection revalidates rather than reusing a cached DNS approval.
    with pytest.raises(UpstreamError, match="blocked address"):
        backend.connect_tcp("attacker.test", 443)
    assert len(dialed) == 1
    metrics = CollectorRegistry()
    metrics.register(backend.connections)
    values = generate_latest(metrics).decode()
    assert 'fetcher_outbound_connections_total{outcome="rejected"} 1.0' in values
    assert 'fetcher_outbound_connections_total{outcome="connected"} 1.0' in values


def test_connect_retries_only_validated_numeric_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookups: list[str] = []
    dialed: list[str] = []

    def resolve(host: str, *_args: Any, **_kwargs: Any) -> list[tuple[Any, ...]]:
        lookups.append(host)
        return answers("93.184.216.34", "1.1.1.1")

    def dial(host: str, *_args: Any, **_kwargs: Any) -> httpcore.NetworkStream:
        dialed.append(host)
        if host == "93.184.216.34":
            raise httpcore.ConnectError("first approved address unavailable")
        assert host == "1.1.1.1"
        return httpcore.MockStream([])

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    backend = ValidatedNetworkBackend()
    monkeypatch.setattr(backend._backend, "connect_tcp", dial)

    stream = backend.connect_tcp("origin.test", 443)

    assert isinstance(stream, httpcore.MockStream)
    assert lookups == ["origin.test"]
    assert dialed == ["93.184.216.34", "1.1.1.1"]
    metrics = CollectorRegistry()
    metrics.register(backend.connections)
    values = generate_latest(metrics).decode()
    assert 'fetcher_outbound_connections_total{outcome="failed"} 1.0' in values
    assert 'fetcher_outbound_connections_total{outcome="connected"} 1.0' in values


def test_connect_deadline_prevents_later_dial(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: answers("93.184.216.34", "1.1.1.1"))
    clock = iter((0.0, 0.0, 1.1))
    monkeypatch.setattr("fetcher_service.transport.monotonic", lambda: next(clock))
    backend = ValidatedNetworkBackend()
    dialed: list[tuple[str, float | None]] = []

    def dial(
        host: str, _port: int, *, timeout: float | None = None, **_kwargs: Any
    ) -> httpcore.NetworkStream:
        dialed.append((host, timeout))
        raise httpcore.ConnectError("first approved address unavailable")

    monkeypatch.setattr(backend._backend, "connect_tcp", dial)

    with pytest.raises(httpcore.ConnectTimeout, match="deadline exceeded"):
        backend.connect_tcp("origin.test", 443, timeout=1.0)

    assert dialed == [("93.184.216.34", 1.0)]


@pytest.mark.parametrize(
    "ips",
    [
        ("93.184.216.34", "127.0.0.1"),
        ("169.254.169.254",),
        ("100.64.0.1",),
        ("::ffff:127.0.0.1",),
        ("64:ff9b::7f00:1",),
        ("2002:7f00:1::",),
        ("::1",),
        (),
    ],
)
def test_reject_entire_answer_set_before_dial(
    ips: tuple[str, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: answers(*ips))
    backend = ValidatedNetworkBackend()

    def forbidden(*args: Any, **kwargs: Any) -> httpcore.NetworkStream:
        pytest.fail("blocked DNS answer must not open any connection")

    monkeypatch.setattr(backend._backend, "connect_tcp", forbidden)
    with pytest.raises(UpstreamError):
        backend.connect_tcp("origin.test", 443)


def test_preflight_approval_cannot_bypass_connection_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    count = 0

    def resolve(*args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
        nonlocal count
        count += 1
        return answers("93.184.216.34" if count == 1 else "10.0.0.1")

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    with pytest.raises(UpstreamError, match="blocked address"):
        HttpFetcher().fetch("https://attacker.test/image")
    assert count == 2


def test_redirect_keeps_original_host_and_revalidates_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookups: list[str] = []
    wire: list[bytes] = []

    def resolve(host: str, *args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
        lookups.append(host)
        # Preflight sees public; connect-time redirect lookup sees private.
        return answers("127.0.0.1" if lookups.count("redirect.test") == 2 else "93.184.216.34")

    class Stream(httpcore.MockStream):
        def write(self, buffer: bytes, timeout: float | None = None) -> None:
            wire.append(buffer)
            super().write(buffer, timeout)

    def dial(*args: Any, **kwargs: Any) -> httpcore.NetworkStream:
        return Stream(
            [
                b"HTTP/1.1 302 Found\r\nLocation: http://redirect.test/image\r\n"
                b"Content-Length: 0\r\n\r\n"
            ]
        )

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", dial)
    with pytest.raises(UpstreamError, match="blocked address"):
        HttpFetcher().fetch("http://origin.test/image")
    assert b"Host: origin.test" in b"".join(wire)
    assert b"Host: redirect.test" not in b"".join(wire)


@pytest.fixture
def tls_origin(tmp_path: Path) -> Iterator[tuple[int, Path, list[str | None]]]:
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
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
            "/CN=origin.test",
            "-addext",
            "subjectAltName=DNS:origin.test",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = self.headers["Host"].encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    names: list[str | None] = []
    context.set_servername_callback(lambda _sock, name, _ctx: names.append(name))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, cert, names
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_real_tls_retains_sni_and_checks_hostname(
    tls_origin: tuple[int, Path, list[str | None]], monkeypatch: pytest.MonkeyPatch
) -> None:
    port, cert, names = tls_origin
    original = socket.getaddrinfo

    def resolve(host: str, port: int, *args: Any, **kwargs: Any) -> Any:
        return original("127.0.0.1" if host.endswith(".test") else host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(
        httpcore, "default_ssl_context", lambda: ssl.create_default_context(cafile=cert)
    )
    with httpx.Client(
        transport=ValidatedTransport(allow_private_hosts=True), trust_env=False
    ) as client:
        assert (
            client.get(f"https://origin.test:{port}/image").content
            == f"origin.test:{port}".encode()
        )
        with pytest.raises(httpcore.ConnectError):
            client.get(f"https://wrong.test:{port}/image")
    assert "origin.test" in names
    assert "wrong.test" in names


def test_capped_response_releases_connection_for_next_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            paths.append(self.path)
            body = b"too-large" if self.path == "/large" else b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: Any) -> None:
            pass

    original_pool = httpcore.ConnectionPool

    def one_connection_pool(*args: Any, **kwargs: Any) -> httpcore.ConnectionPool:
        kwargs["max_connections"] = 1
        return original_pool(*args, **kwargs)

    monkeypatch.setattr("fetcher_service.transport.httpcore.ConnectionPool", one_connection_pool)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        fetcher = HttpFetcher(
            max_bytes=4,
            connect_timeout=1.0,
            read_timeout=1.0,
            allow_private_hosts=True,
        )
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with pytest.raises(UpstreamError, match="exceeds max_bytes"):
                fetcher.fetch(f"{base}/large")
            assert fetcher.fetch(f"{base}/small").data == b"ok"
            assert paths == ["/large", "/small"]
        finally:
            fetcher._client.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
