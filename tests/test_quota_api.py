"""HTTP contract tests for the quota and eviction-policy endpoints (FR-063/FR-066/FR-068)."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient
from httpx import Response

from asset_store_core.api import create_app


class QuotaEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def _reserve(self, alias_name: str, *, eviction_policy: str | None = None) -> str:
        body: dict[str, object] = {
            "space": "cache",
            "partition_id": "gallica",
            "aliases": [{"name": alias_name}],
            "owner_service_id": "bulk-loader",
        }
        if eviction_policy is not None:
            body["eviction_policy"] = eviction_policy
        response = self.client.post("/assets", json=body)
        self.assertEqual(201, response.status_code)
        return str(response.json()["asset_id"])

    def _commit(self, asset_id: str, size: int) -> Response:
        response: Response = self.client.post(
            f"/assets/{asset_id}/commit",
            json={"size_bytes": size, "checksum": "sha256:abc", "caller_service_id": "bulk-loader"},
        )
        return response

    def test_reserve_defaults_to_inherit(self) -> None:
        asset_id = self._reserve("a.png")
        commit = self._commit(asset_id, 1)
        self.assertEqual("inherit", commit.json()["eviction_policy"])

    def test_reserve_with_exempt_policy(self) -> None:
        asset_id = self._reserve("a.png", eviction_policy="exempt")
        commit = self._commit(asset_id, 1)
        self.assertEqual("exempt", commit.json()["eviction_policy"])

    def test_patch_eviction_policy(self) -> None:
        asset_id = self._reserve("a.png")

        response = self.client.patch(
            f"/assets/{asset_id}/eviction-policy",
            json={"eviction_policy": "exempt", "caller_service_id": "admin"},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("exempt", response.json()["eviction_policy"])
        actions = [event["action"] for event in self.client.get("/audit").json()]
        self.assertIn("asset.eviction_policy_set", actions)

    def test_default_partition_quota_reports_sweep_flag(self) -> None:
        response = self.client.get(
            "/quotas/partition", params={"space": "cache", "partition_id": "gallica"}
        )
        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertTrue(body["eviction_sweep_enabled"])
        self.assertEqual(0, body["used_bytes"])

    def test_set_and_get_partition_quota(self) -> None:
        put = self.client.put(
            "/quotas/partition",
            json={"space": "cache", "partition_id": "gallica", "quota_bytes": 500},
        )
        self.assertEqual(200, put.status_code)

        self._commit(self._reserve("a.png"), 30)
        got = self.client.get(
            "/quotas/partition", params={"space": "cache", "partition_id": "gallica"}
        ).json()
        self.assertEqual(500, got["quota_bytes"])
        self.assertEqual(30, got["used_bytes"])

    def test_commit_over_partition_quota_returns_413(self) -> None:
        self.client.put(
            "/quotas/partition",
            json={"space": "cache", "partition_id": "gallica", "quota_bytes": 50},
        )
        response = self._commit(self._reserve("a.png"), 60)

        self.assertEqual(413, response.status_code)
        self.assertEqual("application/problem+json", response.headers["content-type"])
        self.assertEqual("partition", response.json()["scope"])

    def test_commit_over_bucket_quota_returns_413(self) -> None:
        self.client.put("/quotas/bucket", json={"space": "cache", "quota_bytes": 100})
        response = self._commit(self._reserve("a.png"), 100)

        self.assertEqual(413, response.status_code)
        self.assertEqual("bucket", response.json()["scope"])

    def test_bucket_quota_roundtrip(self) -> None:
        self.client.put("/quotas/bucket", json={"space": "cache", "quota_bytes": 1000})
        self._commit(self._reserve("a.png"), 40)
        got = self.client.get("/quotas/bucket", params={"space": "cache"}).json()
        self.assertEqual(1000, got["quota_bytes"])
        self.assertEqual(40, got["used_bytes"])


if __name__ == "__main__":
    unittest.main()
