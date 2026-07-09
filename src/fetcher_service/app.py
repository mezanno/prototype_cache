"""FastAPI application factory for the fetcher-service stub (B-020, Step 1).

Exposes ``POST /v1/ensure-url`` plus ``/healthz`` and ``/readyz``. The app is a
thin HTTP shell over :func:`fetcher_service.service.ensure_url`; the asset-store
client, rule set, and fetcher seam are injectable for tests. By default it builds
an :class:`~fetcher_service.client.AssetStoreClient` from the environment and the
Step-1 :class:`~fetcher_service.fetcher.SyntheticFetcher` (no outbound network).
"""

from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from fetcher_service.client import AssetStoreClient, AssetStoreError
from fetcher_service.config import rule_set_from_env
from fetcher_service.fetcher import SyntheticFetcher, UrlFetcher, http_fetcher_from_env
from fetcher_service.rules import RuleSet, default_rule_set
from fetcher_service.service import (
    EnsureUrlResult,
    FetcherError,
    InvalidRequestError,
    UpstreamError,
    UpstreamTimeoutError,
    ensure_url,
)

DEFAULT_ASSET_STORE_BASE_URL = "http://localhost:8080"
DEFAULT_FETCHER_SECRET = "dev-secret:fetcher"


class EnsureUrlRequest(BaseModel):
    """Request body for ``POST /v1/ensure-url``."""

    url: str = Field(min_length=1)
    mirror_id: str | None = None
    no_cache: bool = False
    tmp_id: str | None = None
    preferred_alias_suffix: str | None = None
    ttl_seconds: int = Field(default=3600, ge=1, le=86_400)


class EnsureUrlResponse(BaseModel):
    """Response body for ``POST /v1/ensure-url``."""

    asset_id: str
    qualified_alias: str
    cache_hit: bool
    bucket: str
    partition_id: str

    @classmethod
    def from_result(cls, result: EnsureUrlResult) -> EnsureUrlResponse:
        return cls(
            asset_id=result.asset_id,
            qualified_alias=result.qualified_alias,
            cache_hit=result.cache_hit,
            bucket=result.bucket,
            partition_id=result.partition_id,
        )


def _problem(status: int, title: str, detail: str) -> JSONResponse:
    """Build an RFC 7807 problem+json response."""

    return JSONResponse(
        status_code=status,
        content={"type": "about:blank", "title": title, "status": status, "detail": detail},
        media_type="application/problem+json",
    )


def create_app(
    *,
    asset_store_client: AssetStoreClient | None = None,
    rules: RuleSet | None = None,
    fetcher: UrlFetcher | None = None,
) -> FastAPI:
    """Build the fetcher FastAPI app, optionally injecting dependencies for tests."""

    rules = rules if rules is not None else _rules_from_env()
    fetcher = fetcher if fetcher is not None else _fetcher_from_env()
    client = asset_store_client if asset_store_client is not None else _client_from_env()

    app = FastAPI(title="fetcher-service", version="0.1.0")
    app.state.asset_store_client = client
    app.state.rules = rules
    app.state.fetcher = fetcher

    @app.exception_handler(FetcherError)
    async def _fetcher_error(_request: Request, exc: FetcherError) -> JSONResponse:
        if isinstance(exc, InvalidRequestError):
            return _problem(400, "Invalid request", str(exc))
        if isinstance(exc, UpstreamTimeoutError):
            return _problem(504, "Upstream timeout", str(exc))
        if isinstance(exc, UpstreamError):
            return _problem(502, "Upstream fetch failed", str(exc))
        return _problem(400, "Fetcher error", str(exc))

    @app.exception_handler(AssetStoreError)
    async def _asset_store_error(_request: Request, exc: AssetStoreError) -> JSONResponse:
        return _problem(502, "Asset-store call failed", str(exc))

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        return {"status": "ready"}

    @app.post("/v1/ensure-url", response_model=EnsureUrlResponse)
    def ensure_url_endpoint(body: EnsureUrlRequest) -> EnsureUrlResponse:
        result = ensure_url(
            client,
            rules,
            fetcher,
            url=body.url,
            mirror_id=body.mirror_id,
            no_cache=body.no_cache,
            tmp_id=body.tmp_id,
            preferred_alias_suffix=body.preferred_alias_suffix,
            capability_ttl_seconds=body.ttl_seconds,
        )
        return EnsureUrlResponse.from_result(result)

    return app


def _client_from_env() -> AssetStoreClient:
    """Build an :class:`AssetStoreClient` from environment variables."""

    base_url = os.environ.get("ASSET_STORE_BASE_URL", DEFAULT_ASSET_STORE_BASE_URL)
    secret = os.environ.get("FETCHER_SERVICE_SECRET", DEFAULT_FETCHER_SECRET)
    service_id = os.environ.get("FETCHER_SERVICE_ID", "fetcher")
    http = httpx.Client(base_url=base_url, timeout=30.0)
    return AssetStoreClient(http, service_id=service_id, service_secret=secret)


def _rules_from_env() -> RuleSet:
    """Load the rule set from ``FETCHER_RULES_FILE`` or fall back to the default."""

    return rule_set_from_env() or default_rule_set()


def _fetcher_from_env() -> UrlFetcher:
    """Real HTTP fetcher by default; the no-network stub when ``FETCHER_SYNTHETIC`` is set."""

    if os.environ.get("FETCHER_SYNTHETIC", "").lower() in {"1", "true", "yes"}:
        return SyntheticFetcher()
    return http_fetcher_from_env()
