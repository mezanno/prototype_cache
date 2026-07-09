"""Tests for the bulk-loader CLI (B-011): happy path + partial/failed handling."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from asset_store_core.api import create_app
from asset_store_core.service_identity import dev_secret

# The bulk-loader ships as a standalone tool outside the importable package.
_TOOL_DIR = Path(__file__).resolve().parent.parent / "tools" / "bulk-loader"
if str(_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOL_DIR))

import bulk_loader  # noqa: E402


def _asgi_client() -> httpx.Client:
    # TestClient is a sync httpx.Client that drives the ASGI app in a portal.
    return TestClient(create_app())


def _write_manifest(tmp: Path, rows: list[tuple[str, str, str]]) -> Path:
    lines = ["alias,mime,path"] + [f"{a},{m},{p}" for a, m, p in rows]
    manifest = tmp / "manifest.csv"
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


class ReadManifestTest(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._dir.name)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_parses_rows(self) -> None:
        manifest = _write_manifest(self.tmp, [("a.png", "image/png", "a.png")])
        rows = bulk_loader.read_manifest(manifest)
        self.assertEqual(
            [bulk_loader.ManifestRow(alias="a.png", mime="image/png", path="a.png")], rows
        )

    def test_missing_column_is_fatal(self) -> None:
        manifest = self.tmp / "bad.csv"
        manifest.write_text("alias,path\na.png,a.png\n", encoding="utf-8")
        with self.assertRaises(bulk_loader.BulkLoadError):
            bulk_loader.read_manifest(manifest)

    def test_blank_required_field_is_fatal(self) -> None:
        manifest = _write_manifest(self.tmp, [("", "image/png", "a.png")])
        with self.assertRaises(bulk_loader.BulkLoadError):
            bulk_loader.read_manifest(manifest)


class BulkLoadRunTest(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._dir.name)
        self.client = _asgi_client()
        self.secret = dev_secret("bulk-loader")

    def tearDown(self) -> None:
        self.client.close()
        self._dir.cleanup()

    def _run(
        self, rows: list[bulk_loader.ManifestRow], **kwargs: object
    ) -> bulk_loader.BulkLoadReport:
        return bulk_loader.run_bulk_load(
            self.client,
            mirror_id="gallica",
            rows=rows,
            service_id="bulk-loader",
            service_secret=self.secret,
            base_dir=self.tmp,
            **kwargs,  # type: ignore[arg-type]
        )

    def test_happy_path_all_committed_and_resolvable(self) -> None:
        (self.tmp / "a.png").write_bytes(b"aaa")
        (self.tmp / "b.png").write_bytes(b"bbbb")
        rows = [
            bulk_loader.ManifestRow("img/a.png", "image/png", "a.png"),
            bulk_loader.ManifestRow("img/b.png", "image/png", "b.png"),
        ]
        report = self._run(rows)

        self.assertFalse(report.any_failed)
        self.assertEqual(2, len(report.ok))
        self.assertEqual(7, report.total_bytes)

        resolved = self.client.get(
            "/resolve", params={"space": "cache", "alias": "gallica/img/a.png"}
        )
        self.assertEqual(200, resolved.status_code)
        self.assertEqual("available", resolved.json()["state"])

    def test_missing_file_row_fails_others_commit(self) -> None:
        (self.tmp / "good.png").write_bytes(b"ok")
        rows = [
            bulk_loader.ManifestRow("img/good.png", "image/png", "good.png"),
            bulk_loader.ManifestRow("img/missing.png", "image/png", "missing.png"),
        ]
        report = self._run(rows)

        self.assertTrue(report.any_failed)
        self.assertEqual(1, len(report.ok))
        self.assertEqual(1, len(report.failed))
        self.assertEqual("img/missing.png", report.failed[0].row.alias)
        # The good row is still resolvable despite the sibling failure.
        resolved = self.client.get(
            "/resolve", params={"space": "cache", "alias": "gallica/img/good.png"}
        )
        self.assertEqual(200, resolved.status_code)

    def test_fail_fast_stops_after_first_failure(self) -> None:
        rows = [
            bulk_loader.ManifestRow("img/missing.png", "image/png", "missing.png"),
            bulk_loader.ManifestRow("img/never.png", "image/png", "never.png"),
        ]
        report = self._run(rows, fail_fast=True)

        self.assertEqual(1, len(report.results))
        self.assertEqual(1, len(report.failed))
        self.assertEqual("img/missing.png", report.failed[0].row.alias)

    def test_failure_report_lists_bad_rows(self) -> None:
        (self.tmp / "good.png").write_bytes(b"ok")
        rows = [
            bulk_loader.ManifestRow("img/good.png", "image/png", "good.png"),
            bulk_loader.ManifestRow("img/missing.png", "image/png", "missing.png"),
        ]
        report = self._run(rows)
        report_path = self.tmp / "failures.csv"
        bulk_loader.write_failure_report(report, report_path)

        content = report_path.read_text(encoding="utf-8")
        self.assertIn("alias,path,error", content)
        self.assertIn("img/missing.png", content)
        self.assertNotIn("img/good.png", content)

    def test_wrong_secret_is_fatal(self) -> None:
        (self.tmp / "a.png").write_bytes(b"aaa")
        rows = [bulk_loader.ManifestRow("img/a.png", "image/png", "a.png")]
        with self.assertRaises(bulk_loader.BulkLoadError):
            bulk_loader.run_bulk_load(
                self.client,
                mirror_id="gallica",
                rows=rows,
                service_id="bulk-loader",
                service_secret="wrong-secret",
                base_dir=self.tmp,
            )

    def test_service_without_cache_write_is_denied(self) -> None:
        # upload-api may not write the cache bucket (FR-015) -> mint denied, fatal.
        rows = [bulk_loader.ManifestRow("img/a.png", "image/png", "a.png")]
        with self.assertRaises(bulk_loader.BulkLoadError):
            bulk_loader.run_bulk_load(
                self.client,
                mirror_id="gallica",
                rows=rows,
                service_id="upload-api",
                service_secret=dev_secret("upload-api"),
                base_dir=self.tmp,
            )


if __name__ == "__main__":
    unittest.main()
