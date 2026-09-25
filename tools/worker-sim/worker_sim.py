"""Deterministic SCN-002/005 worker workload (B-012, ADR-019).

Read by alias, verify checksums, copy result artifacts, then publish a manifest.
See docs/services/worker-sim.md for the task contract and failure semantics.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import quote

import click
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from asset_store_core.errors import ValidationError as PathError
from asset_store_core.paths import normalize_bucket, normalize_relative_alias

MAX_INPUT_BYTES = 50 * 1024 * 1024


def _canonical_path(value: str) -> str:
    try:
        normalized = normalize_relative_alias(value)
        normalize_bucket(normalized.split("/", 1)[0])
    except PathError as exc:
        raise ValueError(str(exc)) from exc
    if normalized != value or len(value.split("/")) < 3:
        raise ValueError("expected a normalized bucket/partition/alias path")
    return value


class InputAsset(BaseModel):
    """Trusted task input: qualified alias and SHA-256 (NFR-005)."""

    model_config = ConfigDict(extra="forbid")
    alias: str
    checksum: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @field_validator("alias")
    @classmethod
    def validate_alias(cls, value: str) -> str:
        return _canonical_path(value)


class Task(BaseModel):
    """Dispatch-shaped input, with optional result publication (SCN-002/005)."""

    model_config = ConfigDict(extra="forbid")
    inputs: list[InputAsset] = Field(min_length=1)
    result_prefix: str | None = None

    @field_validator("result_prefix")
    @classmethod
    def validate_result_prefix(cls, value: str | None) -> str | None:
        if value is not None:
            _canonical_path(value)
            if not value.startswith("results/") or len(value.split("/")) != 5:
                raise ValueError("expected results/user/task/attempt/worker")
        return value


class WorkerError(Exception):
    """A sanitized worker error suitable for console output."""


@dataclass
class RunReport:
    """Run counters and timing; emitted even when an operation fails."""

    correlation_id: str
    status: str = "ok"
    reads: int = 0
    writes: int = 0
    bytes_read: int = 0
    bytes_written: int = 0
    read_seconds: float = 0.0
    elapsed_seconds: float = 0.0
    manifest_written: bool = False
    error: str | None = None


def _check(response: httpx.Response, expected: int) -> None:
    if response.status_code != expected:
        # Backend bodies and exception strings can contain credentials or URLs.
        raise WorkerError(f"HTTP {response.status_code}")


def _mint(
    client: httpx.Client, secret: str, operation: str, scope: str, correlation_id: str
) -> str:
    response = client.post(
        "/capabilities",
        headers={"Authorization": f"Service worker:{secret}", "X-Correlation-Id": correlation_id},
        json={
            "operation": operation,
            "scope_prefix": scope,
            "ttl_seconds": 3600,
            "single_use": False,
        },
    )
    _check(response, 201)
    token: str = response.json()["capability_id"]
    return token


def _headers(token: str, correlation_id: str) -> dict[str, str]:
    return {"Authorization": f"Capability {token}", "X-Correlation-Id": correlation_id}


def _put(
    client: httpx.Client, alias: str, data: bytes, mime: str, token: str, correlation_id: str
) -> dict[str, object]:
    checksum = f"sha256:{hashlib.sha256(data).hexdigest()}"
    response = client.put(
        f"/objects/{quote(alias, safe='/')}",
        content=data,
        params={"expected_checksum": checksum},
        headers={**_headers(token, correlation_id), "Content-Type": mime},
    )
    _check(response, 201)
    asset = response.json()
    if asset["checksum"] != checksum or asset["size_bytes"] != len(data):
        raise WorkerError("committed output metadata does not match payload")
    return {
        "alias": alias,
        "asset_id": asset["asset_id"],
        "size_bytes": len(data),
        "checksum": checksum,
    }


def run_task(
    client: httpx.Client,
    task: Task,
    *,
    service_secret: str,
    emit: Callable[[dict[str, object]], None] | None = None,
) -> RunReport:
    """Run SCN-002/005 through capabilities; never publish after a failed artifact.

    Records bounded counters/latencies (FR-050 observability) and propagates one
    correlation id to every service request. No automatic write retries.
    """
    report = RunReport(correlation_id=uuid.uuid4().hex)
    started = time.monotonic()
    stage = "worker.dispatch"

    def event(outcome: str) -> None:
        if emit is not None:
            emit({"event": stage, "outcome": outcome, "correlation_id": report.correlation_id})

    try:
        write_token = None
        if task.result_prefix is not None:
            write_token = _mint(
                client, service_secret, "write", task.result_prefix, report.correlation_id
            )
        outputs: list[dict[str, object]] = []
        for index, item in enumerate(task.inputs, start=1):
            stage = "worker.read"
            token = _mint(client, service_secret, "read", item.alias, report.correlation_id)
            read_started = time.monotonic()
            data = bytearray()
            try:
                with client.stream(
                    "GET",
                    f"/objects/{quote(item.alias, safe='/')}",
                    headers=_headers(token, report.correlation_id),
                ) as response:
                    _check(response, 200)
                    for chunk in response.iter_bytes(chunk_size=64 * 1024):
                        if len(data) + len(chunk) > MAX_INPUT_BYTES:
                            raise WorkerError("input exceeds simulator's 50 MiB limit")
                        data.extend(chunk)
            finally:
                report.read_seconds += time.monotonic() - read_started
            checksum = f"sha256:{hashlib.sha256(data).hexdigest()}"
            if checksum != item.checksum:
                raise WorkerError("input checksum mismatch")
            report.reads += 1
            report.bytes_read += len(data)
            event("success")
            if task.result_prefix is not None and write_token is not None:
                stage = "worker.write"
                output = _put(
                    client,
                    f"{task.result_prefix}/output-{index:04d}.bin",
                    bytes(data),
                    "application/octet-stream",
                    write_token,
                    report.correlation_id,
                )
                output["source_alias"] = item.alias
                outputs.append(output)
                report.writes += 1
                report.bytes_written += len(data)
                event("success")
        if task.result_prefix is not None and write_token is not None:
            stage = "worker.manifest"
            payload = json.dumps({"version": 1, "outputs": outputs}, sort_keys=True).encode()
            _put(
                client,
                f"{task.result_prefix}/manifest.json",
                payload,
                "application/json",
                write_token,
                report.correlation_id,
            )
            report.manifest_written = True
            event("success")
    except (WorkerError, httpx.HTTPError) as exc:
        report.status = "failed"
        report.error = str(exc) if isinstance(exc, WorkerError) else "HTTP transport failure"
        event("failure")
    except (KeyError, ValueError, TypeError):
        report.status = "failed"
        report.error = "invalid asset-store response"
        event("failure")
    finally:
        report.elapsed_seconds = time.monotonic() - started
    return report


@click.command()
@click.option(
    "--task",
    "task_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--base-url", default="http://localhost:8000", show_default=True)
def main(task_path: Path, base_url: str) -> None:
    """Verify input aliases and optionally publish copied results (B-012)."""
    secret = os.environ.get("WORKER_SIM_SERVICE_SECRET")
    if not secret:
        raise click.ClickException("set WORKER_SIM_SERVICE_SECRET")
    try:
        task = Task.model_validate_json(task_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise click.ClickException(
            "invalid or unreadable task JSON; see worker-sim README"
        ) from exc

    def emit(event: dict[str, object]) -> None:
        click.echo(json.dumps(event), err=True)

    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        report = run_task(client, task, service_secret=secret, emit=emit)
    click.echo(json.dumps(asdict(report)))
    if report.status != "ok":
        raise click.exceptions.Exit(1)


if __name__ == "__main__":
    main()
