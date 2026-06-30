"""Contract tests for the audit-log read endpoint (FR-008/FR-016)."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from asset_store_core.api import create_app


class AuditEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def _reserve(self, alias_name: str) -> str:
        response = self.client.post(
            "/assets",
            json={
                "space": "cache",
                "partition_id": "gallica",
                "aliases": [{"name": alias_name}],
                "owner_service_id": "bulk-loader",
            },
        )
        self.assertEqual(201, response.status_code)
        return str(response.json()["asset_id"])

    def test_audit_is_empty_initially(self) -> None:
        response = self.client.get("/audit")
        self.assertEqual(200, response.status_code)
        self.assertEqual([], response.json())

    def test_reserve_and_commit_appear_in_audit(self) -> None:
        asset_id = self._reserve("img.png")
        self.client.post(
            f"/assets/{asset_id}/commit",
            json={"size_bytes": 3, "checksum": "sha256:abc", "caller_service_id": "bulk-loader"},
        )

        events = self.client.get("/audit").json()
        actions = [event["action"] for event in events]
        self.assertIn("alias.create", actions)
        self.assertIn("asset.commit", actions)
        for event in events:
            self.assertIn("ts", event)
            self.assertIn("outcome", event)
            self.assertIn("before", event)
            self.assertIn("after", event)

    def test_filter_by_action(self) -> None:
        self._reserve("a.png")
        self._reserve("b.png")

        events = self.client.get("/audit", params={"action": "alias.create"}).json()
        self.assertTrue(events)
        self.assertTrue(all(event["action"] == "alias.create" for event in events))

    def test_limit_returns_most_recent(self) -> None:
        self._reserve("a.png")
        self._reserve("b.png")

        events = self.client.get("/audit", params={"limit": 1}).json()
        self.assertEqual(1, len(events))

    def test_limit_out_of_range_is_rejected(self) -> None:
        response = self.client.get("/audit", params={"limit": 0})
        self.assertEqual(422, response.status_code)


if __name__ == "__main__":
    unittest.main()
