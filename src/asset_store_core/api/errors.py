"""RFC 7807 ``application/problem+json`` error model for the HTTP API.

Maps the domain error taxonomy in :mod:`asset_store_core.errors` to HTTP status
codes and a uniform problem document, so every error response has the same shape.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from asset_store_core.errors import (
    AliasConflictError,
    AliasImmutableError,
    AliasNotFoundError,
    AssetNotFoundError,
    AssetStoreError,
    CapabilityAlreadyConsumedError,
    CapabilityDeniedError,
    ChecksumMismatchError,
    InvalidStateTransitionError,
    ObjectNotFoundError,
    ValidationError,
)

PROBLEM_CONTENT_TYPE = "application/problem+json"

_STATUS_BY_ERROR: dict[type[AssetStoreError], int] = {
    ValidationError: 400,
    CapabilityDeniedError: 403,
    CapabilityAlreadyConsumedError: 403,
    AliasNotFoundError: 404,
    AssetNotFoundError: 404,
    ObjectNotFoundError: 404,
    AliasConflictError: 409,
    AliasImmutableError: 409,
    ChecksumMismatchError: 409,
    InvalidStateTransitionError: 409,
}


def _slug(name: str) -> str:
    return f"urn:asset-store:error:{name}"


def _problem(*, status: int, title: str, detail: str, **extra: Any) -> JSONResponse:
    body: dict[str, Any] = {
        "type": _slug(title),
        "title": title,
        "status": status,
        "detail": detail,
    }
    body.update(extra)
    return JSONResponse(status_code=status, media_type=PROBLEM_CONTENT_TYPE, content=body)


def register_exception_handlers(app: FastAPI) -> None:
    """Install problem+json handlers for domain and request-validation errors."""

    async def handle_domain(request: Request, exc: Exception) -> Response:
        status = 500
        if isinstance(exc, AssetStoreError):
            status = _STATUS_BY_ERROR.get(type(exc), 500)
        return _problem(status=status, title=type(exc).__name__, detail=str(exc))

    async def handle_validation(request: Request, exc: Exception) -> Response:
        errors = exc.errors() if isinstance(exc, RequestValidationError) else []
        return _problem(
            status=422,
            title="RequestValidationError",
            detail="request body or query parameters failed validation",
            errors=jsonable(errors),
        )

    app.add_exception_handler(AssetStoreError, handle_domain)
    app.add_exception_handler(RequestValidationError, handle_validation)


def jsonable(errors: Sequence[Any]) -> list[dict[str, Any]]:
    """Strip non-serializable context (e.g. exceptions) from validation errors."""

    cleaned: list[dict[str, Any]] = []
    for err in errors:
        item = {k: v for k, v in err.items() if k != "ctx"}
        cleaned.append(item)
    return cleaned
