"""ADR-026 bounded capability and consumed-token state contracts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from asset_store_core.api import create_app
from asset_store_core.capabilities import Capability, CapabilityStore, Operation, SingleUseLedger
from asset_store_core.errors import (
    CapabilityAlreadyConsumedError,
    CapabilityCapacityError,
    ValidationError,
)
from asset_store_core.registry import InMemoryAssetRegistry
from asset_store_core.service_identity import dev_secret


def _cap(identifier: str, expires_at: datetime, *, single_use: bool = False) -> Capability:
    return Capability(
        capability_id=identifier,
        operation=Operation.WRITE,
        scope_prefix="users/42/uploads",
        expires_at=expires_at,
        caller_service_id="upload-api",
        single_use=single_use,
    )


def _mint(client: TestClient, *, operation: str = "write") -> httpx.Response:
    return cast(
        httpx.Response,
        client.post(
            "/capabilities",
            json={"operation": operation, "scope_prefix": "users/42/uploads", "ttl_seconds": 60},
            headers={"Authorization": f"Service upload-api:{dev_secret('upload-api')}"},
        ),
    )


def test_expired_token_frees_capacity_without_reviving() -> None:
    now = [datetime(2026, 9, 29, tzinfo=UTC)]
    store = CapabilityStore(1, clock=lambda: now[0])
    first = _cap("first", now[0] + timedelta(seconds=60))
    store.issue(first, on_grant=lambda: None)
    with pytest.raises(CapabilityCapacityError):
        store.issue(_cap("second", now[0] + timedelta(seconds=60)), on_grant=lambda: None)
    assert store.get("first") is first

    now[0] += timedelta(seconds=60)
    assert len(store) == 0
    assert store.get("first") is None
    second = _cap("second", now[0] + timedelta(seconds=60))
    store.issue(second, on_grant=lambda: None)
    assert store.get("first") is None
    assert store.get("second") is second


def test_concurrent_contenders_admit_exactly_one_grant() -> None:
    now = datetime(2026, 9, 29, tzinfo=UTC)
    store = CapabilityStore(1, clock=lambda: now)
    start = Barrier(8)
    audited: list[str] = []

    def contend(index: int) -> bool:
        cap = _cap(str(index), now + timedelta(minutes=1))
        start.wait(timeout=5)
        try:
            store.issue(cap, on_grant=lambda: audited.append(cap.capability_id))
        except CapabilityCapacityError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as executor:
        admitted = list(executor.map(contend, range(8)))

    assert admitted.count(True) == 1
    assert len(audited) == 1
    assert len(store) == 1
    assert store.get(audited[0]) is not None


def test_failed_audit_does_not_publish_or_consume_capacity() -> None:
    now = datetime(2026, 9, 29, tzinfo=UTC)
    store = CapabilityStore(1, clock=lambda: now)
    cap = _cap("failed", now + timedelta(minutes=1))

    def fail_audit() -> None:
        raise RuntimeError("audit unavailable")

    with pytest.raises(RuntimeError, match="audit unavailable"):
        store.issue(cap, on_grant=fail_audit)
    assert len(store) == 0
    assert store.get("failed") is None
    store.issue(_cap("next", now + timedelta(minutes=1)), on_grant=lambda: None)
    assert len(store) == 1


def test_consumed_ledger_retires_expired_ids_and_preserves_replay_denial() -> None:
    now = [datetime(2026, 9, 29, tzinfo=UTC)]
    ledger = SingleUseLedger(clock=lambda: now[0])
    first = _cap("first", now[0] + timedelta(seconds=60), single_use=True)
    ledger.record_successful_use(first)
    with pytest.raises(CapabilityAlreadyConsumedError):
        ledger.assert_unused(first)
    with pytest.raises(CapabilityAlreadyConsumedError):
        ledger.record_successful_use(first)

    now[0] += timedelta(seconds=60)
    ledger.prune_expired()
    assert ledger._consumed == {}
    later = _cap("later", now[0] + timedelta(seconds=60), single_use=True)
    ledger.assert_unused(later)
    ledger.record_successful_use(later)
    with pytest.raises(CapabilityAlreadyConsumedError):
        ledger.assert_unused(later)


@pytest.mark.parametrize("value", ["0", "-1", "not-an-integer", "1.5"])
def test_invalid_capacity_environment_fails_at_factory(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ASSET_STORE_MAX_CAPABILITIES", value)
    with pytest.raises(ValidationError, match="ASSET_STORE_MAX_CAPABILITIES"):
        create_app()


def test_http_capacity_rejection_keeps_existing_token_and_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSET_STORE_MAX_CAPABILITIES", "1")
    app = create_app()
    client = TestClient(app)
    first = _mint(client)
    assert first.status_code == 201
    token = first.json()["capability_id"]

    denied = _mint(client)
    assert denied.status_code == 503
    assert denied.headers["Retry-After"] == "1"
    assert denied.json()["title"] == "CapabilityCapacityError"
    assert "cap-" not in denied.text
    grants = [
        event for event in app.state.registry.audit_events if event.action == "capability.issue"
    ]
    assert len(grants) == 1
    assert grants[0].outcome == "granted"

    upload = client.put(
        "/objects/users/42/uploads/kept.txt",
        content=b"kept",
        headers={"Authorization": f"Capability {token}"},
    )
    assert upload.status_code == 201
    metrics = client.get("/metrics").text
    assert "asset_store_active_capabilities 1.0" in metrics
    for outcome in ("capacity_denied", "granted"):
        assert any(
            line.startswith("asset_store_capability_issued_total{")
            and f'outcome="{outcome}"' in line
            and line.endswith(" 1.0")
            for line in metrics.splitlines()
        )


def test_http_audit_failure_does_not_publish_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSET_STORE_MAX_CAPABILITIES", "1")
    registry = InMemoryAssetRegistry()
    original = InMemoryAssetRegistry.record_capability_issue

    def fail_audit(_self: InMemoryAssetRegistry, **_kwargs: object) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(InMemoryAssetRegistry, "record_capability_issue", fail_audit)
    app = create_app(registry=registry)
    client = TestClient(app, raise_server_exceptions=False)
    assert _mint(client).status_code == 500
    assert len(app.state.capabilities) == 0
    metrics = client.get("/metrics").text
    assert not any(
        line.startswith("asset_store_capability_issued_total{") for line in metrics.splitlines()
    )
    assert "asset_store_active_capabilities 0.0" in metrics

    monkeypatch.setattr(InMemoryAssetRegistry, "record_capability_issue", original)
    assert _mint(client).status_code == 201
    assert len(app.state.capabilities) == 1
