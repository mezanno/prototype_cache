"""Fetcher-service error hierarchy.

Kept in its own module so both the ``UrlFetcher`` implementations
(:mod:`fetcher_service.fetcher`) and the ``ensure_url`` orchestration
(:mod:`fetcher_service.service`) can raise/handle them without an import cycle.
The FastAPI app maps each class to an HTTP status (400 / 502 / 504).
"""

from __future__ import annotations


class FetcherError(Exception):
    """Base class for fetcher request errors."""


class InvalidRequestError(FetcherError):
    """The request cannot be served as asked (bad URL, missing tmp_id). Maps to 400."""


class ContentMismatchError(FetcherError):
    """Refetched bytes differ from an immutable alias's checksum (R-011); HTTP 409."""


class UpstreamError(FetcherError):
    """The origin fetch failed (connection, HTTP error, oversized body, blocked host).

    Raised by :class:`~fetcher_service.fetcher.UrlFetcher` implementations that
    perform outbound HTTP; the control flow lets it propagate to the 502 mapping.
    """


class UpstreamTimeoutError(UpstreamError):
    """The origin fetch timed out. Maps to 504."""


class PilotDeniedError(FetcherError):
    """The pilot origin/path policy rejected the request (HTTP 403)."""


class CacheMissError(FetcherError):
    """Cached bytes are absent/expired; no origin fetch occurs (HTTP 404)."""


class CacheBackendError(FetcherError):
    """Sanitized asset-store failure with a retryable HTTP status."""

    def __init__(self, status: int, retry_after: str | None = None) -> None:
        super().__init__("asset-store could not complete the cache operation")
        self.status = status
        self.retry_after = retry_after
