"""Thin HTTP client for the asset-store control + proxy data plane (ADR-017).

The fetcher talks to asset-store exactly like any other service caller: it
authenticates as the ``fetcher`` service identity to mint capabilities (FR-014,
ADR-016) and pushes bytes through the guarded proxy (``PUT /objects/{alias}``).
The performance path (presigned PUT direct-to-S3) is future work — see ADR-017 /
R-013. Tests inject an ``httpx.Client`` bound to an in-memory asset-store app.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

DEFAULT_SERVICE_ID = "fetcher"
DEFAULT_CAPABILITY_TTL_SECONDS = 3600


class AssetStoreError(RuntimeError):
    """An asset-store control/data-plane call failed unexpectedly."""

    def __init__(
        self, message: str, *, status: int | None = None, retry_after: str | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


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

        response = self._http.get(
            "/resolve",
            params={"space": space, "alias": alias},
            headers={"Authorization": f"Service {self._service_id}:{self._service_secret}"},
        )
        if response.status_code == 200:
            result: dict[str, Any] = response.json()
            return result
        if response.status_code == 404:
            return None
        raise AssetStoreError(
            "resolve failed",
            status=response.status_code,
            retry_after=response.headers.get("Retry-After"),
        )

    def mint_write_capability(
        self,
        *,
        scope_prefix: str,
        ttl_seconds: int = DEFAULT_CAPABILITY_TTL_SECONDS,
    ) -> str:
        """Mint a write capability scoped to ``scope_prefix`` (``bucket/segment``)."""

        return self._mint_capability("write", scope_prefix, ttl_seconds)

    def mint_read_capability(self, *, scope_prefix: str, ttl_seconds: int = 300) -> str:
        """Mint reusable internal read permission for the pilot proxy (B-024)."""
        return self._mint_capability("read", scope_prefix, ttl_seconds)

    def _mint_capability(self, operation: str, scope_prefix: str, ttl_seconds: int) -> str:
        response = self._http.post(
            "/capabilities",
            headers={"Authorization": f"Service {self._service_id}:{self._service_secret}"},
            json={
                "operation": operation,
                "scope_prefix": scope_prefix,
                "ttl_seconds": ttl_seconds,
                "single_use": False,
            },
        )
        if response.status_code != 201:
            raise AssetStoreError(
                "capability mint failed",
                status=response.status_code,
                retry_after=response.headers.get("Retry-After"),
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
        response = self._http.put(
            f"/objects/{quote(qualified_alias, safe='/')}", content=data, headers=headers
        )
        if response.status_code != 201:
            raise AssetStoreError(
                "object write failed",
                status=response.status_code,
                retry_after=response.headers.get("Retry-After"),
            )
        asset: dict[str, Any] = response.json()
        return asset

    def read_object(self, *, capability_id: str, qualified_alias: str, max_bytes: int) -> bytes:
        """Capped proxy GET; never expose capability URLs or raw keys (B-024)."""
        with self._http.stream(
            "GET",
            f"/objects/{quote(qualified_alias, safe='/')}",
            headers={"Authorization": f"Capability {capability_id}"},
        ) as response:
            if response.status_code != 200:
                raise AssetStoreError(
                    "object read failed",
                    status=response.status_code,
                    retry_after=response.headers.get("Retry-After"),
                )
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise AssetStoreError("cached object exceeds byte limit", status=413)
                chunks.append(chunk)
            return b"".join(chunks)
