"""B-015/B-019, NFR-002/004/005: paced 15-minute cache-only acceptance."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import subprocess
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
import pilot_acceptance as pilot

DURATION = 900
ROUNDS = 1440
INTERVAL = DURATION / ROUNDS


def paced_client(
    index: int,
    items: list[dict[str, Any]],
    secret: str,
    started: float,
    stop: threading.Event,
) -> dict[str, Any]:
    """Never overlap reads per client or catch up missed slots after backpressure."""
    rows: list[dict[str, Any]] = []
    skipped = 0
    with httpx.Client(
        base_url=pilot.BASE,
        trust_env=False,
        follow_redirects=False,
        timeout=15,
        headers={"Authorization": "Service task-api:" + secret},
    ) as http:
        slot = 0
        while slot < ROUNDS and not stop.is_set():
            now = time.monotonic()
            if now >= started + DURATION:
                break
            due = started + slot * INTERVAL
            if now < due:
                stop.wait(min(due - now, 0.25))
                continue
            current = min(ROUNDS - 1, int((now - started) / INTERVAL))
            if current > slot:
                skipped += current - slot
                slot = current
            result = pilot.verified_read(http, items[(index + slot) % len(items)])
            rows.append({"slot": slot, "elapsed_seconds": now - started, **result})
            slot += 1
    return {
        "client": index,
        "reads": rows,
        "skipped_slots": skipped,
        "unstarted_slots": ROUNDS - len(rows) - skipped,
    }


def summary(clients: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate all outcomes, retaining overloads and whole-run successful p95."""
    rows = [row for client in clients for row in client["reads"]]
    latency = sorted(row["elapsed_ms"] for row in rows if row["ok"])
    return {
        "planned_reads": 3 * ROUNDS,
        "attempted_reads": len(rows),
        "successful_reads": len(latency),
        "skipped_slots": sum(client["skipped_slots"] for client in clients),
        "unstarted_slots": sum(client["unstarted_slots"] for client in clients),
        "bytes": sum(row.get("bytes", 0) for row in rows),
        "http_attempt_statuses": dict(Counter(str(s) for row in rows for s in row["attempts"])),
        "errors": dict(Counter(row["error"] for row in rows if not row["ok"])),
        "p95_ms_with_retries": latency[(len(latency) * 95 + 99) // 100 - 1] if latency else None,
        "max_ms_with_retries": max(latency) if latency else None,
    }


def run(path: Path, items: list[dict[str, Any]], secret: str, digest: str) -> int:
    """Keep private checkpoints, bounded resources and explicit interruption evidence."""
    if path.exists() or path.is_symlink():
        raise ValueError("refuse to overwrite evidence")
    state: dict[str, Any] = {
        "event": "pilot.accelerated_acceptance",
        "status": "running",
        "duration_seconds": DURATION,
        "rounds_per_client": ROUNDS,
        "interval_seconds": INTERVAL,
        "corpus_sha256": digest,
        "started_at": time.time(),
        "samples": [],
        "issues": [],
    }
    stop = threading.Event()
    baseline = pilot.origin_counter()
    state["baseline_origin_connections"] = baseline
    pilot.atomic_write(path, state)
    started = time.monotonic()
    interrupted = False
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(paced_client, i, items, secret, started, stop) for i in range(3)]
        next_sample = started
        try:
            while time.monotonic() < started + DURATION:
                if time.monotonic() >= next_sample:
                    sample: dict[str, Any] = {"timestamp": time.time()}
                    try:
                        sample["resources"] = pilot.resource_sample(sample["timestamp"])
                        sample["origin_connections"] = pilot.origin_counter()
                        if sample["origin_connections"] != baseline:
                            state["issues"].append("origin_counter_changed_or_reset")
                        if sample["resources"]["monitor"]["alerts"]:
                            state["issues"].append("monitor_alerts")
                    except (
                        OSError,
                        ValueError,
                        KeyError,
                        httpx.HTTPError,
                        subprocess.SubprocessError,
                    ):
                        sample["error"] = "observation_unavailable"
                        state["issues"].append("observation_unavailable")
                    state["samples"].append(sample)
                    pilot.atomic_write(path, state)
                    next_sample = time.monotonic() + 60
                stop.wait(0.25)
        except KeyboardInterrupt:
            interrupted = True
        finally:
            stop.set()
        clients = []
        for future in futures:
            try:
                clients.append(future.result())
            except (OSError, ValueError, httpx.HTTPError):
                state["issues"].append("client_unavailable")
    state["clients"] = clients
    state["summary"] = summary(clients)
    state["finished_at"] = time.time()
    state["elapsed_seconds"] = time.monotonic() - started
    state["status"] = (
        "interrupted_review_required" if interrupted else "observations_complete_review_required"
    )
    try:
        state["final_resources"] = pilot.resource_sample(time.time())
        state["final_origin_connections"] = pilot.origin_counter()
        if state["final_origin_connections"] != baseline:
            state["issues"].append("origin_counter_changed_or_reset")
    except (OSError, ValueError, KeyError, httpx.HTTPError, subprocess.SubprocessError):
        state["issues"].append("final_observation_unavailable")
    pilot.atomic_write(path, state)
    print(
        json.dumps(
            {
                "event": state["event"],
                "status": state["status"],
                "summary": state["summary"],
                "issues": state["issues"],
            }
        )
    )
    return int(
        interrupted
        or bool(state["issues"])
        or bool(state["summary"]["errors"])
        or len(clients) != 3
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.state.parent.stat().st_mode & 0o077:
            raise ValueError("state directory must be private")
        with open(str(args.state) + ".lock", "a") as lock:
            lock_path = Path(lock.name)
            lock_path.chmod(0o600)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            corpus_path = Path(__file__).with_name("pilot-corpus.json")
            items = pilot.load_corpus(corpus_path)
            secret = pilot.read_credential(pilot.ROOT / "deploy/pilot/private/fetcher.env")
            return run(
                args.state, items, secret, hashlib.sha256(corpus_path.read_bytes()).hexdigest()
            )
    except (OSError, ValueError, KeyError, httpx.HTTPError, subprocess.SubprocessError):
        print(
            '{"event":"pilot.accelerated_acceptance","error":"configuration_or_observation_failed"}'
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
