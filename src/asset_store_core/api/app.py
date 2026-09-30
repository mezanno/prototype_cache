"""FastAPI application factory for the asset-store prototype (ADR-002).

One process exposing the reserve/commit/resolve registry operations, asset and
alias lifecycle transitions (expire/delete/annotations, alias detach/rebind),
capability minting, and a capability-guarded data plane (``PUT``/``GET
/objects/{alias}``) over HTTP, plus ``/healthz``, ``/readyz`` and ``/metrics``.
Minted capabilities double as opaque bearer tokens presented via
``Authorization: Capability <id>`` (ADR-003 proxy mode). The environment factory
selects Postgres and S3 backends; in-memory adapters
remain available for local development and tests.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

from fastapi import Depends, FastAPI, Query, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

from asset_store_core.admission import (
    WorkAdmission,
    positive_limit_from_env,
    run_work_until_complete,
)
from asset_store_core.api.admin import install_admin
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
    PresignedUrlOut,
    ReserveRequest,
)
from asset_store_core.capabilities import Capability, CapabilityStore, Operation
from asset_store_core.errors import (
    CapabilityCapacityError,
    CapabilityDeniedError,
    ChecksumMismatchError,
    ObjectNotFoundError,
    ServiceAuthError,
    UploadTooLargeError,
    ValidationError,
)
from asset_store_core.guard import DEFAULT_PRESIGN_TTL_SECONDS, StorageGuard
from asset_store_core.models import utcnow
from asset_store_core.object_store import LocalObjectStore, ObjectStoreBackend
from asset_store_core.paths import normalize_space
from asset_store_core.registry import InMemoryAssetRegistry
from asset_store_core.registry_base import AssetRegistry
from asset_store_core.service_identity import ServiceCredentialStore
from asset_store_core.service_policy import assert_service_bucket_allowed
from asset_store_core.storage import ObjectStoreLocation

CAPABILITY_SCHEME = "capability"
SERVICE_SCHEME = "service"


def create_app(
    *,
    registry: AssetRegistry | None = None,
    store: ObjectStoreBackend | None = None,
    credentials: ServiceCredentialStore | None = None,
    close_registry: Callable[[], None] | None = None,
) -> FastAPI:
    """Build the FastAPI app, optionally injecting registry/store for tests."""

    registry = registry if registry is not None else InMemoryAssetRegistry()
    store = store if store is not None else LocalObjectStore()
    credentials = credentials if credentials is not None else ServiceCredentialStore.from_env()
    max_upload_bytes = int(os.environ.get("ASSET_STORE_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
    if max_upload_bytes <= 0:
        raise ValidationError("ASSET_STORE_MAX_UPLOAD_BYTES must be positive")
    raw_max_capabilities = os.environ.get("ASSET_STORE_MAX_CAPABILITIES", "10000")
    try:
        max_capabilities = int(raw_max_capabilities)
    except ValueError as exc:
        raise ValidationError("ASSET_STORE_MAX_CAPABILITIES must be a positive integer") from exc
    capabilities = CapabilityStore(max_capabilities, clock=lambda: utcnow())
    metrics = build_metrics()
    guard = StorageGuard(registry, store, metrics_registry=metrics.registry)
    metrics.active_capabilities.set_function(lambda: len(capabilities))
    register_metrics = getattr(registry, "register_metrics", None)
    if register_metrics is not None:
        register_metrics(metrics.registry)
    logger = configure_logging()
    uploads = WorkAdmission(
        limit=positive_limit_from_env("ASSET_STORE_MAX_INFLIGHT_UPLOADS", 4),
        name="asset_store_upload",
        metrics=metrics.registry,
        logger=logger,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if close_registry is not None:
                close_registry()

    app = FastAPI(lifespan=lifespan, title="asset-store", version="0.1.0")
    app.state.registry = registry
    app.state.store = store
    app.state.uploads = uploads
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

    def require_service_identity(request: Request) -> str:
        """Authenticate the caller via ``Authorization: Service <id>:<secret>`` (FR-014)."""

        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != SERVICE_SCHEME or not token.strip():
            raise ServiceAuthError("missing service credential")
        service_id, sep, secret = token.strip().partition(":")
        if not sep:
            raise ServiceAuthError("malformed service credential; expected 'service_id:secret'")
        return credentials.authenticate(service_id, secret)

    def require_admin(request: Request) -> str:
        caller = require_service_identity(request)
        if caller != "admin":
            raise CapabilityDeniedError("admin identity required")
        return caller

    async def require_legacy_admin(request: Request) -> str:
        caller = require_admin(request)
        if request.method in {"POST", "PUT", "PATCH"}:
            body = await request.json()
            if isinstance(body, dict) and body.get("caller_service_id", caller) != caller:
                raise CapabilityDeniedError("caller identity must match admin credential")
        return caller

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
    def reserve(body: ReserveRequest, caller: str = Depends(require_service_identity)) -> AssetOut:
        if body.owner_service_id != caller:
            raise CapabilityDeniedError("owner must match authenticated service")
        assert_service_bucket_allowed(caller, body.space, operation=Operation.WRITE)
        asset = registry.reserve_asset(
            space=body.space,
            partition_id=body.partition_id,
            aliases={spec.name: spec.mutable for spec in body.aliases},
            owner_service_id=body.owner_service_id,
            mime=body.mime,
            annotations=body.annotations,
            eviction_policy=body.eviction_policy,
            ttl_seconds=body.ttl_seconds,
        )
        return AssetOut.from_asset(asset)

    @app.post("/assets/{asset_id}/commit", response_model=AssetOut)
    def commit(
        asset_id: str, body: CommitRequest, caller: str = Depends(require_service_identity)
    ) -> AssetOut:
        if body.caller_service_id != caller:
            raise CapabilityDeniedError("caller must match authenticated service")
        with registry.asset_lock(asset_id) as pending:
            assert_service_bucket_allowed(caller, pending.space, operation=Operation.WRITE)
            if pending.owner_service_id != caller and caller != "admin":
                raise CapabilityDeniedError("commit requires reservation owner or admin")
            location = ObjectStoreLocation.for_asset(
                space=pending.space, partition_id=pending.partition_id, asset_id=pending.asset_id
            )
            stat = store.stat_object(location)
            if stat is None:
                raise ObjectNotFoundError("reserved payload does not exist")
            if body.size_bytes != stat.size_bytes or body.checksum != stat.checksum:
                raise ChecksumMismatchError("commit metadata differs from stored payload")
            asset = registry.commit_asset(
                asset_id=asset_id,
                size_bytes=stat.size_bytes,
                checksum=stat.checksum,
                caller_service_id=caller,
                mime=body.mime,
                expected_checksum=body.expected_checksum,
            )
        observe_bucket_fill(asset.space)
        return AssetOut.from_asset(asset)

    @app.get("/resolve", response_model=AssetOut)
    def resolve(
        space: str, alias: str, caller: str = Depends(require_service_identity)
    ) -> AssetOut:
        assert_service_bucket_allowed(caller, space, operation=Operation.READ)
        return AssetOut.from_asset(registry.resolve_alias(space=space, alias=alias))

    @app.patch(
        "/assets/{asset_id}/annotations",
        response_model=AssetOut,
        dependencies=[Depends(require_legacy_admin)],
    )
    def update_annotations(asset_id: str, body: AnnotationsUpdateRequest) -> AssetOut:
        asset = registry.update_annotations(
            asset_id=asset_id,
            patch=body.patch,
            caller_service_id=body.caller_service_id,
            overwrite=body.overwrite,
        )
        return AssetOut.from_asset(asset)

    @app.post(
        "/assets/{asset_id}/expire",
        response_model=AssetOut,
        dependencies=[Depends(require_legacy_admin)],
    )
    def expire(asset_id: str, body: LifecycleRequest) -> AssetOut:
        asset = registry.expire_asset(asset_id=asset_id, caller_service_id=body.caller_service_id)
        return AssetOut.from_asset(asset)

    @app.post(
        "/assets/{asset_id}/delete",
        response_model=AssetOut,
        dependencies=[Depends(require_legacy_admin)],
    )
    def delete(asset_id: str, body: LifecycleRequest) -> AssetOut:
        asset = registry.delete_asset(asset_id=asset_id, caller_service_id=body.caller_service_id)
        return AssetOut.from_asset(asset)

    @app.post("/aliases/detach", status_code=204, dependencies=[Depends(require_legacy_admin)])
    def detach_alias(body: AliasDetachRequest) -> Response:
        registry.detach_alias(
            space=body.space, alias=body.alias, caller_service_id=body.caller_service_id
        )
        return Response(status_code=204)

    @app.post(
        "/aliases/detach-mutable",
        response_model=AliasBindingOut,
        dependencies=[Depends(require_legacy_admin)],
    )
    def detach_mutable_alias(body: AliasDetachRequest) -> AliasBindingOut:
        binding = registry.detach_mutable_alias(
            space=body.space, alias=body.alias, caller_service_id=body.caller_service_id
        )
        return AliasBindingOut.from_binding(binding)

    @app.post(
        "/aliases/rebind",
        response_model=AliasBindingOut,
        dependencies=[Depends(require_legacy_admin)],
    )
    def rebind_alias(body: AliasRebindRequest) -> AliasBindingOut:
        binding = registry.rebind_alias(
            space=body.space,
            alias=body.alias,
            new_asset_id=body.new_asset_id,
            caller_service_id=body.caller_service_id,
        )
        return AliasBindingOut.from_binding(binding)

    @app.patch(
        "/assets/{asset_id}/eviction-policy",
        response_model=AssetOut,
        dependencies=[Depends(require_legacy_admin)],
    )
    def set_eviction_policy(asset_id: str, body: EvictionPolicyRequest) -> AssetOut:
        asset = registry.set_eviction_policy(
            asset_id=asset_id,
            eviction_policy=body.eviction_policy,
            caller_service_id=body.caller_service_id,
        )
        return AssetOut.from_asset(asset)

    @app.put(
        "/quotas/partition",
        response_model=PartitionQuotaOut,
        dependencies=[Depends(require_legacy_admin)],
    )
    def set_partition_quota(body: PartitionQuotaRequest) -> PartitionQuotaOut:
        quota = registry.set_partition_quota(
            space=body.space,
            partition_id=body.partition_id,
            quota_bytes=body.quota_bytes,
            quota_asset_count=body.quota_asset_count,
            eviction_sweep_enabled=body.eviction_sweep_enabled,
            caller_service_id="admin",
        )
        return PartitionQuotaOut.from_quota(quota)

    @app.get(
        "/quotas/partition",
        response_model=PartitionQuotaOut,
        dependencies=[Depends(require_legacy_admin)],
    )
    def get_partition_quota(space: str, partition_id: str) -> PartitionQuotaOut:
        quota = registry.get_partition_quota(space=space, partition_id=partition_id)
        return PartitionQuotaOut.from_quota(quota)

    @app.put(
        "/quotas/bucket",
        response_model=BucketQuotaOut,
        dependencies=[Depends(require_legacy_admin)],
    )
    def set_bucket_quota(body: BucketQuotaRequest) -> BucketQuotaOut:
        quota = registry.set_bucket_quota(
            space=body.space,
            quota_bytes=body.quota_bytes,
            warn_threshold=body.warn_threshold,
            hard_ceiling=body.hard_ceiling,
        )
        return BucketQuotaOut.from_quota(quota)

    @app.get(
        "/quotas/bucket",
        response_model=BucketQuotaOut,
        dependencies=[Depends(require_legacy_admin)],
    )
    def get_bucket_quota(space: str) -> BucketQuotaOut:
        return BucketQuotaOut.from_quota(registry.get_bucket_quota(space=space))

    @app.get(
        "/audit", response_model=list[AuditEventOut], dependencies=[Depends(require_legacy_admin)]
    )
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
    def mint_capability(
        body: CapabilityMintRequest,
        caller_service_id: str = Depends(require_service_identity),
    ) -> CapabilityOut:
        bucket = normalize_space(body.scope_prefix.strip("/").split("/", 1)[0])
        try:
            assert_service_bucket_allowed(caller_service_id, bucket, operation=body.operation)
        except CapabilityDeniedError:
            metrics.capability_issued_total.labels(
                SERVICE_NAME, body.operation.value, "denied"
            ).inc()
            registry.record_capability_issue(
                caller_service_id=caller_service_id,
                operation=body.operation.value,
                scope_prefix=body.scope_prefix,
                ttl_seconds=body.ttl_seconds,
                outcome="denied",
            )
            raise
        cap = Capability(
            capability_id=f"cap-{uuid4().hex}",
            operation=body.operation,
            scope_prefix=body.scope_prefix,
            expires_at=utcnow() + timedelta(seconds=body.ttl_seconds),
            caller_service_id=caller_service_id,
            single_use=body.single_use,
        )
        guard.prune_consumed_capabilities()

        def audit_grant() -> None:
            registry.record_capability_issue(
                caller_service_id=caller_service_id,
                operation=body.operation.value,
                scope_prefix=body.scope_prefix,
                ttl_seconds=body.ttl_seconds,
                outcome="granted",
                capability_id=cap.capability_id,
            )

        try:
            capabilities.issue(cap, on_grant=audit_grant)
        except CapabilityCapacityError:
            metrics.capability_issued_total.labels(
                SERVICE_NAME, body.operation.value, "capacity_denied"
            ).inc()
            logger.warning(
                "capability capacity reached",
                extra={"event": "capability.capacity_denied"},
            )
            raise
        metrics.capability_issued_total.labels(SERVICE_NAME, body.operation.value, "granted").inc()
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
        ttl_seconds: int | None = Query(default=None, gt=0),
    ) -> AssetOut:
        guard.authorize_write(capability=capability, alias=alias)
        declared_size = request.headers.get("content-length")
        if declared_size is not None:
            try:
                size = int(declared_size)
            except ValueError as exc:
                raise ValidationError("invalid Content-Length") from exc
            if size < 0:
                raise ValidationError("invalid Content-Length")
            if size > max_upload_bytes:
                raise UploadTooLargeError("proxy upload exceeds configured byte limit")
        with uploads.lease():
            data = bytearray()
            async for chunk in request.stream():
                if len(data) + len(chunk) > max_upload_bytes:
                    raise UploadTooLargeError("proxy upload exceeds configured byte limit")
                data.extend(chunk)
            mime = request.headers.get("content-type")
            asset = await run_work_until_complete(
                guard.write_object,
                capability=capability,
                alias=alias,
                data=bytes(data),
                mutable=mutable,
                mime=mime,
                expected_checksum=expected_checksum,
                ttl_seconds=ttl_seconds,
            )
            observe_bucket_fill(asset.space)
        return AssetOut.from_asset(asset)

    @app.get("/objects/{alias:path}", response_model=None)
    def read_object(
        alias: str,
        capability: Capability = Depends(require_capability),
        mode: str = Query("proxy"),
        expires_in: int = Query(DEFAULT_PRESIGN_TTL_SECONDS, ge=1, le=3600),
    ) -> Response | PresignedUrlOut:
        if mode == "presign":
            presigned = guard.presign_read(
                capability=capability, alias=alias, expires_in=expires_in
            )
            asset = presigned.asset
            return PresignedUrlOut(
                alias=alias,
                asset_id=asset.asset_id,
                url=presigned.url,
                expires_in=presigned.expires_in,
                expires_at=presigned.expires_at,
                size_bytes=asset.size_bytes,
                checksum=asset.checksum,
            )
        if mode != "proxy":
            raise ValidationError("mode must be 'proxy' or 'presign'")
        data = guard.read_bytes(capability=capability, alias=alias)
        return Response(content=data, media_type="application/octet-stream")

    install_admin(
        app,
        registry,
        require_admin,
        Counter(
            "asset_store_admin_actions_total",
            "Admin mutation attempts by action and outcome",
            ["action", "outcome"],
            registry=metrics.registry,
        ),
        logger,
    )
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

    credentials = ServiceCredentialStore.from_env()
    registry: AssetRegistry | None = None
    close_registry: Callable[[], None] | None = None
    dsn = os.environ.get("ASSET_STORE_PG_DSN")
    if dsn:
        from asset_store_core.pg_registry import PostgresAssetRegistry

        registry = PostgresAssetRegistry.connect(dsn)
        close_registry = registry.close

    try:
        return create_app(
            registry=registry, store=store, credentials=credentials, close_registry=close_registry
        )
    except BaseException:
        if close_registry is not None:
            close_registry()
        raise
