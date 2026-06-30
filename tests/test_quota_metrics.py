"""Bucket fill-ratio gauge + warn-log tests (FR-068, ADR-009)."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from asset_store_core.api import create_app


class BucketFillMetricTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def _set_bucket_quota(self, *, quota_bytes: int, warn_threshold: float) -> None:
        response = self.client.put(
            "/quotas/bucket",
            json={
                "space": "cache",
                "quota_bytes": quota_bytes,
                "warn_threshold": warn_threshold,
            },
        )
        self.assertEqual(200, response.status_code, response.text)

    def _commit(self, alias_name: str, size: int) -> None:
        reserve = self.client.post(
            "/assets",
            json={
                "space": "cache",
                "partition_id": "gallica",
                "aliases": [{"name": alias_name}],
                "owner_service_id": "bulk-loader",
            },
        )
        self.assertEqual(201, reserve.status_code, reserve.text)
        asset_id = reserve.json()["asset_id"]
        commit = self.client.post(
            f"/assets/{asset_id}/commit",
            json={"size_bytes": size, "checksum": "sha256:abc", "caller_service_id": "bulk-loader"},
        )
        self.assertEqual(200, commit.status_code, commit.text)

    def _fill_ratio(self) -> float | None:
        body = self.client.get("/metrics").text
        for line in body.splitlines():
            if line.startswith("asset_store_bucket_fill_ratio{") and 'space="cache"' in line:
                return float(line.rsplit(" ", 1)[1])
        return None

    def test_gauge_reflects_fill_ratio_after_commit(self) -> None:
        self._set_bucket_quota(quota_bytes=100, warn_threshold=0.9)
        self._commit("a.png", 60)
        self.assertAlmostEqual(0.6, self._fill_ratio() or 0.0, places=6)

    def test_no_gauge_series_without_a_configured_quota(self) -> None:
        # Default bucket quota has quota_bytes=None, so no ratio is meaningful.
        self._commit("a.png", 60)
        self.assertIsNone(self._fill_ratio())
        self.assertNotIn("asset_store_bucket_fill_ratio{", self.client.get("/metrics").text)

    def test_warning_logged_when_crossing_threshold(self) -> None:
        self._set_bucket_quota(quota_bytes=100, warn_threshold=0.5)
        with self.assertLogs("asset_store", level="WARNING") as captured:
            self._commit("a.png", 60)
        self.assertTrue(
            any("of quota" in message for message in captured.output),
            captured.output,
        )

    def test_no_warning_below_threshold(self) -> None:
        self._set_bucket_quota(quota_bytes=100, warn_threshold=0.9)
        # assertLogs fails if nothing is logged at the level, so log a sentinel
        # and assert the quota warning is absent from the captured records.
        import logging

        with self.assertLogs("asset_store", level="WARNING") as captured:
            logging.getLogger("asset_store").warning("sentinel")
            self._commit("a.png", 60)
        self.assertFalse(any("of quota" in message for message in captured.output))


if __name__ == "__main__":
    unittest.main()
