"""Thin Gallica preload/cache-only facade (B-024, SCN-010, ADR-031)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import NoReturn

import httpx

from fetcher_service.client import AssetStoreClient, AssetStoreError
from fetcher_service.errors import CacheBackendError, CacheMissError, UpstreamError
from fetcher_service.fetcher import FetchedContent, HttpFetcher, UrlFetcher
from fetcher_service.pilot_policy import PARTITION, GallicaPolicy, PilotTarget
from fetcher_service.rules import RuleSet
from fetcher_service.service import EnsureUrlResult, ensure_url


@dataclass(frozen=True)
class CachedImage:
    data: bytes
    mime: str
    checksum: str


class _ApprovedFetcher:
    def __init__(self, fetcher: UrlFetcher, policy: GallicaPolicy, max_bytes: int) -> None:
        self.fetcher, self.policy, self.max_bytes = fetcher, policy, max_bytes

    def fetch(self, url: str) -> FetchedContent:
        self.policy.require(url)
        if isinstance(self.fetcher, HttpFetcher):
            content = self.fetcher.fetch_with_policy(url, self.policy.require)
        else:
            # Injected non-HTTP fetchers are trusted test seams, as in B-020.
            content = self.fetcher.fetch(url)
        if len(content.data) > self.max_bytes:
            raise UpstreamError("origin image exceeds pilot byte limit")
        if content.mime not in {"image/jpeg", "image/tiff"}:
            raise UpstreamError("origin did not return a supported image content type")
        return content


class PilotCache:
    def __init__(self, client: AssetStoreClient, fetcher: UrlFetcher, *, max_bytes: int) -> None:
        self.client = client
        self.policy = GallicaPolicy()
        self.rules = RuleSet(rules=(self.policy,))
        self.fetcher = _ApprovedFetcher(fetcher, self.policy, max_bytes)
        self.max_bytes = max_bytes
        self._read_capability: str | None = None
        self._lock = Lock()

    def _read_token(self, stale: str | None = None) -> str:
        with self._lock:
            if self._read_capability is None or self._read_capability == stale:
                self._read_capability = self.client.mint_read_capability(
                    scope_prefix=f"cache/{PARTITION}"
                )
            return self._read_capability

    def preload(
        self,
        url: str,
        *,
        no_cache: bool = False,
        record_refetch: Callable[[str, str], None] | None = None,
    ) -> EnsureUrlResult:
        target = self.policy.require(url)
        try:
            return ensure_url(
                self.client,
                self.rules,
                self.fetcher,
                url=target.origin_url,
                no_cache=no_cache,
                capability_ttl_seconds=300,
                record_refetch=record_refetch,
            )
        except AssetStoreError as exc:
            if exc.status == 409:
                # A concurrent writer may have committed after our lookup.
                try:
                    existing = self.client.resolve(space="cache", alias=target.relative_alias)
                except AssetStoreError as resolve_error:
                    self._backend_error(resolve_error)
                except httpx.HTTPError as resolve_error:
                    raise CacheBackendError(503, "1") from resolve_error
                if existing is not None:
                    return EnsureUrlResult(
                        asset_id=existing["asset_id"],
                        qualified_alias=f"cache/{target.relative_alias}",
                        cache_hit=True,
                        bucket="cache",
                        partition_id=PARTITION,
                    )
            self._backend_error(exc)
        except httpx.HTTPError as exc:
            raise CacheBackendError(503, "1") from exc

    def read(self, target: PilotTarget) -> CachedImage:
        try:
            asset = self.client.resolve(space="cache", alias=target.relative_alias)
            if asset is None:
                raise CacheMissError("image is not cached; preload it first")
            size = asset.get("size_bytes")
            if not isinstance(size, int) or size < 0:
                raise CacheBackendError(502)
            if size > self.max_bytes:
                raise CacheBackendError(413)
            mime = asset.get("mime")
            if mime not in {"image/jpeg", "image/tiff"}:
                raise CacheBackendError(502)
            token = self._read_token()
            try:
                data = self.client.read_object(
                    capability_id=token,
                    qualified_alias=f"cache/{target.relative_alias}",
                    max_bytes=self.max_bytes,
                )
            except AssetStoreError as exc:
                if exc.status != 403:
                    raise
                data = self.client.read_object(
                    capability_id=self._read_token(stale=token),
                    qualified_alias=f"cache/{target.relative_alias}",
                    max_bytes=self.max_bytes,
                )
            checksum = "sha256:" + hashlib.sha256(data).hexdigest()
            if len(data) != size or checksum != asset.get("checksum"):
                raise CacheBackendError(502)
            return CachedImage(data=data, mime=mime, checksum=checksum)
        except AssetStoreError as exc:
            if exc.status in {404, 410}:
                raise CacheMissError("image is not cached; preload it first") from exc
            self._backend_error(exc)
        except httpx.HTTPError as exc:
            raise CacheBackendError(503, "1") from exc

    @staticmethod
    def _backend_error(exc: AssetStoreError) -> NoReturn:
        status = exc.status
        if status in {429, 503}:
            retry = exc.retry_after if exc.retry_after and exc.retry_after.isdigit() else "1"
            raise CacheBackendError(503, retry) from exc
        if status in {409, 410}:
            raise CacheBackendError(409, "1") from exc
        raise CacheBackendError(413 if status == 413 else 502) from exc
