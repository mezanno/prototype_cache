"""Authenticated operator console and API (B-013, FR-040..042, ADR-021)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from logging import Logger
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, Query, Response
from fastapi.responses import FileResponse
from prometheus_client import Counter
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from asset_store_core.admin_query import AssetQuery, prefix_matches
from asset_store_core.api.schemas import (
    AssetOut,
    AuditEventOut,
    PartitionQuotaOut,
    PartitionQuotaRequest,
)
from asset_store_core.errors import (
    AliasImmutableError,
    InvalidStateTransitionError,
    ValidationError,
)
from asset_store_core.models import Asset, AssetState, EvictionPolicy
from asset_store_core.registry_base import AssetRegistry


class Mutation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: AwareDatetime
    action: Literal["expire", "delete", "ttl", "attach", "detach", "annotations", "eviction"]
    ttl_seconds: int | None = Field(default=None, gt=0)
    alias: str | None = None
    mutable: bool = False
    annotations: dict[str, str] | None = None
    eviction_policy: EvictionPolicy | None = None


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str
    expected_updated_at: AwareDatetime


class BulkApply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates: list[Candidate] = Field(max_length=500)


def public_asset(asset: Asset) -> dict[str, object]:
    return AssetOut.from_asset(asset).model_dump(mode="json", exclude={"storage_key"})


def install_admin(
    app: FastAPI,
    registry: AssetRegistry,
    require_admin: Callable[..., str],
    counter: Counter,
    logger: Logger,
) -> None:
    """Install static UI plus authenticated JSON routes; no browser session cookies."""
    static = Path(__file__).with_name("admin_static")

    @app.get("/admin", include_in_schema=False)
    def console() -> FileResponse:
        return FileResponse(
            static / "index.html",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; "
                "style-src 'self'; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
                "Referrer-Policy": "no-referrer",
            },
        )

    @app.get("/admin/{filename}", include_in_schema=False)
    def static_file(filename: Literal["admin.js", "admin.css"]) -> FileResponse:
        return FileResponse(static / filename, headers={"X-Content-Type-Options": "nosniff"})

    router = APIRouter(prefix="/admin/api", dependencies=[Depends(require_admin)])

    @contextmanager
    def observe(action: str) -> Iterator[None]:
        outcome = "success"
        try:
            yield
        except Exception:
            outcome = "error"
            raise
        finally:
            counter.labels(action, outcome).inc()
            logger.info(
                "admin action %s %s",
                action,
                outcome,
                extra={"event": "admin.action", "action": action, "outcome": outcome},
            )

    @router.get("/assets")
    def listing(response: Response, query: AssetQuery = Query()) -> dict[str, object]:
        response.headers["Cache-Control"] = "no-store"
        rows = registry.query_assets(query)
        more = len(rows) > query.limit
        rows = rows[: query.limit]
        quota = None
        if query.space and query.partition_id:
            quota = PartitionQuotaOut.from_quota(
                registry.get_partition_quota(space=query.space, partition_id=query.partition_id)
            ).model_dump()
        return {
            "items": [public_asset(a) for a in rows],
            "next_cursor": query.cursor_for(rows[-1]) if more else None,
            "quota": quota,
        }

    @router.get("/assets/{asset_id}")
    def inspect(asset_id: str, response: Response) -> dict[str, object]:
        response.headers["Cache-Control"] = "no-store"
        asset = registry.get_asset(asset_id)
        events = registry.recent_audit(asset_id=asset_id)
        return {
            "asset": public_asset(asset),
            "audit": [AuditEventOut.from_event(e).model_dump(mode="json") for e in events[-100:]],
        }

    @router.get("/audit")
    def audit(
        response: Response, limit: int = Query(default=100, ge=1, le=500)
    ) -> list[AuditEventOut]:
        response.headers["Cache-Control"] = "no-store"
        return [AuditEventOut.from_event(e) for e in registry.recent_audit(limit=limit)]

    @router.post("/assets/{asset_id}/actions")
    def mutate(asset_id: str, body: Mutation) -> dict[str, object]:
        with observe(body.action), registry.asset_lock(asset_id) as asset:
            if body.expected_updated_at != asset.updated_at:
                raise InvalidStateTransitionError("asset changed; reload before applying")
            if body.action == "expire":
                registry.expire_asset(asset_id=asset_id, caller_service_id="admin")
            elif body.action == "delete":
                registry.delete_asset(asset_id=asset_id, caller_service_id="admin")
            elif body.action == "ttl":
                if body.ttl_seconds is None:
                    raise ValidationError("ttl_seconds is required")
                registry.set_asset_ttl(
                    asset_id=asset_id, ttl_seconds=body.ttl_seconds, caller_service_id="admin"
                )
            elif body.action in {"attach", "detach"}:
                if not body.alias:
                    raise ValidationError("relative alias is required")
                if body.action == "attach":
                    registry.attach_alias(
                        asset_id=asset_id,
                        alias=body.alias,
                        mutable=body.mutable,
                        caller_service_id="admin",
                    )
                else:
                    # Only detach an alias from the inspected asset, never another asset.
                    name = body.alias.strip().strip("/")
                    if f"{asset.space}/{name}" not in asset.aliases:
                        raise ValidationError("alias does not belong to this asset")
                    try:
                        registry.detach_alias(
                            space=asset.space, alias=name, caller_service_id="admin"
                        )
                    except AliasImmutableError:
                        registry.detach_mutable_alias(
                            space=asset.space, alias=name, caller_service_id="admin"
                        )
            elif body.action == "annotations":
                if body.annotations is None:
                    raise ValidationError("annotations are required")
                registry.update_annotations(
                    asset_id=asset_id,
                    patch=body.annotations,
                    caller_service_id="admin",
                    overwrite=True,
                )
            elif body.action == "eviction":
                if body.eviction_policy is None:
                    raise ValidationError("eviction_policy is required")
                registry.set_eviction_policy(
                    asset_id=asset_id,
                    eviction_policy=body.eviction_policy,
                    caller_service_id="admin",
                )
            return public_asset(registry.get_asset(asset_id))

    @router.put("/quotas/partition")
    def quota(body: PartitionQuotaRequest) -> PartitionQuotaOut:
        with observe("quota"):
            return PartitionQuotaOut.from_quota(
                registry.set_partition_quota(**body.model_dump(), caller_service_id="admin")
            )

    def bulk_query(prefix: str) -> AssetQuery:
        query = AssetQuery(prefix=prefix, state=AssetState.AVAILABLE, limit=500)
        if query.prefix is None or len(query.prefix.split("/")) < 2:
            raise ValidationError("bulk prefix must include a bucket and partition")
        return query

    @router.get("/aliases/expire")
    def preview(prefix: str, response: Response) -> dict[str, object]:
        response.headers["Cache-Control"] = "no-store"
        query = bulk_query(prefix)
        rows = registry.query_assets(query)
        if len(rows) > query.limit:
            raise ValidationError("more than 500 assets match; narrow the prefix")
        return {
            "prefix": query.prefix,
            "candidates": [
                {"asset_id": a.asset_id, "expected_updated_at": a.updated_at.isoformat()}
                for a in rows
            ],
        }

    @router.post("/aliases/expire")
    def bulk(prefix: str, body: BulkApply) -> dict[str, int]:
        query = bulk_query(prefix)
        applied = skipped = 0
        if len({c.asset_id for c in body.candidates}) != len(body.candidates):
            raise ValidationError("duplicate candidate")
        with observe("bulk_expire"):
            for candidate in body.candidates:
                with registry.asset_lock(candidate.asset_id) as asset:
                    if (
                        asset.updated_at != candidate.expected_updated_at
                        or asset.state is not AssetState.AVAILABLE
                        or not any(prefix_matches(a, query.prefix or "") for a in asset.aliases)
                    ):
                        skipped += 1
                        continue
                    registry.expire_asset(asset_id=asset.asset_id, caller_service_id="admin")
                    applied += 1
        return {"applied": applied, "skipped": skipped}

    app.include_router(router)
