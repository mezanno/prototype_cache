"""Pluggable outbound-fetch seam.

The fetcher's remote-HTTP behavior lives behind :class:`UrlFetcher` so the
control flow (normalize → rules → cache lookup → store) can be exercised without
a network. :class:`SyntheticFetcher` performs no network I/O (deterministic
bytes derived from the URL) and is used in tests and dev; :class:`HttpFetcher`
is the real client (timeouts, max body, redirect cap, SSRF controls).
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable
from urllib.parse import urljoin, urlsplit

import httpx

from fetcher_service.errors import UpstreamError, UpstreamTimeoutError


@dataclass(frozen=True, slots=True)
class FetchedContent:
    """Bytes materialized for a URL plus their MIME type."""

    data: bytes
    mime: str


@runtime_checkable
class UrlFetcher(Protocol):
    """Materialize a URL into bytes. Implementations may perform outbound HTTP.

    Real implementations raise :class:`fetcher_service.errors.UpstreamError` (or
    its :class:`~fetcher_service.errors.UpstreamTimeoutError` subclass) on fetch
    failure; the control flow lets those propagate to the 502/504 mapping.
    """

    def fetch(self, url: str) -> FetchedContent:
        """Return the content for ``url`` (raises on failure in real impls)."""


class SyntheticFetcher:
    """Stub fetcher that performs no network I/O (tests and offline dev).

    Emits a small JSON document whose ``content_id`` is a deterministic function
    of the URL, so a round-trip is verifiable (the stored bytes echo the URL) and
    the identity portion is stable across calls. ``fetched_at`` records when the
    stub ran; it does not affect ``content_id``.
    """

    mime = "application/json"

    def fetch(self, url: str) -> FetchedContent:
        content_id = hashlib.sha256(url.encode("utf-8")).hexdigest()
        payload = {
            "stub": True,
            "url": url,
            "content_id": content_id,
            "fetched_at": datetime.now(UTC).isoformat(),
        }
        data = json.dumps(payload, sort_keys=True).encode("utf-8")
        return FetchedContent(data=data, mime=self.mime)


# Defaults (overridable via the environment in :func:`http_fetcher_from_env`).
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 30.0
DEFAULT_MAX_BYTES = 50 * 1024 * 1024  # 50 MiB
DEFAULT_MAX_REDIRECTS = 5
_ALLOWED_SCHEMES = frozenset({"http", "https"})
_DEFAULT_MIME = "application/octet-stream"


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True if ``ip`` is in a range an outbound fetch must never reach (SSRF)."""

    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _assert_host_allowed(host: str, *, allow_private_hosts: bool) -> None:
    """Resolve ``host`` and reject it if any address is a blocked (SSRF) range."""

    if allow_private_hosts:
        return
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UpstreamError(f"cannot resolve host {host!r}: {exc}") from exc
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:  # pragma: no cover - getaddrinfo returns valid IPs
            continue
        if _is_blocked_ip(ip):
            raise UpstreamError(f"host {host!r} resolves to a blocked address ({address})")


class HttpFetcher:
    """Outbound HTTP fetcher with timeouts, a body cap, a redirect cap and an
    SSRF guard.

    Redirects are followed manually so each hop's host is re-validated against
    the SSRF policy before connecting (auto-follow would connect first). The
    response body is streamed and aborted once it exceeds ``max_bytes``, so an
    oversized origin cannot exhaust memory. Only ``http``/``https`` are allowed.

    Note: the SSRF check resolves the host and inspects its addresses, then lets
    httpx re-resolve on connect — a DNS-rebinding TOCTOU window remains and is
    accepted for the prototype (a hardened build would pin the validated IP).
    """

    def __init__(
        self,
        *,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        allow_private_hosts: bool = False,
        client: httpx.Client | None = None,
    ) -> None:
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._allow_private_hosts = allow_private_hosts
        timeout = httpx.Timeout(
            connect=connect_timeout,
            read=read_timeout,
            write=read_timeout,
            pool=connect_timeout,
        )
        # follow_redirects stays False: we validate each hop's host ourselves.
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=False)

    def fetch(self, url: str) -> FetchedContent:
        current = url
        for _ in range(self._max_redirects + 1):
            self._validate(current)
            try:
                with self._client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise UpstreamError(f"redirect from {current!r} without a Location")
                        current = urljoin(current, location)
                        continue
                    if response.status_code >= 400:
                        raise UpstreamError(
                            f"origin returned HTTP {response.status_code} for {current!r}"
                        )
                    data = self._read_capped(response)
                    mime = response.headers.get("content-type", _DEFAULT_MIME).split(";", 1)[0]
                    return FetchedContent(data=data, mime=mime.strip() or _DEFAULT_MIME)
            except httpx.TimeoutException as exc:
                raise UpstreamTimeoutError(f"timeout fetching {current!r}: {exc}") from exc
            except httpx.HTTPError as exc:
                raise UpstreamError(f"error fetching {current!r}: {exc}") from exc
        raise UpstreamError(f"too many redirects (>{self._max_redirects}) fetching {url!r}")

    def _validate(self, url: str) -> None:
        scheme = urlsplit(url).scheme.lower()
        if scheme not in _ALLOWED_SCHEMES:
            raise UpstreamError(f"scheme {scheme!r} is not allowed (http/https only)")
        host = urlsplit(url).hostname
        if not host:
            raise UpstreamError(f"URL {url!r} has no host")
        _assert_host_allowed(host, allow_private_hosts=self._allow_private_hosts)

    def _read_capped(self, response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > self._max_bytes:
                raise UpstreamError(f"origin body exceeds max_bytes ({self._max_bytes})")
            chunks.append(chunk)
        return b"".join(chunks)


def http_fetcher_from_env() -> HttpFetcher:
    """Build an :class:`HttpFetcher` from ``FETCHER_HTTP_*`` environment variables."""

    def _float(name: str, default: float) -> float:
        raw = os.environ.get(name)
        return float(raw) if raw else default

    def _int(name: str, default: int) -> int:
        raw = os.environ.get(name)
        return int(raw) if raw else default

    allow_private = os.environ.get("FETCHER_ALLOW_PRIVATE_HOSTS", "").lower() in {
        "1",
        "true",
        "yes",
    }
    return HttpFetcher(
        connect_timeout=_float("FETCHER_HTTP_CONNECT_TIMEOUT", DEFAULT_CONNECT_TIMEOUT),
        read_timeout=_float("FETCHER_HTTP_READ_TIMEOUT", DEFAULT_READ_TIMEOUT),
        max_bytes=_int("FETCHER_HTTP_MAX_BYTES", DEFAULT_MAX_BYTES),
        max_redirects=_int("FETCHER_HTTP_MAX_REDIRECTS", DEFAULT_MAX_REDIRECTS),
        allow_private_hosts=allow_private,
    )
