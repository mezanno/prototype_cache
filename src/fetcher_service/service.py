"""``ensure_url`` orchestration (SCN-007, fetcher-service contract).

Ties the pieces together: normalize the URL, evaluate the rewrite rules, look up
the cache, and on a miss materialize bytes (Step 1: the synthetic stub) and store
them through asset-store. Cacheable URLs land in ``cache/{mirror_id}/…``;
non-cacheable URLs stage in ``tmp/{tmp_id}/…``. asset-store performs no outbound
HTTP (ADR-008); all fetching happens here behind the :class:`UrlFetcher` seam.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from fetcher_service.client import AssetStoreClient
from fetcher_service.fetcher import UrlFetcher
from fetcher_service.normalize import InvalidUrl, NormalizedUrl, normalize_url
from fetcher_service.rules import RuleSet

CACHE_BUCKET = "cache"
TMP_BUCKET = "tmp"


class FetcherError(Exception):
    """Base class for fetcher request errors."""


class InvalidRequestError(FetcherError):
    """The request cannot be served as asked (bad URL, missing tmp_id). Maps to 400."""


class UpstreamError(FetcherError):
    """The origin fetch failed (connection, HTTP error, oversized body). Maps to 502.

    Raised by :class:`~fetcher_service.fetcher.UrlFetcher` implementations that
    perform outbound HTTP (Step 2). The Step-1 ``SyntheticFetcher`` never raises
    it; the class exists so the control flow and error mapping are settled now.
    """


class UpstreamTimeoutError(UpstreamError):
    """The origin fetch timed out. Maps to 504."""


@dataclass(frozen=True, slots=True)
class EnsureUrlResult:
    """Outcome of an ``ensure_url`` call."""

    asset_id: str
    qualified_alias: str
    cache_hit: bool
    bucket: str
    partition_id: str


def _tmp_alias_tail(normalized: NormalizedUrl, preferred_alias_suffix: str | None) -> str:
    """Derive a stable ``tmp`` alias tail for a non-cacheable URL."""

    if preferred_alias_suffix:
        return preferred_alias_suffix.strip("/")
    digest = hashlib.sha256(normalized.canonical.encode("utf-8")).hexdigest()[:32]
    return f"fetched/{digest}"


def ensure_url(
    client: AssetStoreClient,
    rules: RuleSet,
    fetcher: UrlFetcher,
    *,
    url: str,
    mirror_id: str | None = None,
    no_cache: bool = False,
    tmp_id: str | None = None,
    preferred_alias_suffix: str | None = None,
    capability_ttl_seconds: int = 3600,
) -> EnsureUrlResult:
    """Materialize ``url`` into asset-store and return its stable alias.

    Idempotent: a second call for the same URL resolves the existing alias
    (``cache_hit=True``) instead of re-fetching. On a cache miss the configured
    :class:`UrlFetcher` produces the bytes, which are written through the guarded
    proxy under a freshly minted, prefix-scoped write capability.
    """

    try:
        normalized = normalize_url(url)
    except InvalidUrl as exc:
        raise InvalidRequestError(str(exc)) from exc

    match = rules.evaluate(normalized)
    if match is not None:
        partition_id = match.mirror_id
        bucket = CACHE_BUCKET
        relative_alias = f"{partition_id}/{match.primary_alias}"
    else:
        if not tmp_id:
            raise InvalidRequestError(
                "URL is not cacheable by any rule; provide tmp_id to stage it in tmp"
            )
        partition_id = tmp_id.strip("/")
        bucket = TMP_BUCKET
        relative_alias = f"{partition_id}/{_tmp_alias_tail(normalized, preferred_alias_suffix)}"

    qualified = f"{bucket}/{relative_alias}"

    if not no_cache:
        existing = client.resolve(space=bucket, alias=relative_alias)
        if existing is not None:
            return EnsureUrlResult(
                asset_id=existing["asset_id"],
                qualified_alias=qualified,
                cache_hit=True,
                bucket=bucket,
                partition_id=partition_id,
            )

    content = fetcher.fetch(normalized.canonical)
    capability_id = client.mint_write_capability(
        scope_prefix=f"{bucket}/{partition_id}",
        ttl_seconds=capability_ttl_seconds,
    )
    asset = client.put_object(
        capability_id=capability_id,
        qualified_alias=qualified,
        data=content.data,
        mime=content.mime,
    )
    return EnsureUrlResult(
        asset_id=asset["asset_id"],
        qualified_alias=qualified,
        cache_hit=False,
        bucket=bucket,
        partition_id=partition_id,
    )
