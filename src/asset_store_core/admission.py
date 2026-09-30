"""Single-process, no-wait work admission for M-001/P2 (NFR-004, SEC-06)."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import Lock
from typing import ParamSpec, TypeVar

from anyio import CancelScope
from prometheus_client import CollectorRegistry, Counter, Gauge
from starlette.concurrency import run_in_threadpool

from asset_store_core.errors import ValidationError, WorkCapacityError


def positive_limit_from_env(name: str, default: int) -> int:
    """Read a positive integer without exposing invalid configuration values."""
    try:
        limit = int(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise ValidationError(f"{name} must be a positive integer") from exc
    if limit <= 0:
        raise ValidationError(f"{name} must be a positive integer")
    return limit


class WorkAdmission:
    """Admit at most ``limit`` jobs; overload never queues a waiting job.

    A lease covers async body reads and synchronous work without holding the
    mutex across either. Release is unconditional, including cancellation.
    Each app owns its gate; multiple application processes multiply the bound.
    """

    def __init__(
        self, *, limit: int, name: str, metrics: CollectorRegistry, logger: logging.Logger
    ) -> None:
        if limit <= 0:
            raise ValidationError("work admission limit must be positive")
        self._limit = limit
        self._active = 0
        self._lock = Lock()
        self._name = name
        self._logger = logger
        self._attempts = Counter(
            f"{name}_admission_total",
            "Work admission attempts by outcome.",
            ["outcome"],
            registry=metrics,
        )
        self._gauge = Gauge(
            f"{name}_inflight",
            "Currently admitted jobs in this application process.",
            registry=metrics,
        )
        self._gauge.set_function(self.active)

    def active(self) -> int:
        """Return a consistent occupancy snapshot for metrics and diagnostics."""
        with self._lock:
            return self._active

    @contextmanager
    def lease(self) -> Iterator[None]:
        """Acquire without waiting and release on every exit (SEC-06)."""
        with self._lock:
            admitted = self._active < self._limit
            if admitted:
                self._active += 1
        if not admitted:
            self._attempts.labels("denied").inc()
            self._logger.warning(
                "Work admission saturated", extra={"event": f"{self._name}.overload"}
            )
            raise WorkCapacityError("work capacity exhausted; retry with backoff")
        try:
            self._attempts.labels("granted").inc()
            yield
        finally:
            with self._lock:
                self._active -= 1


_P = ParamSpec("_P")
_T = TypeVar("_T")


async def run_work_until_complete(
    function: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs
) -> _T:
    """Keep the caller's lease until blocking work exits, even on cancellation.

    Cancelling an async request cannot stop an already running Python thread.
    Shield the worker and drain it before propagating request cancellation so
    a still-running upload/fetch never silently frees an admission slot.
    """
    worker = asyncio.create_task(run_in_threadpool(function, *args, **kwargs))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        with CancelScope(shield=True):
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
        if not worker.cancelled():
            worker.exception()  # Retrieve a worker failure; preserve cancellation.
        raise
