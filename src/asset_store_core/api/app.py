"""FastAPI application factory for the asset-store prototype (ADR-002).

One process exposing the reserve/commit/resolve registry operations, asset and
alias lifecycle transitions (expire/delete/annotations, alias detach/rebind),
capability minting, and a capability-guarded data plane (``PUT``/``GET
/objects/{alias}``) over HTTP, plus ``/healthz``, ``/readyz`` and ``/metrics``.
Minted capabilities double as opaque bearer tokens presented via
``Authorization: Capability <id>`` (ADR-003 proxy mode). Storage is the in-memory
core; Postgres and a real S3 backend are wired later behind the same interfaces.
"""

from __future__ import annotations

import os
from datetime import timedelta
from uuid import uuid4

from fastapi import Depends, FastAPI, Query, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from asset_store_core.api.errors import register_exception_handlers
from asset_store_core.api.metrics import SERVICE_NAME, build_metrics
from asset_store_core.api.observability import ObservabilityMiddleware, configure_logging
from asset_store_core.api.schemas import (
    AliasBindingOut,
    AliasDetachRequest,
    AliasRebindRequest,
    AnnotationsUpdateRequest,
    AssetOut,
    AuditEventOut,
    BucketQuotaOut,
    BucketQuotaRequest,
    CapabilityMintRequest,
    CapabilityOut,
    CommitRequest,
    EvictionPolicyRequest,
    LifecycleRequest,
    PartitionQuotaOut,
    PartitionQuotaRequest,
    ReserveRequest,
)
from asset_store_core.capabilities import Capability
from asset_store_core.errors import CapabilityDeniedError
from asset_store_core.guard import StorageGuard
from asset_store_core.models import utcnow
from asset_store_core.object_store import LocalObjectStore, ObjectStoreBackend
from asset_store_core.paths import normalize_space
from asset_store_core.registry import InMemoryAssetRegistry
from asset_store_core.registry_base import AssetRegistry
from asset_store_core.service_policy import assert_service_bucket_allowed

CAPABILITY_SCHEME = "capability"


def create_app(
    *,
    registry: AssetRegistry | None = None,
    store: ObjectStoreBackend | None = None,
) -> FastAPI:
    """Build the FastAPI app, optionally injecting registry/store for tests."""

    registry = registry if registry is not None else InMemoryAssetRegistry()
    store = store if store is not None else LocalObjectStore()
    guard = StorageGuard(registry, store)
    capabilities: dict[str, Capability] = {}
    metrics = build_metrics()
    logger = configure_logging()

    app = FastAPI(title="asset-store", version="0.1.0")
    app.state.registry = registry
    app.state.store = store
    app.state.guard = guard
    app.state.capabilities = capabilities
    app.state.metrics = metrics
    app.add_middleware(ObservabilityMiddleware, metrics=metrics, logger=logger)
    register_exception_handlers(app)

    def observe_bucket_fill(space: str) -> None:
        """Publish the bucket fill ratio and warn when it crosses ``warn_threshold``.

        Called after every successful commit (FR-068, ADR-009). The async LFU
        eviction sweep (FR-064/FR-067) stays deferred to the lifecycle worker;
        this only surfaces the warn signal for dashboards and alerts.
        """

        quota = registry.get_bucket_quota(space=space)
        if quota.quota_bytes is None or quota.quota_bytes <= 0:
            return
        ratio = quota.used_bytes / quota.quota_bytes
        metrics.bucket_fill_ratio.labels(SERVICE_NAME, quota.space).set(ratio)
        if ratio >= quota.warn_threshold:
            logger.warning(
                "bucket %s at %.1f%% of quota (%d/%d bytes, warn>=%.0f%%)",
                quota.space,
                ratio * 100,
                quota.used_bytes,
                quota.quota_bytes,
                quota.warn_threshold * 100,
                extra={"event": "quota.bucket_warn", "space": quota.space},
            )

    def require_capability(request: Request) -> Capability:
        """Resolve the bearer capability from ``Authorization: Capability <id>``."""

        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != CAPABILITY_SCHEME or not token.strip():
            raise CapabilityDeniedError("missing capability credential")
        capability = capabilities.get(token.strip())
        if capability is None:
            raise CapabilityDeniedError("unknown capability credential")
        return capability

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
            eviction_policy=body.eviction_policy,
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
        observe_bucket_fill(asset.space)
        return AssetOut.from_asset(asset)

    @app.get("/resolve", response_model=AssetOut)
    def resolve(space: str, alias: str) -> AssetOut:
        return AssetOut.from_asset(registry.resolve_alias(space=space, alias=alias))

    @app.patch("/assets/{asset_id}/annotations", response_model=AssetOut)
    def update_annotations(asset_id: str, body: AnnotationsUpdateRequest) -> AssetOut:
        asset = registry.update_annotations(
            asset_id=asset_id,
            patch=body.patch,
            caller_service_id=body.caller_service_id,
            overwrite=body.overwrite,
        )
        return AssetOut.from_asset(asset)

    @app.post("/assets/{asset_id}/expire", response_model=AssetOut)
    def expire(asset_id: str, body: LifecycleRequest) -> AssetOut:
        asset = registry.expire_asset(asset_id=asset_id, caller_service_id=body.caller_service_id)
        return AssetOut.from_asset(asset)

    @app.post("/assets/{asset_id}/delete", response_model=AssetOut)
    def delete(asset_id: str, body: LifecycleRequest) -> AssetOut:
        asset = registry.delete_asset(asset_id=asset_id, caller_service_id=body.caller_service_id)
        return AssetOut.from_asset(asset)

    @app.post("/aliases/detach", status_code=204)
    def detach_alias(body: AliasDetachRequest) -> Response:
        registry.detach_alias(
            space=body.space, alias=body.alias, caller_service_id=body.caller_service_id
        )
        return Response(status_code=204)

    @app.post("/aliases/detach-mutable", response_model=AliasBindingOut)
    def detach_mutable_alias(body: AliasDetachRequest) -> AliasBindingOut:
        binding = registry.detach_mutable_alias(
            space=body.space, alias=body.alias, caller_service_id=body.caller_service_id
        )
        return AliasBindingOut.from_binding(binding)

    @app.post("/aliases/rebind", response_model=AliasBindingOut)
    def rebind_alias(body: AliasRebindRequest) -> AliasBindingOut:
        binding = registry.rebind_alias(
            space=body.space,
            alias=body.alias,
            new_asset_id=body.new_asset_id,
            caller_service_id=body.caller_service_id,
        )
        return AliasBindingOut.from_binding(binding)

    @app.patch("/assets/{asset_id}/eviction-policy", response_model=AssetOut)
    def set_eviction_policy(asset_id: str, body: EvictionPolicyRequest) -> AssetOut:
        asset = registry.set_eviction_policy(
            asset_id=asset_id,
            eviction_policy=body.eviction_policy,
            caller_service_id=body.caller_service_id,
        )
        return AssetOut.from_asset(asset)

    @app.put("/quotas/partition", response_model=PartitionQuotaOut)
    def set_partition_quota(body: PartitionQuotaRequest) -> PartitionQuotaOut:
        quota = registry.set_partition_quota(
            space=body.space,
            partition_id=body.partition_id,
            quota_bytes=body.quota_bytes,
            quota_asset_count=body.quota_asset_count,
            eviction_sweep_enabled=body.eviction_sweep_enabled,
        )
        return PartitionQuotaOut.from_quota(quota)

    @app.get("/quotas/partition", response_model=PartitionQuotaOut)
    def get_partition_quota(space: str, partition_id: str) -> PartitionQuotaOut:
        quota = registry.get_partition_quota(space=space, partition_id=partition_id)
        return PartitionQuotaOut.from_quota(quota)

    @app.put("/quotas/bucket", response_model=BucketQuotaOut)
    def set_bucket_quota(body: BucketQuotaRequest) -> BucketQuotaOut:
        quota = registry.set_bucket_quota(
            space=body.space,
            quota_bytes=body.quota_bytes,
            warn_threshold=body.warn_threshold,
            hard_ceiling=body.hard_ceiling,
        )
        return BucketQuotaOut.from_quota(quota)

    @app.get("/quotas/bucket", response_model=BucketQuotaOut)
    def get_bucket_quota(space: str) -> BucketQuotaOut:
        return BucketQuotaOut.from_quota(registry.get_bucket_quota(space=space))

    @app.get("/audit", response_model=list[AuditEventOut])
    def list_audit(
        action: str | None = None,
        target: str | None = None,
        caller_service_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> list[AuditEventOut]:
        matched = [
            event
            for event in registry.audit_events
            if (action is None or event.action == action)
            and (target is None or event.target == target)
            and (caller_service_id is None or event.caller_service_id == caller_service_id)
        ]
        return [AuditEventOut.from_event(event) for event in matched[-limit:]]

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
        capabilities[cap.capability_id] = cap
        return CapabilityOut(
            capability_id=cap.capability_id,
            operation=cap.operation.value,
            scope_prefix=cap.scope_prefix,
            caller_service_id=cap.caller_service_id,
            expires_at=cap.expires_at,
            single_use=cap.single_use,
        )

    @app.put("/objects/{alias:path}", status_code=201, response_model=AssetOut)
    async def write_object(
        alias: str,
        request: Request,
        capability: Capability = Depends(require_capability),
        mutable: bool = False,
        expected_checksum: str | None = None,
    ) -> AssetOut:
        data = await request.body()
        mime = request.headers.get("content-type")
        asset = guard.write_object(
            capability=capability,
            alias=alias,
            data=data,
            mutable=mutable,
            mime=mime,
            expected_checksum=expected_checksum,
        )
        observe_bucket_fill(asset.space)
        return AssetOut.from_asset(asset)

    @app.get("/objects/{alias:path}")
    def read_object(
        alias: str,
        capability: Capability = Depends(require_capability),
    ) -> Response:
        data = guard.read_bytes(capability=capability, alias=alias)
        return Response(content=data, media_type="application/octet-stream")

    return app


def _require_env(name: str) -> str:
    """Return env var ``name`` or raise a clear startup error (B-002)."""

    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def create_app_from_env() -> FastAPI:
    """Build the app selecting backends from environment variables (B-002).

    Used as the uvicorn ASGI factory in the compose/Swarm stacks. When
    ``ASSET_STORE_S3_ENDPOINT`` is set, the durable
    :class:`~asset_store_core.s3_object_store.S3ObjectStore` is wired (reading
    ``ASSET_STORE_S3_REGION``/``_ACCESS_KEY``/``_SECRET_KEY``); otherwise the
    in-memory :class:`~asset_store_core.object_store.LocalObjectStore` is used.

    When ``ASSET_STORE_PG_DSN`` is set, the durable
    :class:`~asset_store_core.pg_registry.PostgresAssetRegistry` is wired (B-009);
    otherwise the in-memory :class:`~asset_store_core.registry.InMemoryAssetRegistry`
    is used.
    """

    store: ObjectStoreBackend | None = None
    endpoint = os.environ.get("ASSET_STORE_S3_ENDPOINT")
    if endpoint:
        from asset_store_core.s3_object_store import S3ObjectStore

        store = S3ObjectStore(
            endpoint_url=endpoint,
            region=os.environ.get("ASSET_STORE_S3_REGION", "garage"),
            access_key=_require_env("ASSET_STORE_S3_ACCESS_KEY"),
            secret_key=_require_env("ASSET_STORE_S3_SECRET_KEY"),
        )

    registry: AssetRegistry | None = None
    dsn = os.environ.get("ASSET_STORE_PG_DSN")
    if dsn:
        from asset_store_core.pg_registry import PostgresAssetRegistry

        registry = PostgresAssetRegistry.connect(dsn)

    return create_app(registry=registry, store=store)
