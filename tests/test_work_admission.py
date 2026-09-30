"""M-001/P2 / SEC-06: overload bounds, recovery and cancellation contracts."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from prometheus_client import CollectorRegistry, generate_latest

from asset_store_core.admission import WorkAdmission, positive_limit_from_env
from asset_store_core.api import create_app
from asset_store_core.errors import ValidationError, WorkCapacityError
from asset_store_core.object_store import LocalObjectStore, StoredObjectStat
from asset_store_core.storage import ObjectStoreLocation
from fetcher_service.app import create_app as create_fetcher_app
from fetcher_service.client import AssetStoreClient
from fetcher_service.fetcher import FetchedContent
from fetcher_service.rules import RuleSet
from fetcher_service.service import UpstreamError


@pytest.mark.parametrize("raw", ["0", "-1", "1.5", "secret-invalid"])
def test_invalid_limits_do_not_expose_values(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    for name in ["ASSET_STORE_MAX_INFLIGHT_UPLOADS", "FETCHER_MAX_INFLIGHT_JOBS"]:
        monkeypatch.setenv(name, raw)
        with pytest.raises(ValidationError, match=name) as exc:
            positive_limit_from_env(name, 4)
        assert raw not in str(exc.value)


def test_concurrent_admission_never_exceeds_bound_and_recovers() -> None:
    metrics = CollectorRegistry()
    gate = WorkAdmission(limit=3, name="test_work", metrics=metrics, logger=logging.getLogger())
    release = threading.Event()
    entered = threading.Barrier(4)

    def hold() -> None:
        with gate.lease():
            entered.wait(timeout=5)
            assert release.wait(5)

    with ThreadPoolExecutor(max_workers=3) as executor:
        work = [executor.submit(hold) for _ in range(3)]
        try:
            entered.wait(timeout=5)
            assert gate.active() == 3
            for _ in range(20):
                with pytest.raises(WorkCapacityError), gate.lease():
                    pytest.fail("overload entered work")
            assert "test_work_inflight 3.0" in generate_latest(metrics).decode()
        finally:
            release.set()
        for job in work:
            job.result(timeout=5)
    with pytest.raises(RuntimeError), gate.lease():
        raise RuntimeError("job failed")
    with gate.lease():
        assert gate.active() == 1
    assert gate.active() == 0


async def mint(client: httpx.AsyncClient) -> dict[str, str]:
    result = await client.post(
        "/capabilities",
        headers={"Authorization": "Service bulk-loader:dev-secret:bulk-loader"},
        json={"operation": "write", "scope_prefix": "cache/gallica", "ttl_seconds": 300},
    )
    assert result.status_code == 201
    return {"Authorization": "Capability " + result.json()["capability_id"]}


def test_upload_admission_precedes_body_and_recovers_after_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSET_STORE_MAX_INFLIGHT_UPLOADS", "1")
    app = create_app()

    async def scenario() -> None:
        entered, release = asyncio.Event(), asyncio.Event()
        consumed: list[bool] = []

        async def slow_body() -> AsyncIterator[bytes]:
            entered.set()
            await asyncio.wait_for(release.wait(), timeout=5)
            yield b"body"

        async def rejected_body() -> AsyncIterator[bytes]:
            consumed.append(True)
            yield b"body"

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as api:
            headers = await mint(api)
            task = asyncio.create_task(
                api.put("/objects/cache/gallica/slow", headers=headers, content=slow_body())
            )
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                assert app.state.uploads.active() == 1
                denied = await api.put(
                    "/objects/cache/gallica/overload", headers=headers, content=rejected_body()
                )
                assert denied.status_code == 503
                assert denied.headers["Retry-After"] == "1"
                assert denied.json()["title"] == "WorkCapacityError"
                assert not consumed
                unauthenticated = await api.put(
                    "/objects/cache/gallica/denied", content=rejected_body()
                )
                assert unauthenticated.status_code == 403
                assert not consumed
                assert not app.state.registry.list_assets()
            finally:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert app.state.uploads.active() == 0
            response = await api.put(
                "/objects/cache/gallica/recovered", headers=headers, content=b"ok"
            )
            assert response.status_code == 201
            metrics = (await api.get("/metrics")).text
            assert 'asset_store_upload_admission_total{outcome="denied"} 1.0' in metrics
            assert "asset_store_upload_inflight 0.0" in metrics

    asyncio.run(scenario())


class BlockingStore(LocalObjectStore):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def put_object(self, location: ObjectStoreLocation, data: bytes) -> StoredObjectStat:
        self.entered.set()
        assert self.release.wait(5)
        return super().put_object(location, data)


def test_cancelled_upload_holds_slot_until_storage_worker_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSET_STORE_MAX_INFLIGHT_UPLOADS", "1")
    store = BlockingStore()
    app = create_app(store=store)

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as api:
            headers = await mint(api)
            task = asyncio.create_task(
                api.put("/objects/cache/gallica/a", headers=headers, content=b"bytes")
            )
            try:
                assert await asyncio.to_thread(store.entered.wait, 5)
                task.cancel()
                # Let cancellation reach the endpoint while the thread is blocked.
                for _ in range(5):
                    await asyncio.sleep(0)
                assert not task.done()
                assert app.state.uploads.active() == 1
                denied = await api.put(
                    "/objects/cache/gallica/b", headers=headers, content=b"bytes"
                )
                assert denied.status_code == 503
            finally:
                store.release.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert app.state.uploads.active() == 0
            response = await api.put("/objects/cache/gallica/b", headers=headers, content=b"bytes")
            assert response.status_code == 201

    asyncio.run(scenario())


class BlockingFetcher:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def fetch(self, url: str) -> FetchedContent:
        self.calls += 1
        self.entered.set()
        assert self.release.wait(5)
        raise UpstreamError("controlled origin failure")


def test_fetcher_overload_does_not_start_origin_work_and_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FETCHER_MAX_INFLIGHT_JOBS", "1")
    fetcher = BlockingFetcher()
    store_http = httpx.Client(
        base_url="http://unused",
        transport=httpx.MockTransport(lambda request: httpx.Response(404)),
    )
    app = create_fetcher_app(
        asset_store_client=AssetStoreClient(store_http, service_secret="dev-secret:fetcher"),
        fetcher=fetcher,
        rules=RuleSet(rules=()),
    )

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as api:
            auth = {"Authorization": "Service task-api:dev-secret:task-api"}
            body = {"url": "https://example.test/image", "tmp_id": "test"}
            task = asyncio.create_task(api.post("/v1/ensure-url", headers=auth, json=body))
            try:
                assert await asyncio.to_thread(fetcher.entered.wait, 5)
                denied = await api.post("/v1/ensure-url", headers=auth, json=body)
                assert denied.status_code == 503
                assert denied.headers["Retry-After"] == "1"
                assert fetcher.calls == 1
                assert (await api.get("/healthz")).status_code == 200
                assert (await api.post("/v1/ensure-url", json=body)).status_code == 401
            finally:
                fetcher.release.set()
                assert (await task).status_code == 502
            assert app.state.jobs.active() == 0
            assert (await api.post("/v1/ensure-url", headers=auth, json=body)).status_code == 502
            assert fetcher.calls == 2
            metrics = (await api.get("/metrics")).text
            assert 'fetcher_job_admission_total{outcome="denied"} 1.0' in metrics
            assert "fetcher_job_inflight 0.0" in metrics

    try:
        asyncio.run(scenario())
    finally:
        store_http.close()


@pytest.mark.parametrize("failure", ["oversize", "checksum", "storage"])
def test_upload_slots_release_after_failure(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    monkeypatch.setenv("ASSET_STORE_MAX_INFLIGHT_UPLOADS", "1")
    monkeypatch.setenv("ASSET_STORE_MAX_UPLOAD_BYTES", "4")

    class FailingStore(LocalObjectStore):
        def put_object(self, location: ObjectStoreLocation, data: bytes) -> StoredObjectStat:
            if failure == "storage" and data == b"fail":
                raise RuntimeError("controlled failure")
            return super().put_object(location, data)

    app = create_app(store=FailingStore())

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, raise_app_exceptions=False), base_url="http://test"
        ) as api:
            headers = await mint(api)
            response = await api.put(
                "/objects/cache/gallica/a",
                headers=headers,
                content=b"large" if failure == "oversize" else b"fail",
                params={"expected_checksum": "sha256:wrong"} if failure == "checksum" else {},
            )
            assert (
                response.status_code == {"oversize": 413, "checksum": 409, "storage": 500}[failure]
            )
            assert app.state.uploads.active() == 0
            retry = await api.put("/objects/cache/gallica/b", headers=headers, content=b"ok")
            assert retry.status_code == 201
            assert app.state.uploads.active() == 0

    asyncio.run(scenario())
