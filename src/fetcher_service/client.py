"""Thin HTTP client for the asset-store control + proxy data plane (ADR-017).

The fetcher talks to asset-store exactly like any other service caller: it
authenticates as the ``fetcher`` service identity to mint capabilities (FR-014,
ADR-016) and pushes bytes through the guarded proxy (``PUT /objects/{alias}``).
The performance path (presigned PUT direct-to-S3) is future work — see ADR-017 /
R-013. Tests inject an ``httpx.Client`` bound to an in-memory asset-store app.
"""

from __future__ import annotations

from typing import Any

import httpx

DEFAULT_SERVICE_ID = "fetcher"
DEFAULT_CAPABILITY_TTL_SECONDS = 3600


class AssetStoreError(RuntimeError):
    """An asset-store control/data-plane call failed unexpectedly."""


class AssetStoreClient:
    """Minimal asset-store client: resolve, mint write capability, proxy PUT."""

    def __init__(
        self,
        http: httpx.Client,
        *,
        service_id: str = DEFAULT_SERVICE_ID,
        service_secret: str,
    ) -> None:
        self._http = http
        self._service_id = service_id
        self._service_secret = service_secret

    def resolve(self, *, space: str, alias: str) -> dict[str, Any] | None:
        """Resolve a qualified alias; return the asset JSON, or ``None`` if absent."""

        response = self._http.get("/resolve", params={"space": space, "alias": alias})
        if response.status_code == 200:
            result: dict[str, Any] = response.json()
            return result
        if response.status_code == 404:
            return None
        raise AssetStoreError(f"resolve failed ({response.status_code}): {response.text}")

    def mint_write_capability(
        self,
        *,
        scope_prefix: str,
        ttl_seconds: int = DEFAULT_CAPABILITY_TTL_SECONDS,
    ) -> str:
        """Mint a write capability scoped to ``scope_prefix`` (``bucket/segment``)."""

        response = self._http.post(
            "/capabilities",
            headers={"Authorization": f"Service {self._service_id}:{self._service_secret}"},
            json={
                "operation": "write",
                "scope_prefix": scope_prefix,
                "ttl_seconds": ttl_seconds,
                "single_use": False,
            },
        )
        if response.status_code != 201:
            raise AssetStoreError(
                f"capability mint failed ({response.status_code}): {response.text}"
            )
        capability_id: str = response.json()["capability_id"]
        return capability_id

    def put_object(
        self,
        *,
        capability_id: str,
        qualified_alias: str,
        data: bytes,
        mime: str | None,
    ) -> dict[str, Any]:
        """Upload bytes for ``qualified_alias`` (reserve→PUT→commit server-side)."""

        headers = {"Authorization": f"Capability {capability_id}"}
        if mime:
            headers["Content-Type"] = mime
        response = self._http.put(f"/objects/{qualified_alias}", content=data, headers=headers)
        if response.status_code != 201:
            raise AssetStoreError(f"object write failed ({response.status_code}): {response.text}")
        asset: dict[str, Any] = response.json()
        return asset
