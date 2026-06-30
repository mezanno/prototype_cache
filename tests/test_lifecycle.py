"""Contract tests for the lifecycle HTTP endpoints (FR-003/FR-005..008)."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from asset_store_core.api import create_app


class LifecycleEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def _reserve(self, alias_name: str, *, mutable: bool = False) -> str:
        response = self.client.post(
            "/assets",
            json={
                "space": "cache",
                "partition_id": "gallica",
                "aliases": [{"name": alias_name, "mutable": mutable}],
                "owner_service_id": "bulk-loader",
            },
        )
        self.assertEqual(201, response.status_code)
        return str(response.json()["asset_id"])

    def _commit(self, asset_id: str) -> None:
        response = self.client.post(
            f"/assets/{asset_id}/commit",
            json={
                "size_bytes": 3,
                "checksum": "sha256:abc",
                "caller_service_id": "bulk-loader",
            },
        )
        self.assertEqual(200, response.status_code)

    def _available(self, alias_name: str, *, mutable: bool = False) -> str:
        asset_id = self._reserve(alias_name, mutable=mutable)
        self._commit(asset_id)
        return asset_id

    def test_expire_transitions_to_expired(self) -> None:
        asset_id = self._available("img.png")

        response = self.client.post(
            f"/assets/{asset_id}/expire", json={"caller_service_id": "admin"}
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("expired", response.json()["state"])
        actions = [event["action"] for event in self.client.get("/audit").json()]
        self.assertIn("asset.expire", actions)

    def test_expire_from_pending_is_conflict(self) -> None:
        asset_id = self._reserve("img.png")

        response = self.client.post(
            f"/assets/{asset_id}/expire", json={"caller_service_id": "admin"}
        )

        self.assertEqual(409, response.status_code)
        self.assertEqual("application/problem+json", response.headers["content-type"])

    def test_delete_transitions_to_deleted(self) -> None:
        asset_id = self._available("img.png")

        response = self.client.post(
            f"/assets/{asset_id}/delete", json={"caller_service_id": "admin"}
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("deleted", response.json()["state"])

    def test_update_annotations_merges_by_default(self) -> None:
        asset_id = self._reserve("img.png")

        response = self.client.patch(
            f"/assets/{asset_id}/annotations",
            json={"patch": {"source": "gallica"}, "caller_service_id": "admin"},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual({"source": "gallica"}, response.json()["annotations"])

    def test_detach_immutable_alias_unbinds(self) -> None:
        self._available("img.png")

        response = self.client.post(
            "/aliases/detach",
            json={"space": "cache", "alias": "gallica/img.png", "caller_service_id": "admin"},
        )

        self.assertEqual(204, response.status_code)
        resolved = self.client.get(
            "/resolve", params={"space": "cache", "alias": "gallica/img.png"}
        )
        self.assertEqual(404, resolved.status_code)
        actions = [event["action"] for event in self.client.get("/audit").json()]
        self.assertIn("alias.detach", actions)

    def test_detach_mutable_then_rebind(self) -> None:
        self._available("ver.png", mutable=True)
        new_asset_id = self._available("ver-v2.png")

        detached = self.client.post(
            "/aliases/detach-mutable",
            json={"space": "cache", "alias": "gallica/ver.png", "caller_service_id": "admin"},
        )
        self.assertEqual(200, detached.status_code)
        self.assertIsNone(detached.json()["asset_id"])

        rebound = self.client.post(
            "/aliases/rebind",
            json={
                "space": "cache",
                "alias": "gallica/ver.png",
                "new_asset_id": new_asset_id,
                "caller_service_id": "admin",
            },
        )
        self.assertEqual(200, rebound.status_code)
        self.assertEqual(new_asset_id, rebound.json()["asset_id"])

        resolved = self.client.get(
            "/resolve", params={"space": "cache", "alias": "gallica/ver.png"}
        )
        self.assertEqual(200, resolved.status_code)
        self.assertEqual(new_asset_id, resolved.json()["asset_id"])

    def test_detach_immutable_via_mutable_endpoint_is_conflict(self) -> None:
        self._available("img.png")

        response = self.client.post(
            "/aliases/detach-mutable",
            json={"space": "cache", "alias": "gallica/img.png", "caller_service_id": "admin"},
        )

        self.assertEqual(409, response.status_code)
        self.assertEqual("application/problem+json", response.headers["content-type"])


if __name__ == "__main__":
    unittest.main()
