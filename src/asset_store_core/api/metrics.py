"""Prometheus metrics for the asset-store HTTP API (spec 04_OPERATIONS).

Each app instance owns its own :class:`CollectorRegistry` so that multiple apps
(notably in tests) can coexist without duplicate-registration errors on the global
default registry.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Histogram

SERVICE_NAME = "asset-store"


@dataclass(frozen=True, slots=True)
class Metrics:
    """Bundle of collectors bound to one registry."""

    registry: CollectorRegistry
    requests_total: Counter
    request_duration_seconds: Histogram
    capability_issued_total: Counter


def build_metrics() -> Metrics:
    """Create a fresh metrics bundle on its own registry."""

    registry = CollectorRegistry()
    requests_total = Counter(
        "asset_store_requests_total",
        "HTTP request count by endpoint and result class.",
        ["service", "endpoint", "result_class"],
        registry=registry,
    )
    request_duration_seconds = Histogram(
        "asset_store_request_duration_seconds",
        "Per-endpoint request latency in seconds.",
        ["service", "endpoint"],
        registry=registry,
    )
    capability_issued_total = Counter(
        "asset_store_capability_issued_total",
        "Capability mint attempts by operation and outcome.",
        ["service", "op", "outcome"],
        registry=registry,
    )
    return Metrics(
        registry=registry,
        requests_total=requests_total,
        request_duration_seconds=request_duration_seconds,
        capability_issued_total=capability_issued_total,
    )
