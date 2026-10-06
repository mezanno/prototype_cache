"""M-001/P6 / B-015/B-019: bounded, cache-only burst and real 24-hour soak ticks."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
from prometheus_client.parser import text_string_to_metric_families

from fetcher_service.errors import PilotDeniedError
from fetcher_service.pilot_policy import IMAGE_MIMES, GallicaPolicy

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:18001"
DURATION = 86400
MAX_SAMPLES = 1441
COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    str(ROOT / "deploy/pilot/private/pilot.env"),
    "-f",
    str(ROOT / "deploy/pilot/compose.yml"),
]


def read_credential(path: Path) -> str:
    """Read one existing task-api secret without shell evaluation or output."""
    if not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("credential file must be protected")
    for line in path.read_text().splitlines():
        key, _, value = line.partition("=")
        if key == "ASSET_STORE_SERVICE_CREDENTIALS":
            for entry in value.split(","):
                identity, _, secret = entry.partition(":")
                if identity == "task-api" and secret:
                    return secret
    raise ValueError("task-api credential is missing")


def load_corpus(path: Path) -> list[dict[str, Any]]:
    """Freeze exact approved renditions and expected integrity (NFR-005)."""
    items: list[dict[str, Any]] = json.loads(path.read_text())
    if not items or len(items) > 100:
        raise ValueError("corpus must contain 1 to 100 entries")
    for item in items:
        GallicaPolicy().require(item["url"])
        size = item["size_bytes"]
        if type(size) is not int or not 0 < size <= 52428800:
            raise ValueError("invalid expected size")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", item["checksum"]) is None:
            raise ValueError("invalid expected checksum")
    return items


def verified_read(http: httpx.Client, item: dict[str, Any]) -> dict[str, Any]:
    """Bound streaming bytes and retries; retain every overload status."""
    target = GallicaPolicy().require(item["url"])
    start = time.perf_counter()
    attempts: list[int] = []
    for attempt in range(3):
        try:
            with http.stream("GET", "/" + target.host + target.path) as response:
                attempts.append(response.status_code)
                if response.status_code == 503 and attempt < 2:
                    retry = response.headers.get("Retry-After", "1")
                    delay = min(2, max(0.1, float(retry)))
                elif response.status_code != 200:
                    return {"ok": False, "error": "http_status", "attempts": attempts}
                else:
                    digest = hashlib.sha256()
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > item["size_bytes"]:
                            return {"ok": False, "error": "byte_limit", "attempts": attempts}
                        digest.update(chunk)
                    checksum = "sha256:" + digest.hexdigest()
                    mime = response.headers.get("Content-Type", "").split(";", 1)[0]
                    if (
                        size != item["size_bytes"]
                        or checksum != item["checksum"]
                        or response.headers.get("ETag") != '"' + checksum + '"'
                        or mime not in IMAGE_MIMES
                    ):
                        return {"ok": False, "error": "integrity", "attempts": attempts}
                    return {
                        "ok": True,
                        "attempts": attempts,
                        "bytes": size,
                        "elapsed_ms": (time.perf_counter() - start) * 1000,
                    }
            time.sleep(delay)
        except (httpx.HTTPError, ValueError):
            return {"ok": False, "error": "transport_or_protocol", "attempts": attempts}
    raise AssertionError("unreachable")


def run_reads(items: list[dict[str, Any]], secret: str, cycles: int) -> dict[str, Any]:
    """Three independent HTTP clients start together; no origin preload route."""
    barrier = threading.Barrier(3)

    def worker(index: int) -> list[dict[str, Any]]:
        with httpx.Client(
            base_url=BASE,
            trust_env=False,
            follow_redirects=False,
            timeout=15,
            headers={"Authorization": "Service task-api:" + secret},
        ) as http:
            barrier.wait(timeout=10)
            return [verified_read(http, items[(index + n) % len(items)]) for n in range(cycles)]

    with ThreadPoolExecutor(max_workers=3) as executor:
        groups = list(executor.map(worker, range(3)))
    rows = [row for group in groups for row in group]
    latencies = sorted(row["elapsed_ms"] for row in rows if row["ok"])
    return {
        "clients": 3,
        "logical_reads": len(rows),
        "successful_reads": len(latencies),
        "bytes": sum(row.get("bytes", 0) for row in rows),
        "http_attempt_statuses": dict(Counter(str(s) for row in rows for s in row["attempts"])),
        "errors": dict(Counter(row["error"] for row in rows if not row["ok"])),
        "p95_ms_with_retries": latencies[math.ceil(len(latencies) * 0.95) - 1]
        if latencies
        else None,
        "max_ms_with_retries": max(latencies) if latencies else None,
    }


def atomic_write(path: Path, state: dict[str, Any]) -> None:
    """Replace one bounded mode-600 report, without following output symlinks."""
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        try:
            json.dump(state, file, allow_nan=False)
            file.write("\n")
            file.close()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def metric_values(url: str, names: set[str]) -> dict[str, float]:
    with httpx.Client(trust_env=False, timeout=5) as http:
        response = http.get(url)
        response.raise_for_status()
    result: dict[str, float] = {}
    for family in text_string_to_metric_families(response.text):
        for sample in family.samples:
            if sample.name in names:
                if not math.isfinite(sample.value):
                    raise ValueError("unavailable metric")
                result[sample.name] = result.get(sample.name, 0) + sample.value
    return result


def resource_sample(now: float, fixture_id: str | None = None) -> dict[str, Any]:
    """Capture existing signals without credentials, queries, aliases or object keys."""
    monitor = json.loads((ROOT / "deploy/pilot/private/monitor.json").read_text())
    observed_at = time.time()
    if not 0 <= observed_at - monitor["timestamp"] <= 180:
        raise ValueError("monitor snapshot stale")
    probe = (
        "import os,json,psycopg; "
        "c=psycopg.connect(os.environ['ASSET_STORE_PG_DSN']); "
        "q=c.cursor(); q.execute('SELECT "
        "(SELECT count(*) FROM assets),(SELECT count(*) FROM aliases),"
        "(SELECT count(*) FROM audit_events),pg_database_size(current_database()),"
        "(SELECT CAST(coalesce(sum(size_bytes),0) AS bigint) FROM assets "
        "WHERE payload_deleted_at IS NULL)'); "
        "print(json.dumps(dict(zip(['assets','aliases','audit_rows','database_bytes',"
        "'retained_payload_bytes'],q.fetchone())))); c.close()"
    )
    result = subprocess.run(
        [*COMPOSE, "exec", "-T", "asset-store", "python", "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    stats = subprocess.run(
        [
            "docker",
            "stats",
            "--no-stream",
            "--format",
            "{{json .}}",
            *[
                f"asset-store-pilot-{name}-1"
                for name in ("asset-store", "fetcher", "postgres", "garage", "lifecycle")
            ],
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    sample: dict[str, Any] = {
        "observed_at": observed_at,
        "monitor": monitor,
        "database": json.loads(result.stdout),
        "containers": [
            {key: row[key] for key in ("ID", "Name", "MemUsage", "MemPerc", "CPUPerc", "PIDs")}
            for row in (json.loads(line) for line in stats.stdout.splitlines())
        ],
        "capabilities": metric_values(
            "http://127.0.0.1:18000/metrics",
            {
                "asset_store_active_capabilities",
                "asset_store_registry_requests_waiting",
            },
        ),
    }
    if fixture_id:
        fixture_probe = (
            "import os,json,psycopg,boto3; from botocore.exceptions import ClientError; "
            "c=psycopg.connect(os.environ['ASSET_STORE_PG_DSN']); q=c.cursor(); "
            "q.execute('SELECT space,storage_key,state,size_bytes,expired_at,payload_deleted_at "
            "FROM assets WHERE asset_id=%s',(os.environ['ACCEPTANCE_FIXTURE_ID'],)); "
            "space,key,state,size,expired,deleted=q.fetchone(); c.close(); "
            "s=boto3.client('s3',endpoint_url=os.environ['ASSET_STORE_S3_ENDPOINT'],"
            "region_name=os.environ['ASSET_STORE_S3_REGION'],"
            "aws_access_key_id=os.environ['ASSET_STORE_S3_ACCESS_KEY'],"
            "aws_secret_access_key=os.environ['ASSET_STORE_S3_SECRET_KEY']); exists=True\n"
            "try: s.head_object(Bucket=space,Key=key)\n"
            "except ClientError as e:\n"
            " if e.response['Error']['Code'] not in ('404','NoSuchKey','NotFound'): raise\n"
            " exists=False\n"
            "print(json.dumps({'state':state,'size_bytes':size,'expired_at':str(expired),"
            "'payload_deleted_at':str(deleted),'physical_exists':exists}))"
        )
        result = subprocess.run(
            [
                *COMPOSE,
                "exec",
                "-T",
                "-e",
                "ACCEPTANCE_FIXTURE_ID=" + fixture_id,
                "asset-store",
                "python",
                "-c",
                fixture_probe,
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        sample["lifecycle_fixture"] = json.loads(result.stdout)
    return sample


def origin_counter() -> float:
    return metric_values(BASE + "/metrics", {"fetcher_outbound_connections_total"}).get(
        "fetcher_outbound_connections_total", 0
    )


def tick(
    state: dict[str, Any],
    items: list[dict[str, Any]],
    secret: str,
    now: float,
) -> None:
    """One bounded tick; observed failures remain visible through completion."""
    if state["status"] != "running":
        return

    def issue(name: str) -> None:
        state["issues"].append({"timestamp": now, "issue": name})
        state["issue_count"] += 1
        state["issues"] = state["issues"][-MAX_SAMPLES:]

    previous = state["samples"][-1]["timestamp"] if state["samples"] else state["started_at"]
    if now < previous or now - previous > 180:
        issue("schedule_gap_or_clock_change")
    if now >= state["deadline"]:
        state["status"] = "observations_complete_review_required"
        state["finished_at"] = now
        state["observed_span_seconds"] = now - state["started_at"]
        try:
            state["final_resources"] = resource_sample(now, state.get("lifecycle_fixture_id"))
        except (OSError, ValueError, KeyError, httpx.HTTPError, subprocess.SubprocessError):
            issue("final_observation_unavailable")
        return
    if len(state["samples"]) >= MAX_SAMPLES:
        state["status"] = "sample_limit_reached_review_required"
        return
    sample: dict[str, Any] = {"timestamp": now}
    try:
        before = origin_counter()
        offset = len(state["samples"]) % len(items)
        sample["reads"] = run_reads(items[offset:] + items[:offset], secret, 1)
        sample["resources"] = resource_sample(now, state.get("lifecycle_fixture_id"))
        sample["origin_connections"] = origin_counter()
        if before != state["baseline_origin_connections"] or sample["origin_connections"] != before:
            issue("origin_counter_changed_or_reset")
        if sample["reads"]["errors"]:
            issue("read_failures")
        if sample["resources"]["monitor"]["alerts"]:
            issue("monitor_alerts")
        resources = sample["resources"]
        if any(float(row["MemPerc"].removesuffix("%")) >= 90 for row in resources["containers"]):
            issue("container_memory_high")
        if resources["capabilities"].get("asset_store_active_capabilities", 0) > 1000:
            issue("capability_bound_exceeded")
        if state["samples"] and "resources" in state["samples"][0]:
            baseline = state["samples"][0]["resources"]
            if {row["Name"]: row["ID"] for row in baseline["containers"]} != {
                row["Name"]: row["ID"] for row in resources["containers"]
            }:
                issue("container_recreated")
            for key in ("assets", "aliases", "retained_payload_bytes"):
                expected = baseline["database"][key]
                if key == "retained_payload_bytes" and "lifecycle_fixture" in resources:
                    fixture = resources["lifecycle_fixture"]
                    if not fixture["physical_exists"]:
                        expected -= fixture["size_bytes"]
                if resources["database"][key] != expected:
                    issue("registered_content_changed")
                    break
    except (OSError, ValueError, KeyError, httpx.HTTPError, subprocess.SubprocessError):
        issue("observation_unavailable")
        sample["error"] = "observation_unavailable"
    state["samples"].append(sample)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("start", "tick"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--fixture-id", help="Dedicated tmp expiry/reclamation fixture")
    parser.add_argument(
        "--corpus", type=Path, default=Path(__file__).with_name("pilot-corpus.json")
    )
    parser.add_argument(
        "--credentials", type=Path, default=ROOT / "deploy/pilot/private/fetcher.env"
    )
    args = parser.parse_args()
    try:
        if args.state.parent.stat().st_mode & 0o077:
            raise ValueError("state directory must be private")
        descriptor = os.open(str(args.state) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(descriptor, "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return 0
            corpus = load_corpus(args.corpus)
            digest = hashlib.sha256(args.corpus.read_bytes()).hexdigest()
            secret = read_credential(args.credentials)
            if args.mode == "start":
                if args.state.exists():
                    raise ValueError("refuse to overwrite an existing rehearsal")
                before = origin_counter()
                burst = run_reads(corpus, secret, 20)
                burst_failed = bool(burst["errors"]) or origin_counter() != before
                now = time.time()
                state: dict[str, Any] = {
                    "event": "pilot.acceptance",
                    "status": "burst_failed_review_required" if burst_failed else "running",
                    "started_at": now,
                    "deadline": now + DURATION,
                    "duration_seconds": DURATION,
                    "corpus_sha256": digest,
                    "url_count": len(corpus),
                    "unique_resource_count": len(
                        {GallicaPolicy().require(i["url"]).fetch_url for i in corpus}
                    ),
                    "burst": burst,
                    "baseline_origin_connections": before,
                    "lifecycle_fixture_id": args.fixture_id,
                    "samples": [],
                    "issues": [],
                    "issue_count": 0,
                }
                tick(state, corpus, secret, now)
            else:
                state = json.loads(args.state.read_text())
                if state["corpus_sha256"] != digest:
                    raise ValueError("corpus changed")
                tick(state, corpus, secret, time.time())
            atomic_write(args.state, state)
            print(
                json.dumps(
                    {
                        "event": "pilot.acceptance",
                        "status": state["status"],
                        "samples": len(state["samples"]),
                        "issues": state["issue_count"],
                    }
                )
            )
            return int(state["status"] == "burst_failed_review_required")
    except (
        OSError,
        ValueError,
        KeyError,
        PilotDeniedError,
        httpx.HTTPError,
        subprocess.SubprocessError,
    ):
        print('{"event":"pilot.acceptance","error":"configuration_or_observation_failed"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
