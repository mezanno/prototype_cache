"""M-001/P5 / FR-064 / NFR-009: private, read-only operator health snapshot."""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from prometheus_client.parser import text_string_to_metric_families

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    str(ROOT / "deploy/pilot/private/pilot.env"),
    "-f",
    str(ROOT / "deploy/pilot/compose.yml"),
]
PREFIXES = (
    "fetcher_cache_operations_",
    "fetcher_job_",
    "fetcher_refetch_checks_",
    "asset_store_upload_",
    "asset_store_reserved_upload_bytes",
    "asset_store_registry_",
    "asset_store_failed_upload_cleanup_",
    "asset_store_capability_issued_",
    "gc_",
    "storage_space_used_ratio",
)


def summarize_metrics(body: str) -> dict[str, float]:
    """Aggregate selected samples, omitting identifying labels and timestamps."""
    totals: dict[str, float] = {}
    for family in text_string_to_metric_families(body):
        for sample in family.samples:
            if sample.name.startswith(PREFIXES) and not sample.name.endswith("_created"):
                if not math.isfinite(sample.value):
                    raise ValueError("metric unavailable")
                labels = ",".join(
                    f"{key}={sample.labels[key]}"
                    for key in ("operation", "outcome", "space", "reason")
                    if key in sample.labels
                )
                name = sample.name + ("{" + labels + "}" if labels else "")
                totals[name] = totals.get(name, 0) + sample.value
    return totals


def lifecycle_alerts(body: str, age: float) -> list[str]:
    """Detect stale sweeps, capacity pressure and cleanup failure (FR-064)."""
    alerts = ["lifecycle_stale"] if age > 180 or age < 0 else []
    for family in text_string_to_metric_families(body):
        for sample in family.samples:
            if not math.isfinite(sample.value):
                alerts.append("lifecycle_metric_unavailable")
            elif sample.name == "storage_space_used_ratio" and sample.value > 0.8:
                alerts.append("capacity_high")
            elif sample.name in ("gc_errors_total", "gc_eviction_exhausted") and sample.value > 0:
                alerts.append(sample.name)
    return sorted(set(alerts))


def docker(*args: str) -> str:
    """Capture output privately; never expose backend exception messages."""
    return subprocess.run(
        [*COMPOSE, *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout


def snapshot() -> dict[str, object]:
    """Read health, metric aggregates, Docker filesystem and worker freshness."""
    alerts: list[str] = []
    report: dict[str, object] = {"event": "pilot.monitor", "timestamp": time.time()}
    try:
        rows = [json.loads(line) for line in docker("ps", "--format", "json").splitlines()]
        states = {row["Service"]: row for row in rows}
        for service in ("garage", "postgres", "asset-store", "fetcher", "lifecycle"):
            row = states.get(service, {})
            if row.get("State") != "running" or (
                service != "lifecycle" and row.get("Health") != "healthy"
            ):
                alerts.append(service + "_unhealthy")
    except (OSError, ValueError, subprocess.SubprocessError):
        alerts.append("docker_unavailable")
    for service, port in (("asset-store", 18000), ("fetcher", 18001)):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/readyz", timeout=5) as response:
                response.read()
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5) as response:
                metrics = summarize_metrics(response.read().decode())
            report[service] = metrics
            if any(not math.isfinite(value) for value in metrics.values()):
                alerts.append(service + "_metric_unavailable")
        except (OSError, ValueError):
            alerts.append(service + "_http_unavailable")
    try:
        probe = (
            "import json,time; from pathlib import Path; p=Path('/tmp/lifecycle.prom'); "
            "print(json.dumps({'age':time.time()-p.stat().st_mtime,'body':p.read_text()}))"
        )
        worker = json.loads(docker("exec", "-T", "lifecycle", "python", "-c", probe))
        report["lifecycle_age_seconds"] = worker["age"]
        report["lifecycle"] = summarize_metrics(worker["body"])
        alerts.extend(lifecycle_alerts(worker["body"], worker["age"]))
    except (OSError, ValueError, subprocess.SubprocessError):
        alerts.append("lifecycle_unavailable")
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.DockerRootDir}}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        disk = shutil.disk_usage(result.stdout.strip())
        report["docker_disk_free_bytes"] = disk.free
        report["docker_disk_free_ratio"] = disk.free / disk.total
        if disk.free / disk.total < 0.1:
            alerts.append("docker_disk_low")
    except (OSError, subprocess.SubprocessError):
        alerts.append("docker_disk_unavailable")
    report["alerts"] = sorted(set(alerts))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Atomically replace a private JSON snapshot")
    args = parser.parse_args()
    report = snapshot()
    body = json.dumps(report, allow_nan=False) + "\n"
    if args.output:
        with tempfile.NamedTemporaryFile(mode="w", dir=args.output.parent, delete=False) as file:
            temporary = Path(file.name)
            try:
                file.write(body)
                file.close()
                os.replace(temporary, args.output)
            finally:
                temporary.unlink(missing_ok=True)
    else:
        print(body, end="")
    return int(bool(report["alerts"]))


if __name__ == "__main__":
    raise SystemExit(main())
