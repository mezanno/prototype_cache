"""Pluggable outbound-fetch seam.

The fetcher's remote-HTTP behavior lives behind :class:`UrlFetcher` so the
control flow (normalize → rules → cache lookup → store) can be exercised without
a network. Step 1 ships :class:`SyntheticFetcher` (no network, deterministic
bytes derived from the URL). Step 2 replaces it with a real HTTP client
(timeouts, max body, redirect limit, SSRF controls) behind the same seam.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class FetchedContent:
    """Bytes materialized for a URL plus their MIME type."""

    data: bytes
    mime: str


@runtime_checkable
class UrlFetcher(Protocol):
    """Materialize a URL into bytes. Implementations may perform outbound HTTP.

    Real (Step-2) implementations raise
    :class:`fetcher_service.service.UpstreamError` (or its
    :class:`~fetcher_service.service.UpstreamTimeoutError` subclass) on fetch
    failure; the control flow lets those propagate to the 502/504 mapping.
    """

    def fetch(self, url: str) -> FetchedContent:
        """Return the content for ``url`` (raises on failure in real impls)."""


class SyntheticFetcher:
    """Step-1 stub: performs no network I/O.

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
