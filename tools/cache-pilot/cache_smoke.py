"""Explicit HTTP preload/read smoke check for M-001 (B-024, SCN-010).

Configure CACHE_PILOT_BASE_URL, CACHE_PILOT_ORIGIN_URL and
CACHE_PILOT_SERVICE_SECRET. No source URLs or credentials are printed.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from fetcher_service.errors import PilotDeniedError
from fetcher_service.pilot_policy import IMAGE_MIMES, GallicaPolicy


class SmokeFailure(RuntimeError):
    """Sanitized actionable failure, safe for operator output."""


@dataclass(frozen=True)
class SmokeResult:
    size_bytes: int
    checksum: str
    first_cache_hit: bool


def run_smoke(http: httpx.Client, origin_url: str, *, max_bytes: int) -> SmokeResult:
    """One explicit preload, two bounded byte reads and a second preload hit."""
    target = GallicaPolicy().require(origin_url)
    if max_bytes <= 0:
        raise SmokeFailure("byte limit must be positive")

    def preload() -> dict[str, object]:
        response = http.post("/v1/cache/preload", json={"url": target.origin_url})
        if response.status_code != 200:
            raise SmokeFailure(f"preload returned HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError as exc:
            raise SmokeFailure("preload returned invalid JSON") from exc
        if not isinstance(body, dict) or not isinstance(body.get("cache_hit"), bool):
            raise SmokeFailure("preload returned invalid hit metadata")
        if not isinstance(body.get("asset_id"), str):
            raise SmokeFailure("preload returned invalid asset metadata")
        return body

    first = preload()
    checksums: list[str] = []
    sizes: list[int] = []
    for _ in range(2):
        digest = hashlib.sha256()
        size = 0
        with http.stream("GET", "/" + target.host + target.path) as response:
            if response.status_code != 200:
                raise SmokeFailure(f"cached read returned HTTP {response.status_code}")
            mime = response.headers.get("Content-Type", "").split(";", 1)[0]
            if mime not in IMAGE_MIMES:
                raise SmokeFailure("cached read returned an unsupported content type")
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise SmokeFailure("cached read exceeded the byte limit")
                digest.update(chunk)
            checksum = "sha256:" + digest.hexdigest()
            if response.headers.get("ETag") != '"' + checksum + '"':
                raise SmokeFailure("cached read ETag does not match downloaded bytes")
        checksums.append(checksum)
        sizes.append(size)
    if checksums[0] != checksums[1] or sizes[0] != sizes[1]:
        raise SmokeFailure("repeated cached reads differ")
    hit = preload()
    if hit["cache_hit"] is not True or hit["asset_id"] != first["asset_id"]:
        raise SmokeFailure("repeated preload did not reuse the cached asset")
    return SmokeResult(sizes[0], checksums[0], bool(first["cache_hit"]))


def main() -> int:
    try:
        base = os.environ["CACHE_PILOT_BASE_URL"]
        origin = os.environ["CACHE_PILOT_ORIGIN_URL"]
        secret = os.environ["CACHE_PILOT_SERVICE_SECRET"]
        identity = os.environ.get("CACHE_PILOT_SERVICE_ID", "task-api")
        if identity not in {"task-api", "admin"} or not secret:
            raise SmokeFailure("configure a task-api/admin service credential")
        parts = urlsplit(base)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.path not in {"", "/"}
        ):
            raise SmokeFailure("base URL must be an HTTP(S) origin without credentials or a path")
        if parts.scheme == "http" and parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise SmokeFailure("use HTTPS except for a local host or tunnel endpoint")
        max_bytes = int(os.environ.get("CACHE_PILOT_MAX_BYTES", str(50 * 1024 * 1024)))
        with httpx.Client(
            base_url=base,
            timeout=60,
            trust_env=False,
            follow_redirects=False,
            headers={"Authorization": f"Service {identity}:{secret}"},
        ) as http:
            result = run_smoke(http, origin, max_bytes=max_bytes)
    except KeyError:
        print("FAIL: required CACHE_PILOT_* environment configuration is missing")
        return 1
    except SmokeFailure as exc:
        print(f"FAIL: {exc}")
        return 1
    except (httpx.HTTPError, ValueError, PilotDeniedError):
        print("FAIL: invalid configuration or HTTP transport failure; check connectivity and TLS")
        return 1
    print(
        f"PASS: {result.size_bytes} bytes; {result.checksum}; "
        f"initial_cache_hit={str(result.first_cache_hit).lower()}; repeat_preload_hit=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
