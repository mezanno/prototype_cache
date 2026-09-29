"""SEC-05: bind outbound connections to validated DNS answers (ADR-025)."""

from __future__ import annotations

import ipaddress
import logging
import socket
from collections.abc import Iterable, Iterator
from time import monotonic

import httpcore
import httpx
from prometheus_client import CollectorRegistry, Counter

from fetcher_service.errors import UpstreamError

_LOG = logging.getLogger("fetcher_service")
_SOCKET_OPTION = (
    tuple[int, int, int] | tuple[int, int, bytes | bytearray] | tuple[int, int, None, int]
)


def blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Reject non-public addresses and IPv6 address-translation tunnels."""
    if not ip.is_global or ip.is_multicast:
        return True
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return blocked_ip(ip.ipv4_mapped)
        # A public-looking transition address can route to an embedded private IPv4.
        return any(ip in network for network in _TRANSITION_NETWORKS)
    return False


_TRANSITION_NETWORKS = tuple(
    ipaddress.IPv6Network(prefix)
    for prefix in ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32")
)


def resolve_allowed(host: str, port: int, *, allow_private_hosts: bool) -> list[str]:
    """Validate the whole answer set before returning any numeric destination."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise UpstreamError("cannot resolve origin host") from exc
    addresses: list[str] = []
    for family, _, _, _, sockaddr in infos:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            raise UpstreamError("unsupported origin address family")
        address = str(sockaddr[0])
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise UpstreamError("invalid origin address") from exc
        if not allow_private_hosts and ("%" in address or blocked_ip(ip)):
            _LOG.warning("outbound connection blocked", extra={"event": "fetch.ssrf_denied"})
            raise UpstreamError("origin resolves to a blocked address")
        if str(ip) not in addresses:
            addresses.append(str(ip))
    if not addresses:
        raise UpstreamError("origin has no usable addresses")
    return addresses


class ValidatedNetworkBackend(httpcore.NetworkBackend):
    """Resolve at connect time; the underlying dialer sees only numeric IPs.

    HTTP origin, Host, SNI and certificate hostname verification stay in httpcore
    and retain the original hostname. Each new connection validates a fresh answer
    set; a pooled existing connection remains attached to its validated peer.
    """

    def __init__(self, *, allow_private_hosts: bool = False) -> None:
        self.allow_private_hosts = allow_private_hosts
        self._backend = httpcore.SyncBackend()
        self.connections = Counter(
            "fetcher_outbound_connections_total",
            "Validated outbound TCP connection outcomes.",
            ["outcome"],
            registry=None,
        )

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[_SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        started = monotonic()
        try:
            addresses = resolve_allowed(host, port, allow_private_hosts=self.allow_private_hosts)
        except UpstreamError:
            self.connections.labels("rejected").inc()
            raise
        last_error: Exception | None = None
        for address in addresses:
            remaining = None if timeout is None else timeout - (monotonic() - started)
            if remaining is not None and remaining <= 0:
                raise httpcore.ConnectTimeout("origin connection deadline exceeded")
            try:
                stream = self._backend.connect_tcp(
                    address,
                    port,
                    timeout=remaining,
                    local_address=local_address,
                    socket_options=socket_options,
                )
                self.connections.labels("connected").inc()
                return stream
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                self.connections.labels("failed").inc()
                last_error = exc
        assert last_error is not None
        raise last_error


class _ResponseStream(httpx.SyncByteStream):
    def __init__(self, response: httpcore.Response) -> None:
        self.response = response

    def __iter__(self) -> Iterator[bytes]:
        yield from self.response.iter_stream()

    def close(self) -> None:
        self.response.close()


class ValidatedTransport(httpx.BaseTransport):
    """Public HTTPX transport / httpcore backend adapter, no private API patching."""

    def __init__(self, *, allow_private_hosts: bool = False) -> None:
        self._backend = ValidatedNetworkBackend(allow_private_hosts=allow_private_hosts)
        self._pool = httpcore.ConnectionPool(
            network_backend=self._backend,
            ssl_context=httpcore.default_ssl_context(),
            max_connections=10,
            max_keepalive_connections=5,
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        assert isinstance(request.stream, httpx.SyncByteStream)
        response = self._pool.handle_request(
            httpcore.Request(
                request.method,
                httpcore.URL(
                    scheme=request.url.raw_scheme,
                    host=request.url.raw_host,
                    port=request.url.port,
                    target=request.url.raw_path,
                ),
                headers=request.headers.raw,
                content=request.stream,
                extensions=request.extensions,
            )
        )
        return httpx.Response(
            response.status,
            headers=response.headers,
            stream=_ResponseStream(response),
            extensions=response.extensions,
        )

    def register_metrics(self, registry: CollectorRegistry) -> None:
        registry.register(self._backend.connections)

    def close(self) -> None:
        self._pool.close()
