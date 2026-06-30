"""Pydantic request/response schemas for the asset-store HTTP API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from asset_store_core.capabilities import Operation
from asset_store_core.models import AliasBinding, Asset, AuditEvent


class AliasSpecIn(BaseModel):
    """One alias to reserve, with its mutability flag (FR-008, default immutable)."""

    name: str
    mutable: bool = False


class ReserveRequest(BaseModel):
    """Body for ``POST /assets`` (FR-001/FR-004)."""

    space: str
    partition_id: str
    aliases: list[AliasSpecIn] = Field(min_length=1)
    owner_service_id: str
    mime: str | None = None
    annotations: dict[str, str] | None = None


class CommitRequest(BaseModel):
    """Body for ``POST /assets/{asset_id}/commit`` (FR-022)."""

    size_bytes: int = Field(ge=0)
    checksum: str
    caller_service_id: str
    mime: str | None = None
    expected_checksum: str | None = None


class AssetOut(BaseModel):
    """Asset projection returned by reserve/commit/resolve."""

    asset_id: str
    space: str
    partition_id: str
    storage_key: str
    state: str
    aliases: list[str]
    mime: str | None
    size_bytes: int | None
    checksum: str | None
    annotations: dict[str, str]
    created_at: datetime
    updated_at: datetime
    owner_service_id: str

    @classmethod
    def from_asset(cls, asset: Asset) -> AssetOut:
        return cls(
            asset_id=asset.asset_id,
            space=asset.space,
            partition_id=asset.partition_id,
            storage_key=asset.storage_key,
            state=asset.state.value,
            aliases=sorted(asset.aliases),
            mime=asset.mime,
            size_bytes=asset.size_bytes,
            checksum=asset.checksum,
            annotations=dict(asset.annotations),
            created_at=asset.created_at,
            updated_at=asset.updated_at,
            owner_service_id=asset.owner_service_id,
        )


class CapabilityMintRequest(BaseModel):
    """Body for ``POST /capabilities`` (FR-010, TTL bounded 60 s..24 h)."""

    operation: Operation
    scope_prefix: str
    caller_service_id: str
    ttl_seconds: int = Field(ge=60, le=86_400)
    single_use: bool = False


class CapabilityOut(BaseModel):
    """Minted capability descriptor (unsigned in this prototype slice)."""

    capability_id: str
    operation: str
    scope_prefix: str
    caller_service_id: str
    expires_at: datetime
    single_use: bool


class AuditEventOut(BaseModel):
    """One recorded audit event (FR-008/FR-016)."""

    action: str
    target: str
    caller_service_id: str
    outcome: str
    before: dict[str, str]
    after: dict[str, str]
    ts: datetime

    @classmethod
    def from_event(cls, event: AuditEvent) -> AuditEventOut:
        return cls(
            action=event.action,
            target=event.target,
            caller_service_id=event.caller_service_id,
            outcome=event.outcome,
            before=dict(event.before),
            after=dict(event.after),
            ts=event.ts,
        )


class LifecycleRequest(BaseModel):
    """Body for the asset state transitions ``expire``/``delete`` (FR-006/FR-007)."""

    caller_service_id: str


class AnnotationsUpdateRequest(BaseModel):
    """Body for ``PATCH /assets/{asset_id}/annotations`` (FR-005)."""

    patch: dict[str, str]
    caller_service_id: str
    overwrite: bool = False


class AliasDetachRequest(BaseModel):
    """Body for the alias detach endpoints (FR-003)."""

    space: str
    alias: str
    caller_service_id: str


class AliasRebindRequest(BaseModel):
    """Body for ``POST /aliases/rebind`` (FR-008)."""

    space: str
    alias: str
    new_asset_id: str
    caller_service_id: str


class AliasBindingOut(BaseModel):
    """Alias binding projection returned by the detach/rebind endpoints."""

    space: str
    alias: str
    asset_id: str | None
    mutable: bool
    previous_asset_id: str | None
    updated_at: datetime

    @classmethod
    def from_binding(cls, binding: AliasBinding) -> AliasBindingOut:
        return cls(
            space=binding.space,
            alias=binding.alias,
            asset_id=binding.asset_id,
            mutable=binding.mutable,
            previous_asset_id=binding.previous_asset_id,
            updated_at=binding.updated_at,
        )
