"""fetcher-service — remote URL materialization for asset-store (B-020).

Step 1 (this package) provides the ``ensure_url`` control flow and a no-network
synthetic fetcher. See [`docs/services/fetcher-service.md`](../../docs/services/fetcher-service.md).
"""

from __future__ import annotations

from fetcher_service.service import EnsureUrlResult, FetcherError, InvalidRequestError, ensure_url

__all__ = [
    "EnsureUrlResult",
    "FetcherError",
    "InvalidRequestError",
    "ensure_url",
]
