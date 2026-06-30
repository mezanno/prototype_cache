"""Structured JSON logging and a request observability middleware.

Implements the logging/correlation-id contract from spec 04_OPERATIONS:
one JSON line per event, a `correlation_id` per inbound request propagated via the
`X-Correlation-Id` header, and per-request metrics recorded in one pass.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from asset_store_core.api.metrics import SERVICE_NAME, Metrics

CORRELATION_ID_HEADER = b"x-correlation-id"
LOGGER_NAME = "asset_store"

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")

_OPTIONAL_FIELDS = ("caller_service_id", "space", "alias", "endpoint", "status", "duration_ms")


def current_correlation_id() -> str:
    """Return the correlation id bound to the current request, or ``"-"``."""

    return _correlation_id.get()


class JsonLogFormatter(logging.Formatter):
    """Render log records as single-line JSON with the spec's field set."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "service": getattr(record, "service", SERVICE_NAME),
            "level": record.levelname.lower(),
            "correlation_id": getattr(record, "correlation_id", _correlation_id.get()),
            "event": getattr(record, "event", record.name),
            "message": record.getMessage(),
        }
        for field in _OPTIONAL_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, separators=(",", ":"))


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Return the ``asset_store`` logger configured for JSON output (idempotent)."""

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    if not any(isinstance(handler.formatter, JsonLogFormatter) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonLogFormatter())
        logger.addHandler(handler)
        logger.propagate = False
    return logger


class ObservabilityMiddleware:
    """Bind a correlation id, time each request, and emit metrics + a log line."""

    def __init__(self, app: ASGIApp, *, metrics: Metrics, logger: logging.Logger) -> None:
        self._app = app
        self._metrics = metrics
        self._logger = logger

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        correlation_id = self._inbound_correlation_id(scope) or uuid.uuid4().hex
        token = _correlation_id.set(correlation_id)
        start = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.append((CORRELATION_ID_HEADER, correlation_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self._app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - start
            endpoint = self._endpoint_label(scope)
            result_class = f"{status // 100}xx"
            self._metrics.requests_total.labels(SERVICE_NAME, endpoint, result_class).inc()
            self._metrics.request_duration_seconds.labels(SERVICE_NAME, endpoint).observe(duration)
            self._logger.info(
                "request handled",
                extra={
                    "event": "http.request",
                    "correlation_id": correlation_id,
                    "endpoint": endpoint,
                    "status": status,
                    "duration_ms": round(duration * 1000, 3),
                },
            )
            _correlation_id.reset(token)

    @staticmethod
    def _inbound_correlation_id(scope: Scope) -> str | None:
        for name, value in scope.get("headers", []):
            if name == CORRELATION_ID_HEADER and value:
                decoded: str = value.decode()
                return decoded
        return None

    @staticmethod
    def _endpoint_label(scope: Scope) -> str:
        handler = scope.get("endpoint")
        if handler is not None:
            return getattr(handler, "__name__", "unmatched")
        return "unmatched"
