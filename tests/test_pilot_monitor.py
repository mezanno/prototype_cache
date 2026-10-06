"""M-001/P5: operator alerts must detect failure without exposing metric labels."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/pilot"))
from monitor import lifecycle_alerts, summarize_metrics  # noqa: E402


def test_metrics_omit_labels_and_sum_outcomes() -> None:
    result = summarize_metrics(
        'fetcher_cache_operations_total{outcome="hit",alias="private"} 3\n'
        'fetcher_cache_operations_total{outcome="miss"} 2\n'
        "unselected_secret_metric 9\nfetcher_cache_operations_created 100\n"
    )
    assert result == {
        "fetcher_cache_operations_total{outcome=hit}": 3,
        "fetcher_cache_operations_total{outcome=miss}": 2,
    }
    assert "private" not in str(result)


def test_worker_capacity_uses_each_bucket_not_sum() -> None:
    body = 'storage_space_used_ratio{space="cache"} 0.5\n'
    body += 'storage_space_used_ratio{space="tmp"} 0.5\n'
    assert lifecycle_alerts(body, 60) == []
    assert lifecycle_alerts(body.replace("0.5", "0.81"), 181) == [
        "capacity_high",
        "lifecycle_stale",
    ]


def test_cleanup_errors_and_exhaustion_are_visible() -> None:
    assert lifecycle_alerts("gc_errors_total 1\ngc_eviction_exhausted 1\n", 0) == [
        "gc_errors_total",
        "gc_eviction_exhausted",
    ]


def test_unavailable_metrics_fail_closed() -> None:
    with pytest.raises(ValueError):
        summarize_metrics("asset_store_reserved_upload_bytes NaN\n")
    assert lifecycle_alerts("storage_space_used_ratio NaN\n", 0) == ["lifecycle_metric_unavailable"]


def test_snapshot_reports_failures_without_exception_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess
    import urllib.request

    import monitor

    def unavailable(*args: object, **kwargs: object) -> str:
        raise OSError("sensitive-credential")

    monkeypatch.setattr(monitor, "docker", unavailable)
    monkeypatch.setattr(subprocess, "run", unavailable)
    monkeypatch.setattr(urllib.request, "urlopen", unavailable)
    report = monitor.snapshot()
    assert report["alerts"] == [
        "asset-store_http_unavailable",
        "docker_disk_unavailable",
        "docker_unavailable",
        "fetcher_http_unavailable",
        "lifecycle_unavailable",
    ]
    assert "sensitive-credential" not in str(report)


def test_latest_snapshot_is_private_and_replaced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    import monitor

    output = tmp_path / "monitor.json"
    output.write_text("old")
    monkeypatch.setattr(sys, "argv", ["monitor.py", "--output", str(output)])
    monkeypatch.setattr(monitor, "snapshot", lambda: {"alerts": ["lifecycle_stale"]})
    assert monitor.main() == 1
    assert json.loads(output.read_text()) == {"alerts": ["lifecycle_stale"]}
    assert output.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.iterdir()) == [output]
