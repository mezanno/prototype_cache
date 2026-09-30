"""FastAPI application for URL materialization and refetch checks (B-020).

Exposes ensure-url, health/readiness and Prometheus metrics. Dependencies are
injectable; the default fetcher performs real HTTP, with an optional synthetic
implementation selected via FETCHER_SYNTHETIC.
"""

from __future__ import annotations

import logging
import os

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, generate_latest
from pydantic import BaseModel, ConfigDict, Field

from asset_store_core.admission import (
    WorkAdmission,
    positive_limit_from_env,
    run_work_until_complete,
)
from asset_store_core.api.errors import register_exception_handlers
from asset_store_core.api.observability import JsonLogFormatter
from asset_store_core.errors import CapabilityDeniedError, ServiceAuthError
from asset_store_core.service_identity import ServiceCredentialStore
from fetcher_service.client import AssetStoreClient, AssetStoreError
from fetcher_service.config import rule_set_from_env
from fetcher_service.errors import (
    CacheBackendError,
    CacheMissError,
    ContentMismatchError,
    PilotDeniedError,
)
from fetcher_service.fetcher import SyntheticFetcher, UrlFetcher, http_fetcher_from_env
from fetcher_service.pilot import PilotCache
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


class PreloadRequest(BaseModel):
    """Explicitly populate one approved image; force refetch is opt-in."""

    model_config = ConfigDict(extra="forbid")
    url: str = Field(
        min_length=1,
        max_length=2048,
        examples=[
            "https://gallica.bnf.fr/iiif/ark:/12148/btv1b90017179/f15/full/800,/0/native.jpg"
        ],
    )
    no_cache: bool = False


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
    credentials: ServiceCredentialStore | None = None,
) -> FastAPI:
    """Build the fetcher FastAPI app, optionally injecting dependencies for tests."""

    credentials = credentials if credentials is not None else ServiceCredentialStore.from_env()
    rules = rules if rules is not None else _rules_from_env()
    fetcher = fetcher if fetcher is not None else _fetcher_from_env()
    client = asset_store_client if asset_store_client is not None else _client_from_env()

    app = FastAPI(title="fetcher-service", version="0.1.0")
    register_exception_handlers(app)

    async def require_dispatcher(request: Request) -> str:
        try:
            scheme, _, token = request.headers.get("authorization", "").partition(" ")
            identity, sep, secret = token.partition(":")
            if scheme.lower() != "service" or not sep:
                raise ServiceAuthError("missing service credential")
            caller = credentials.authenticate(identity, secret)
            if caller not in {"task-api", "admin"}:
                raise CapabilityDeniedError("fetcher requires task-api or admin identity")
        except (ServiceAuthError, CapabilityDeniedError):
            ingress_auth.labels("denied").inc()
            logger.warning(
                "fetch.ingress_auth denied",
                extra={"event": "fetch.ingress_auth", "outcome": "denied"},
            )
            raise
        ingress_auth.labels("granted").inc()
        return caller

    app.state.asset_store_client = client
    app.state.rules = rules
    app.state.fetcher = fetcher
    metrics = CollectorRegistry()
    register_metrics = getattr(fetcher, "register_metrics", None)
    if register_metrics is not None:
        register_metrics(metrics)
    ingress_auth = Counter(
        "fetcher_ingress_auth_total",
        "Fetcher dispatcher authentication outcomes.",
        ["outcome"],
        registry=metrics,
    )
    refetch_checks = Counter(
        "fetcher_refetch_checks_total",
        "Forced refetch checksum comparisons (R-011).",
        ["bucket", "outcome"],
        registry=metrics,
    )
    logger = logging.getLogger("fetcher_service")
    logger.setLevel(logging.INFO)
    if not any(isinstance(h.formatter, JsonLogFormatter) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonLogFormatter())
        logger.addHandler(handler)

    jobs = WorkAdmission(
        limit=positive_limit_from_env("FETCHER_MAX_INFLIGHT_JOBS", 4),
        name="fetcher_job",
        metrics=metrics,
        logger=logger,
    )
    app.state.jobs = jobs
    pilot = PilotCache(
        client,
        fetcher,
        max_bytes=positive_limit_from_env("FETCHER_HTTP_MAX_BYTES", 50 * 1024 * 1024),
    )
    app.state.pilot = pilot
    cache_operations = Counter(
        "fetcher_cache_operations_total",
        "Pilot cache operation outcomes.",
        ["operation", "outcome"],
        registry=metrics,
    )

    def record_cache(operation: str, outcome: str) -> None:
        cache_operations.labels(operation, outcome).inc()
        logger.info(
            "cache.operation",
            extra={
                "event": "cache.operation",
                "action": operation,
                "outcome": outcome,
                "service": "fetcher-service",
            },
        )

    def record_refetch(bucket: str, outcome: str) -> None:
        refetch_checks.labels(bucket, outcome).inc()

    @app.exception_handler(FetcherError)
    async def _fetcher_error(_request: Request, exc: FetcherError) -> JSONResponse:
        if isinstance(exc, PilotDeniedError):
            return _problem(403, "Cache policy denied", str(exc))
        if isinstance(exc, CacheMissError):
            return _problem(404, "Cache miss", str(exc))
        if isinstance(exc, CacheBackendError):
            response = _problem(exc.status, "Cache backend error", str(exc))
            if exc.retry_after:
                response.headers["Retry-After"] = exc.retry_after
            return response
        if isinstance(exc, ContentMismatchError):
            return _problem(409, "Cached content mismatch", str(exc))
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

    @app.get("/metrics")
    def prometheus_metrics() -> Response:
        return Response(generate_latest(metrics), media_type=CONTENT_TYPE_LATEST)

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        return {"status": "ready"}

    async def ensure_url_endpoint(body: EnsureUrlRequest) -> EnsureUrlResponse:
        with jobs.lease():
            result = await run_work_until_complete(
                ensure_url,
                client,
                rules,
                fetcher,
                url=body.url,
                mirror_id=body.mirror_id,
                no_cache=body.no_cache,
                tmp_id=body.tmp_id,
                preferred_alias_suffix=body.preferred_alias_suffix,
                capability_ttl_seconds=body.ttl_seconds,
                record_refetch=record_refetch,
            )
        return EnsureUrlResponse.from_result(result)

    if os.environ.get("FETCHER_PILOT_MODE", "").lower() not in {"1", "true", "yes"}:
        app.add_api_route(
            "/v1/ensure-url",
            ensure_url_endpoint,
            methods=["POST"],
            response_model=EnsureUrlResponse,
            dependencies=[Depends(require_dispatcher)],
        )

    @app.post(
        "/v1/cache/preload",
        response_model=EnsureUrlResponse,
        dependencies=[Depends(require_dispatcher)],
    )
    async def preload_cache(body: PreloadRequest) -> EnsureUrlResponse:
        try:
            with jobs.lease():
                result = await run_work_until_complete(
                    pilot.preload, body.url, no_cache=body.no_cache, record_refetch=record_refetch
                )
            record_cache("preload", "hit" if result.cache_hit else "stored")
            return EnsureUrlResponse.from_result(result)
        except Exception:
            record_cache("preload", "error")
            raise

    @app.get(
        "/{origin_host}/{origin_path:path}",
        dependencies=[Depends(require_dispatcher)],
        responses={
            200: {"content": {"image/jpeg": {}, "image/tiff": {}}},
            404: {"description": "Cache miss; preload first"},
        },
    )
    async def read_cache(origin_host: str, origin_path: str, request: Request) -> Response:
        try:
            target = pilot.policy.require_read(
                request.scope["raw_path"], request.scope["query_string"]
            )
            with jobs.lease():
                image = await run_work_until_complete(pilot.read, target)
            record_cache("read", "hit")
            return Response(
                image.data,
                media_type=image.mime,
                headers={
                    "ETag": '"' + image.checksum + '"',
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                },
            )
        except CacheMissError:
            record_cache("read", "miss")
            raise
        except Exception:
            record_cache("read", "error")
            raise

    return app


def _client_from_env() -> AssetStoreClient:
    """Build an :class:`AssetStoreClient` from environment variables."""

    base_url = os.environ.get("ASSET_STORE_BASE_URL", DEFAULT_ASSET_STORE_BASE_URL)
    secret = os.environ.get("FETCHER_SERVICE_SECRET")
    if not secret:
        if os.environ.get("ASSET_STORE_DEV_MODE", "").lower() not in {"1", "true", "yes"}:
            raise RuntimeError("FETCHER_SERVICE_SECRET is required outside explicit dev mode")
        secret = DEFAULT_FETCHER_SECRET
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
