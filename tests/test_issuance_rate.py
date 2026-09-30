"""ADR-030 / FR-014/050: bounded, atomic capability rate admission."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from asset_store_core.api import create_app
from asset_store_core.errors import CapabilityRateError, ServiceAuthError, ValidationError
from asset_store_core.issuance_rate import IssuanceRateLimiter

BODY = {"operation": "write", "scope_prefix": "cache/test", "ttl_seconds": 60}


def auth(identity: str) -> dict[str, str]:
    return {"Authorization": f"Service {identity}:dev-secret:{identity}"}


def test_refill_is_monotonic_capped_and_identity_scoped() -> None:
    now = [0.0]
    limiter = IssuanceRateLimiter(["a", "b"], per_minute=30, burst=2, clock=lambda: now[0])
    limiter.admit("a")
    limiter.admit("a")
    with pytest.raises(CapabilityRateError) as denied:
        limiter.admit("a")
    assert denied.value.retry_after == 2
    limiter.admit("b")
    now[0] = 1
    with pytest.raises(CapabilityRateError) as partial:
        limiter.admit("a")
    assert partial.value.retry_after == 1
    now[0] = 2
    limiter.admit("a")
    now[0] = 1000
    limiter.admit("a")
    limiter.admit("a")
    with pytest.raises(CapabilityRateError):
        limiter.admit("a")  # Long idle time cannot accumulate beyond burst.
    now[0] = 999
    with pytest.raises(CapabilityRateError):
        limiter.admit("a")
    now[0] = 1000
    with pytest.raises(CapabilityRateError):
        limiter.admit("a")  # A backward clock cannot create extra credit.


def test_concurrent_contenders_cannot_exceed_burst() -> None:
    limiter = IssuanceRateLimiter(["a"], per_minute=60, burst=3, clock=lambda: 0)
    start = Barrier(12)

    def contend(_: int) -> bool:
        start.wait(timeout=5)
        try:
            limiter.admit("a")
            return True
        except CapabilityRateError:
            return False

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(contend, range(12)))
    assert results.count(True) == 3


def test_unknown_identities_never_create_state() -> None:
    limiter = IssuanceRateLimiter(["a"], per_minute=60, burst=1, clock=lambda: 0)
    for index in range(100):
        with pytest.raises(ServiceAuthError):
            limiter.admit(str(index))
    assert set(limiter._credit) == {"a"}
    limiter.admit("a")


@pytest.mark.parametrize(
    "name", ["ASSET_STORE_CAPABILITY_RATE_PER_MINUTE", "ASSET_STORE_CAPABILITY_RATE_BURST"]
)
@pytest.mark.parametrize("value", ["0", "-1", "1.5", "invalid"])
def test_invalid_rate_configuration_fails_factory(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError, match=name):
        create_app()


def test_http_auth_rate_audit_and_existing_grant_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSET_STORE_CAPABILITY_RATE_BURST", "1")
    monkeypatch.setenv("ASSET_STORE_CAPABILITY_RATE_PER_MINUTE", "1")
    app = create_app()
    now = [0.0]
    app.state.issuance_rate._clock = lambda: now[0]
    # Set a deterministic epoch before any issuance attempt.
    limiter = app.state.issuance_rate
    for credit in limiter._credit.values():
        credit.updated_at = 0
    with TestClient(app) as client:
        assert client.post("/capabilities", json=BODY).status_code == 401
        assert (
            client.post(
                "/capabilities", headers={"Authorization": "Service bulk-loader:wrong"}, json=BODY
            ).status_code
            == 401
        )
        first = client.post("/capabilities", headers=auth("bulk-loader"), json=BODY)
        assert first.status_code == 201
        token = first.json()["capability_id"]
        before = app.state.registry.audit_events
        for _ in range(10):
            response = client.post("/capabilities", headers=auth("bulk-loader"), json=BODY)
            assert response.status_code == 429
            assert response.headers["Retry-After"] == "60"
            assert response.json()["title"] == "CapabilityRateError"
            assert token not in response.text
        assert app.state.registry.audit_events == before
        assert len(app.state.capabilities) == 1
        assert (
            client.put(
                "/objects/cache/test/a",
                headers={"Authorization": "Capability " + token},
                content=b"ok",
            ).status_code
            == 201
        )
        assert client.post("/capabilities", headers=auth("admin"), json=BODY).status_code == 201
        now[0] = 60
        assert (
            client.post("/capabilities", headers=auth("bulk-loader"), json=BODY).status_code == 201
        )
        metrics = client.get("/metrics").text
        assert 'op="write",outcome="rate_denied",service="asset-store"} 10.0' in metrics


@pytest.mark.parametrize("failure", ["policy", "capacity", "audit"])
def test_failed_admitted_attempt_is_not_refunded(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from asset_store_core.registry import InMemoryAssetRegistry

    monkeypatch.setenv("ASSET_STORE_CAPABILITY_RATE_BURST", "1")
    monkeypatch.setenv("ASSET_STORE_CAPABILITY_RATE_PER_MINUTE", "1")
    if failure == "capacity":
        monkeypatch.setenv("ASSET_STORE_MAX_CAPABILITIES", "1")
    app = create_app()
    body = dict(BODY)
    expected = {"policy": 403, "capacity": 503, "audit": 500}[failure]
    with TestClient(app, raise_server_exceptions=False) as client:
        if failure == "policy":
            body["scope_prefix"] = "users/42/a"
        elif failure == "capacity":
            # A different service fills the token store without consuming this service's credit.
            assert client.post("/capabilities", headers=auth("admin"), json=BODY).status_code == 201
        else:

            def fail_audit(*args: object, **kwargs: object) -> None:
                raise RuntimeError("controlled audit failure")

            monkeypatch.setattr(InMemoryAssetRegistry, "record_capability_issue", fail_audit)
        response = client.post("/capabilities", headers=auth("bulk-loader"), json=body)
        assert response.status_code == expected
        assert (
            client.post("/capabilities", headers=auth("bulk-loader"), json=BODY).status_code == 429
        )
        if failure == "policy":
            events = app.state.registry.audit_events
            assert len(events) == 1 and events[0].outcome == "denied"
        if failure == "audit":
            assert len(app.state.capabilities) == 0
