"""FastAPI application factory for the asset-store prototype (ADR-002).

One process exposing the reserve/commit/resolve registry operations and capability
minting over HTTP, plus ``/healthz`` and ``/readyz`` probes. Storage is the
in-memory core; Postgres and a real S3 backend are wired later behind the same
interfaces.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from asset_store_core.api.errors import register_exception_handlers
from asset_store_core.api.metrics import SERVICE_NAME, build_metrics
from asset_store_core.api.observability import ObservabilityMiddleware, configure_logging
from asset_store_core.api.schemas import (
    AssetOut,
    CapabilityMintRequest,
    CapabilityOut,
    CommitRequest,
    ReserveRequest,
)
from asset_store_core.capabilities import Capability
from asset_store_core.errors import CapabilityDeniedError
from asset_store_core.models import utcnow
from asset_store_core.object_store import LocalObjectStore, ObjectStoreBackend
from asset_store_core.paths import normalize_space
from asset_store_core.registry import InMemoryAssetRegistry
from asset_store_core.service_policy import assert_service_bucket_allowed


def create_app(
    *,
    registry: InMemoryAssetRegistry | None = None,
    store: ObjectStoreBackend | None = None,
) -> FastAPI:
    """Build the FastAPI app, optionally injecting registry/store for tests."""

    registry = registry if registry is not None else InMemoryAssetRegistry()
    store = store if store is not None else LocalObjectStore()
    metrics = build_metrics()
    logger = configure_logging()

    app = FastAPI(title="asset-store", version="0.1.0")
    app.state.registry = registry
    app.state.store = store
    app.state.metrics = metrics
    app.add_middleware(ObservabilityMiddleware, metrics=metrics, logger=logger)
    register_exception_handlers(app)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        return {"status": "ready"}

    @app.get("/metrics")
    def metrics_endpoint() -> Response:
        return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)

    @app.post("/assets", status_code=201, response_model=AssetOut)
    def reserve(body: ReserveRequest) -> AssetOut:
        asset = registry.reserve_asset(
            space=body.space,
            partition_id=body.partition_id,
            aliases={spec.name: spec.mutable for spec in body.aliases},
            owner_service_id=body.owner_service_id,
            mime=body.mime,
            annotations=body.annotations,
        )
        return AssetOut.from_asset(asset)

    @app.post("/assets/{asset_id}/commit", response_model=AssetOut)
    def commit(asset_id: str, body: CommitRequest) -> AssetOut:
        asset = registry.commit_asset(
            asset_id=asset_id,
            size_bytes=body.size_bytes,
            checksum=body.checksum,
            caller_service_id=body.caller_service_id,
            mime=body.mime,
            expected_checksum=body.expected_checksum,
        )
        return AssetOut.from_asset(asset)

    @app.get("/resolve", response_model=AssetOut)
    def resolve(space: str, alias: str) -> AssetOut:
        return AssetOut.from_asset(registry.resolve_alias(space=space, alias=alias))

    @app.post("/capabilities", status_code=201, response_model=CapabilityOut)
    def mint_capability(body: CapabilityMintRequest) -> CapabilityOut:
        bucket = normalize_space(body.scope_prefix.strip("/").split("/", 1)[0])
        try:
            assert_service_bucket_allowed(body.caller_service_id, bucket, operation=body.operation)
        except CapabilityDeniedError:
            metrics.capability_issued_total.labels(
                SERVICE_NAME, body.operation.value, "denied"
            ).inc()
            raise
        cap = Capability(
            capability_id=f"cap-{uuid4().hex}",
            operation=body.operation,
            scope_prefix=body.scope_prefix,
            expires_at=utcnow() + timedelta(seconds=body.ttl_seconds),
            caller_service_id=body.caller_service_id,
            single_use=body.single_use,
        )
        metrics.capability_issued_total.labels(SERVICE_NAME, body.operation.value, "granted").inc()
        return CapabilityOut(
            capability_id=cap.capability_id,
            operation=cap.operation.value,
            scope_prefix=cap.scope_prefix,
            caller_service_id=cap.caller_service_id,
            expires_at=cap.expires_at,
            single_use=cap.single_use,
        )

    return app
