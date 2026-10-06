"""M-001/P6: integrity, overload transparency, scheduled window and privacy."""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/cache-pilot"))
import pilot_acceptance as acceptance  # noqa: E402

URL = "https://gallica.bnf.fr/iiif/ark:/12148/fixture1/f1/full/800,/0/native.jpg"
ITEM: dict[str, Any] = {
    "url": URL,
    "size_bytes": 5,
    "checksum": "sha256:" + hashlib.sha256(b"image").hexdigest(),
}


def test_retries_retain_overload_status_and_never_preload(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        assert request.method == "GET"
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, headers={"Retry-After": "1"})
        return httpx.Response(
            200,
            content=b"image",
            headers={
                "Content-Type": "image/jpeg",
                "ETag": '"' + ITEM["checksum"] + '"',
            },
        )

    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    with httpx.Client(base_url="http://localhost", transport=httpx.MockTransport(respond)) as http:
        result = acceptance.verified_read(http, ITEM)
    assert result["ok"] and result["attempts"] == [503, 200]
    assert sleeps == [1]


@pytest.mark.parametrize("content,error", [(b"other", "integrity"), (b"oversized", "byte_limit")])
def test_reads_fail_on_content_corruption(content: bytes, error: str) -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            content=content,
            headers={
                "Content-Type": "image/jpeg",
                "ETag": '"' + ITEM["checksum"] + '"',
            },
        )
    )
    with httpx.Client(base_url="http://localhost", transport=transport) as http:
        assert acceptance.verified_read(http, ITEM)["error"] == error


def test_retry_limit_does_not_hide_failed_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    transport = httpx.MockTransport(lambda _: httpx.Response(503))
    with httpx.Client(base_url="http://localhost", transport=transport) as http:
        result = acceptance.verified_read(http, ITEM)
    assert not result["ok"] and result["attempts"] == [503, 503, 503]


def state() -> dict[str, Any]:
    return {
        "status": "running",
        "started_at": 0,
        "deadline": 86400,
        "baseline_origin_connections": 0,
        "samples": [],
        "issues": [],
        "issue_count": 0,
    }


def test_deadline_finishes_without_work_and_records_missing_schedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden() -> float:
        raise AssertionError("work after deadline")

    monkeypatch.setattr(acceptance, "origin_counter", forbidden)
    monkeypatch.setattr(acceptance, "resource_sample", lambda *args: {})
    report = state()
    report["samples"] = [{"timestamp": 86340}]
    acceptance.tick(report, [ITEM], "secret", 86400)
    assert report["status"] == "observations_complete_review_required"
    assert report["observed_span_seconds"] == 86400
    incomplete = state()
    acceptance.tick(incomplete, [ITEM], "secret", 86400)
    assert incomplete["issues"][-1]["issue"] == "schedule_gap_or_clock_change"
    assert incomplete["issue_count"] == 1


def test_failures_count_once_each_and_keep_partial_read_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(acceptance, "origin_counter", lambda: 0.0)
    monkeypatch.setattr(acceptance, "run_reads", lambda *args: {"errors": {}, "bytes": 15})

    def unavailable(now: float, fixture_id: str | None = None) -> dict[str, Any]:
        raise OSError("sensitive-secret")

    monkeypatch.setattr(acceptance, "resource_sample", unavailable)
    report = state()
    acceptance.tick(report, [ITEM], "secret", 60)
    acceptance.tick(report, [ITEM], "secret", 120)
    assert report["issue_count"] == 2
    assert report["samples"][0]["reads"]["bytes"] == 15
    assert "sensitive-secret" not in json.dumps(report)


def test_report_replacement_is_private_and_does_not_follow_symlink(tmp_path: Path) -> None:
    target = tmp_path / "owner-file"
    target.write_text("preserved")
    report = tmp_path / "report.json"
    report.symlink_to(target)
    acceptance.atomic_write(report, {"status": "running"})
    assert target.read_text() == "preserved"
    assert not report.is_symlink()
    assert report.stat().st_mode & 0o777 == 0o600


def test_approved_corpus_is_three_urls_two_resources() -> None:
    corpus = acceptance.load_corpus(acceptance.ROOT / "tools/cache-pilot/pilot-corpus.json")
    assert len(corpus) == 3
    from fetcher_service.pilot_policy import GallicaPolicy

    assert len({GallicaPolicy().require(item["url"]).fetch_url for item in corpus}) == 2


def test_three_clients_over_real_http_cache_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket
    import threading

    import uvicorn
    from fastapi.testclient import TestClient

    from asset_store_core.api import create_app as asset_app
    from fetcher_service.app import create_app
    from fetcher_service.client import AssetStoreClient
    from fetcher_service.fetcher import FetchedContent

    image = (Path(__file__).parent / "fixtures/gallica/image.jpg").read_bytes()
    item = {
        "url": URL,
        "size_bytes": len(image),
        "checksum": "sha256:" + hashlib.sha256(image).hexdigest(),
    }

    class Origin:
        calls = 0

        def fetch(self, url: str) -> FetchedContent:
            self.calls += 1
            return FetchedContent(image, "image/jpeg")

    origin = Origin()
    monkeypatch.setenv("FETCHER_MAX_INFLIGHT_JOBS", "2")
    with TestClient(asset_app()) as storage:
        app = create_app(
            asset_store_client=AssetStoreClient(storage, service_secret="dev-secret:fetcher"),
            fetcher=origin,
        )
        with TestClient(app) as seed:
            response = seed.post(
                "/v1/cache/preload",
                json={"url": URL},
                headers={"Authorization": "Service task-api:dev-secret:task-api"},
            )
            assert response.status_code == 200
        server = uvicorn.Server(uvicorn.Config(app, log_level="critical"))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            monkeypatch.setattr(acceptance, "BASE", f"http://127.0.0.1:{listener.getsockname()[1]}")
            thread = threading.Thread(
                target=server.run, kwargs={"sockets": [listener]}, daemon=True
            )
            thread.start()
            try:
                deadline = time.monotonic() + 5
                while not server.started and thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert server.started
                report = acceptance.run_reads([item], "dev-secret:task-api", 3)
                assert report["clients"] == 3 and report["successful_reads"] == 9
                assert report["bytes"] == 9 * len(image) and report["errors"] == {}
                assert report["http_attempt_statuses"]["200"] == 9
                assert origin.calls == 1
            finally:
                server.should_exit = True
                thread.join(timeout=5)
                assert not thread.is_alive()


def test_changed_corpus_stops_before_work_and_redacts_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tmp_path.chmod(0o700)
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps([ITEM]))
    credentials = tmp_path / "fetcher.env"
    credentials.write_text("ASSET_STORE_SERVICE_CREDENTIALS=task-api:sensitive-secret\n")
    credentials.chmod(0o600)
    report = tmp_path / "state.json"
    report.write_text(json.dumps({"corpus_sha256": "old"}))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pilot_acceptance.py",
            "tick",
            "--state",
            str(report),
            "--corpus",
            str(corpus),
            "--credentials",
            str(credentials),
        ],
    )
    assert acceptance.main() == 1
    assert "sensitive-secret" not in capsys.readouterr().out
    assert json.loads(report.read_text()) == {"corpus_sha256": "old"}


def test_concurrent_monitor_refresh_is_not_mistaken_for_clock_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    directory = tmp_path / "deploy/pilot/private"
    directory.mkdir(parents=True)
    (directory / "monitor.json").write_text(json.dumps({"timestamp": 120, "alerts": []}))
    monkeypatch.setattr(acceptance, "ROOT", tmp_path)
    monkeypatch.setattr(time, "time", lambda: 121)

    def result(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        body = (
            {}
            if "exec" in args
            else {
                "ID": "id",
                "Name": "name",
                "MemUsage": "1MiB",
                "MemPerc": "1%",
                "CPUPerc": "0%",
                "PIDs": "1",
            }
        )
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(body), stderr="")

    monkeypatch.setattr(subprocess, "run", result)
    monkeypatch.setattr(acceptance, "metric_values", lambda *args: {})
    # The monitor finished after the read round started, but before resource capture.
    resources = acceptance.resource_sample(100)
    assert resources["observed_at"] == 121 and resources["monitor"]["timestamp"] == 120


def test_accelerated_pacing_skips_backpressure_without_catchup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import accelerated_acceptance as accelerated

    clock = [0.0]

    class Stop:
        def is_set(self) -> bool:
            return False

        def wait(self, delay: float) -> bool:
            clock[0] += delay
            return False

    class Client:
        def __init__(self, **kwargs: Any) -> None:
            assert kwargs["follow_redirects"] is False

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    starts: list[float] = []

    def read(*args: Any) -> dict[str, Any]:
        starts.append(clock[0])
        clock[0] += 1.1
        return {"ok": True, "attempts": [503, 200], "bytes": 5, "elapsed_ms": 1100}

    monkeypatch.setattr(accelerated, "DURATION", 3)
    monkeypatch.setattr(accelerated, "ROUNDS", 6)
    monkeypatch.setattr(accelerated, "INTERVAL", 0.5)
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(httpx, "Client", Client)
    monkeypatch.setattr(acceptance, "verified_read", read)
    result = accelerated.paced_client(0, [ITEM], "secret", 0, Stop())  # type: ignore[arg-type]
    assert starts == [0, 1.1, 2.2]
    assert result["skipped_slots"] == 2 and result["unstarted_slots"] == 1
    assert [row["slot"] for row in result["reads"]] == [0, 2, 4]


def test_accelerated_summary_preserves_failures_and_overloads() -> None:
    import accelerated_acceptance as accelerated

    report = accelerated.summary(
        [
            {
                "skipped_slots": 2,
                "unstarted_slots": 1,
                "reads": [
                    {"ok": True, "attempts": [503, 200], "bytes": 5, "elapsed_ms": 1000},
                    {"ok": False, "attempts": [503, 503, 503], "error": "http_status"},
                ],
            }
        ]
    )
    assert report["successful_reads"] == 1 and report["attempted_reads"] == 2
    assert report["http_attempt_statuses"] == {"503": 4, "200": 1}
    assert report["errors"] == {"http_status": 1}
    assert report["p95_ms_with_retries"] == 1000


def test_accelerated_refuses_existing_evidence_before_any_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import accelerated_acceptance as accelerated

    report = tmp_path / "report.json"
    report.write_text("preserved")

    def forbidden() -> float:
        raise AssertionError("unexpected network")

    monkeypatch.setattr(acceptance, "origin_counter", forbidden)
    with pytest.raises(ValueError, match="overwrite"):
        accelerated.run(report, [ITEM], "secret", "digest")
    assert report.read_text() == "preserved"


def test_accelerated_short_harness_records_resources_and_final_outcomes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import accelerated_acceptance as accelerated

    monkeypatch.setattr(accelerated, "DURATION", 0.3)
    monkeypatch.setattr(accelerated, "ROUNDS", 2)
    monkeypatch.setattr(accelerated, "INTERVAL", 0.025)
    monkeypatch.setattr(acceptance, "origin_counter", lambda: 0)
    monkeypatch.setattr(acceptance, "resource_sample", lambda *args: {"monitor": {"alerts": []}})
    monkeypatch.setattr(
        acceptance,
        "verified_read",
        lambda *args: {
            "ok": True,
            "attempts": [200],
            "bytes": 5,
            "elapsed_ms": 1,
        },
    )
    report = tmp_path / "accelerated.json"
    assert accelerated.run(report, [ITEM], "secret", "digest") == 0
    state = json.loads(report.read_text())
    assert state["status"] == "observations_complete_review_required"
    assert state["samples"] and state["final_origin_connections"] == 0
    assert state["summary"]["attempted_reads"] <= 6
    assert state["summary"]["successful_reads"] == state["summary"]["attempted_reads"]
    assert "secret" not in report.read_text()
    assert report.stat().st_mode & 0o777 == 0o600


def test_accelerated_interrupt_preserves_incomplete_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import accelerated_acceptance as accelerated

    monkeypatch.setattr(acceptance, "origin_counter", lambda: 0)
    calls = 0

    def interrupt(*args: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise KeyboardInterrupt
        return {"monitor": {"alerts": []}}

    monkeypatch.setattr(acceptance, "resource_sample", interrupt)
    monkeypatch.setattr(
        accelerated,
        "paced_client",
        lambda *args: {
            "client": args[0],
            "reads": [],
            "skipped_slots": 0,
            "unstarted_slots": 1440,
        },
    )
    report = tmp_path / "interrupt.json"
    assert accelerated.run(report, [ITEM], "secret", "digest") == 1
    data = json.loads(report.read_text())
    assert data["status"] == "interrupted_review_required"
    assert data["summary"]["unstarted_slots"] == 4320


def test_accelerated_origin_change_remains_a_failed_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import accelerated_acceptance as accelerated

    values = iter([0, 1])
    monkeypatch.setattr(acceptance, "origin_counter", lambda: next(values, 1))
    monkeypatch.setattr(acceptance, "resource_sample", lambda *args: {"monitor": {"alerts": []}})
    monkeypatch.setattr(accelerated, "DURATION", 0.01)
    monkeypatch.setattr(
        accelerated,
        "paced_client",
        lambda *args: {
            "client": args[0],
            "reads": [],
            "skipped_slots": 0,
            "unstarted_slots": 1440,
        },
    )
    report = tmp_path / "changed.json"
    assert accelerated.run(report, [ITEM], "secret", "digest") == 1
    assert "origin_counter_changed_or_reset" in json.loads(report.read_text())["issues"]
