"""bulk-loader CLI — SCN-001 bulk preload into the ``cache`` bucket (B-011).

The loader authenticates as the ``bulk-loader`` service (``Authorization:
Service <id>:<secret>``, FR-014), mints a single **write** capability scoped to
``cache/{mirror_id}`` (the capability model requires a bucket plus at least one
segment, so a bare-bucket ``cache/`` scope is not representable; the per-mirror
scope still covers every row of a run and FR-015 confines this service to
``cache``), then streams each manifest row through the guarded data plane
(``PUT /objects/{alias}``), which performs reserve -> PUT -> commit server-side
(FR-004/FR-020/FR-022).

Batch semantics are **best-effort per row** (Q-001): good rows commit and become
resolvable immediately; failed rows are collected into a report and cause a
non-zero exit. ``--fail-fast`` stops on the first failure (leaving earlier rows
committed) for interactive manifest debugging.

The alias is the stable citation name ``cache/{mirror_id}/{row-alias}`` with no
per-run identifier in the path, so re-running a manifest resolves to the same
aliases (idempotent from the caller's view) and only re-creates missing rows.
"""

from __future__ import annotations

import csv
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import click
import httpx

DEFAULT_BASE_URL = "http://localhost:8080"
DEFAULT_SERVICE_ID = "bulk-loader"
CACHE_BUCKET = "cache"
# SCN-001 mints a 1 h write capability.
CAPABILITY_TTL_SECONDS = 3600
DEFAULT_MAX_RETRIES = 2
MANIFEST_COLUMNS = ("alias", "mime", "path")


class BulkLoadError(Exception):
    """Fatal error that aborts the whole run (auth, capability mint, bad manifest)."""


@dataclass(frozen=True)
class ManifestRow:
    """One manifest entry: a relative alias, its MIME type, and a local file path."""

    alias: str
    mime: str
    path: str


@dataclass
class RowResult:
    """Outcome of a single row upload."""

    row: ManifestRow
    ok: bool
    error: str | None = None
    size_bytes: int = 0


@dataclass
class BulkLoadReport:
    """Aggregate summary of a bulk-load run."""

    results: list[RowResult] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    @property
    def ok(self) -> list[RowResult]:
        return [r for r in self.results if r.ok]

    @property
    def failed(self) -> list[RowResult]:
        return [r for r in self.results if not r.ok]

    @property
    def total_bytes(self) -> int:
        return sum(r.size_bytes for r in self.results if r.ok)

    @property
    def any_failed(self) -> bool:
        return any(not r.ok for r in self.results)


def read_manifest(manifest_path: Path) -> list[ManifestRow]:
    """Parse a CSV manifest with an ``alias,mime,path`` header.

    Raises :class:`BulkLoadError` if the file is missing or the header is wrong.
    """

    try:
        text = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BulkLoadError(f"cannot read manifest {manifest_path}: {exc}") from exc

    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        raise BulkLoadError("manifest is empty")
    missing = [c for c in MANIFEST_COLUMNS if c not in reader.fieldnames]
    if missing:
        raise BulkLoadError(
            f"manifest missing required column(s): {', '.join(missing)} "
            f"(expected header: {','.join(MANIFEST_COLUMNS)})"
        )

    rows: list[ManifestRow] = []
    for lineno, raw in enumerate(reader, start=2):
        alias = (raw.get("alias") or "").strip().strip("/")
        mime = (raw.get("mime") or "").strip()
        path = (raw.get("path") or "").strip()
        if not alias or not path:
            raise BulkLoadError(f"manifest line {lineno}: 'alias' and 'path' are required")
        rows.append(ManifestRow(alias=alias, mime=mime, path=path))
    return rows


def qualified_alias(mirror_id: str, row_alias: str) -> str:
    """Build the stable qualified alias ``cache/{mirror_id}/{row_alias}``."""

    return f"{CACHE_BUCKET}/{mirror_id.strip().strip('/')}/{row_alias.strip().strip('/')}"


def mint_write_capability(
    client: httpx.Client,
    *,
    service_id: str,
    service_secret: str,
    scope_prefix: str,
) -> str:
    """Mint a 1 h write capability scoped to ``scope_prefix`` (``cache/{mirror_id}``).

    The capability model requires a bucket plus at least one segment, so the
    loader scopes per mirror (``cache/{mirror_id}``) rather than the bare bucket;
    this still covers every row of a run and is tighter than a bucket-wide grant.
    Raises :class:`BulkLoadError` on an auth or policy failure (fatal for the run).
    """

    response = client.post(
        "/capabilities",
        headers={"Authorization": f"Service {service_id}:{service_secret}"},
        json={
            "operation": "write",
            "scope_prefix": scope_prefix,
            "ttl_seconds": CAPABILITY_TTL_SECONDS,
            "single_use": False,
        },
    )
    if response.status_code != 201:
        raise BulkLoadError(f"capability mint failed ({response.status_code}): {response.text}")
    capability_id: str = response.json()["capability_id"]
    return capability_id


def upload_row(
    client: httpx.Client,
    *,
    capability_id: str,
    mirror_id: str,
    row: ManifestRow,
    base_dir: Path,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> RowResult:
    """Upload one manifest row through ``PUT /objects/{alias}`` (reserve->PUT->commit).

    Retries transient transport/5xx errors up to ``max_retries`` times before
    marking the row failed. Never raises: a failure is returned as a
    :class:`RowResult` so the caller can continue (best-effort per row).
    """

    file_path = row.path if Path(row.path).is_absolute() else str(base_dir / row.path)
    try:
        data = Path(file_path).read_bytes()
    except OSError as exc:
        return RowResult(row=row, ok=False, error=f"cannot read file: {exc}")

    alias = qualified_alias(mirror_id, row.alias)
    headers = {"Authorization": f"Capability {capability_id}"}
    if row.mime:
        headers["Content-Type"] = row.mime

    last_error = "unknown error"
    for attempt in range(max_retries + 1):
        try:
            response = client.put(f"/objects/{alias}", content=data, headers=headers)
        except httpx.HTTPError as exc:
            last_error = f"transport error: {exc}"
        else:
            if response.status_code == 201:
                committed: int = response.json().get("size_bytes") or len(data)
                return RowResult(row=row, ok=True, size_bytes=committed)
            last_error = f"HTTP {response.status_code}: {response.text}"
            # 4xx (scope/allowlist/validation) will not succeed on retry.
            if response.status_code < 500:
                break
        if attempt < max_retries:
            time.sleep(0.1 * (attempt + 1))
    return RowResult(row=row, ok=False, error=last_error)


def run_bulk_load(
    client: httpx.Client,
    *,
    mirror_id: str,
    rows: list[ManifestRow],
    service_id: str,
    service_secret: str,
    base_dir: Path,
    fail_fast: bool = False,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> BulkLoadReport:
    """Run the full SCN-001 flow: mint one capability, then upload every row.

    Best-effort per row: a failing row is recorded and (unless ``fail_fast``)
    the run continues. Raises :class:`BulkLoadError` only for fatal, whole-run
    failures (capability mint).
    """

    capability_id = mint_write_capability(
        client,
        service_id=service_id,
        service_secret=service_secret,
        scope_prefix=f"{CACHE_BUCKET}/{mirror_id.strip().strip('/')}",
    )
    report = BulkLoadReport()
    started = time.monotonic()
    for row in rows:
        result = upload_row(
            client,
            capability_id=capability_id,
            mirror_id=mirror_id,
            row=row,
            base_dir=base_dir,
            max_retries=max_retries,
        )
        report.results.append(result)
        if not result.ok and fail_fast:
            break
    report.elapsed_seconds = time.monotonic() - started
    return report


def write_failure_report(report: BulkLoadReport, report_path: Path) -> None:
    """Write failed rows to a CSV (``alias,path,error``) for retrying."""

    with report_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("alias", "path", "error"))
        for result in report.failed:
            writer.writerow((result.row.alias, result.row.path, result.error or ""))


@click.command()
@click.option(
    "--manifest",
    "manifest",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="CSV manifest with an 'alias,mime,path' header.",
)
@click.option("--mirror-id", required=True, help="Partition id under cache/ (e.g. gallica).")
@click.option(
    "--base-url", default=DEFAULT_BASE_URL, show_default=True, help="asset-store base URL."
)
@click.option(
    "--service-id",
    default=DEFAULT_SERVICE_ID,
    show_default=True,
    help="Service identity used to mint the write capability.",
)
@click.option(
    "--service-secret",
    envvar="BULK_LOADER_SERVICE_SECRET",
    required=True,
    help="Service secret (or env BULK_LOADER_SERVICE_SECRET).",
)
@click.option("--batch-id", default=None, help="Run/correlation label (not part of any alias).")
@click.option("--fail-fast", is_flag=True, help="Stop at the first failing row.")
@click.option(
    "--report",
    "report_path",
    default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write failed rows (alias,path,error) to this CSV.",
)
@click.option(
    "--max-retries",
    default=DEFAULT_MAX_RETRIES,
    show_default=True,
    help="Retries per row for transient (5xx/transport) errors.",
)
def main(
    manifest: Path,
    mirror_id: str,
    base_url: str,
    service_id: str,
    service_secret: str,
    batch_id: str | None,
    fail_fast: bool,
    report_path: Path | None,
    max_retries: int,
) -> None:
    """Bulk-preload the assets listed in MANIFEST into cache/{mirror-id}/… (SCN-001)."""

    batch_id = batch_id or uuid.uuid4().hex
    try:
        rows = read_manifest(manifest)
    except BulkLoadError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"bulk-load batch={batch_id} mirror={mirror_id} rows={len(rows)} target={base_url}")
    try:
        with httpx.Client(base_url=base_url, timeout=30.0) as client:
            report = run_bulk_load(
                client,
                mirror_id=mirror_id,
                rows=rows,
                service_id=service_id,
                service_secret=service_secret,
                base_dir=manifest.parent,
                fail_fast=fail_fast,
                max_retries=max_retries,
            )
    except BulkLoadError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(
        f"done: {len(report.ok)} ok, {len(report.failed)} failed, "
        f"{report.total_bytes} bytes, {report.elapsed_seconds:.2f}s"
    )
    for result in report.failed:
        click.echo(f"  FAIL {result.row.alias}: {result.error}", err=True)
    if report_path is not None and report.failed:
        write_failure_report(report, report_path)
        click.echo(f"failure report written to {report_path}", err=True)
    if report.any_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
