"""HTTP contract tests for the asset-store FastAPI app, incl. RFC 7807 errors."""

from __future__ import annotations

import unittest
from typing import Any

from fastapi.testclient import TestClient

from asset_store_core.api import create_app
from asset_store_core.service_identity import dev_secret

PROBLEM = "application/problem+json"


def _service_auth(service_id: str) -> dict[str, str]:
    return {"Authorization": f"Service {service_id}:{dev_secret(service_id)}"}


class ApiContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def _reserve(self, **overrides: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "space": "cache",
            "partition_id": "gallica",
            "aliases": [{"name": "img.png"}],
            "owner_service_id": "bulk-loader",
            "mime": "image/png",
        }
        body.update(overrides)
        response = self.client.post("/assets", json=body)
        self.assertEqual(201, response.status_code)
        data: dict[str, Any] = response.json()
        return data

    def test_health_and_ready(self) -> None:
        self.assertEqual({"status": "ok"}, self.client.get("/healthz").json())
        self.assertEqual({"status": "ready"}, self.client.get("/readyz").json())

    def test_reserve_commit_resolve_round_trip(self) -> None:
        reserved = self._reserve()
        self.assertEqual("pending", reserved["state"])
        self.assertIn("cache/gallica/img.png", reserved["aliases"])

        commit = self.client.post(
            f"/assets/{reserved['asset_id']}/commit",
            json={"size_bytes": 3, "checksum": "sha256:abc", "caller_service_id": "bulk-loader"},
        )
        self.assertEqual(200, commit.status_code)
        self.assertEqual("available", commit.json()["state"])

        resolved = self.client.get(
            "/resolve", params={"space": "cache", "alias": "gallica/img.png"}
        )
        self.assertEqual(200, resolved.status_code)
        self.assertEqual(reserved["asset_id"], resolved.json()["asset_id"])

    def test_resolve_unknown_alias_returns_problem_404(self) -> None:
        response = self.client.get("/resolve", params={"space": "cache", "alias": "nope/x"})
        self.assertEqual(404, response.status_code)
        self.assertTrue(response.headers["content-type"].startswith(PROBLEM))
        body = response.json()
        self.assertEqual(404, body["status"])
        self.assertEqual("AliasNotFoundError", body["title"])
        self.assertTrue(body["type"].startswith("urn:asset-store:error:"))

    def test_duplicate_reserve_returns_problem_409(self) -> None:
        self._reserve()
        response = self.client.post(
            "/assets",
            json={
                "space": "cache",
                "partition_id": "gallica",
                "aliases": [{"name": "img.png"}],
                "owner_service_id": "bulk-loader",
            },
        )
        self.assertEqual(409, response.status_code)
        self.assertEqual("AliasConflictError", response.json()["title"])

    def test_commit_checksum_mismatch_returns_problem_409(self) -> None:
        reserved = self._reserve()
        response = self.client.post(
            f"/assets/{reserved['asset_id']}/commit",
            json={
                "size_bytes": 3,
                "checksum": "sha256:server",
                "caller_service_id": "bulk-loader",
                "expected_checksum": "sha256:client",
            },
        )
        self.assertEqual(409, response.status_code)
        self.assertEqual("ChecksumMismatchError", response.json()["title"])

    def test_mint_capability_success(self) -> None:
        response = self.client.post(
            "/capabilities",
            json={
                "operation": "write",
                "scope_prefix": "users/42/uploads",
                "ttl_seconds": 300,
            },
            headers=_service_auth("upload-api"),
        )
        self.assertEqual(201, response.status_code)
        body = response.json()
        self.assertTrue(body["capability_id"].startswith("cap-"))
        self.assertEqual("write", body["operation"])
        self.assertEqual("upload-api", body["caller_service_id"])
        self.assertIn("expires_at", body)

    def test_mint_capability_requires_service_credential(self) -> None:
        response = self.client.post(
            "/capabilities",
            json={
                "operation": "write",
                "scope_prefix": "users/42/uploads",
                "ttl_seconds": 300,
            },
        )
        self.assertEqual(401, response.status_code)
        self.assertTrue(response.headers["content-type"].startswith(PROBLEM))
        self.assertEqual("ServiceAuthError", response.json()["title"])

    def test_mint_capability_rejects_wrong_secret(self) -> None:
        response = self.client.post(
            "/capabilities",
            json={
                "operation": "write",
                "scope_prefix": "users/42/uploads",
                "ttl_seconds": 300,
            },
            headers={"Authorization": "Service upload-api:wrong-secret"},
        )
        self.assertEqual(401, response.status_code)
        self.assertEqual("ServiceAuthError", response.json()["title"])

    def test_mint_capability_denied_by_service_policy(self) -> None:
        response = self.client.post(
            "/capabilities",
            json={
                "operation": "write",
                "scope_prefix": "users/42/uploads",
                "ttl_seconds": 300,
            },
            headers=_service_auth("worker"),
        )
        self.assertEqual(403, response.status_code)
        self.assertEqual("CapabilityDeniedError", response.json()["title"])

    def test_mint_capability_ttl_too_low_returns_problem_422(self) -> None:
        response = self.client.post(
            "/capabilities",
            json={
                "operation": "read",
                "scope_prefix": "cache/gallica",
                "ttl_seconds": 10,
            },
            headers=_service_auth("worker"),
        )
        self.assertEqual(422, response.status_code)
        self.assertTrue(response.headers["content-type"].startswith(PROBLEM))
        self.assertEqual("RequestValidationError", response.json()["title"])

    def test_capability_issue_is_audited(self) -> None:
        self.client.post(
            "/capabilities",
            json={"operation": "write", "scope_prefix": "users/42/uploads", "ttl_seconds": 300},
            headers=_service_auth("upload-api"),
        )
        self.client.post(
            "/capabilities",
            json={"operation": "write", "scope_prefix": "users/42/uploads", "ttl_seconds": 300},
            headers=_service_auth("worker"),
        )
        events = self.client.get("/audit", params={"action": "capability.issue"}).json()
        outcomes = {(e["caller_service_id"], e["outcome"]) for e in events}
        self.assertIn(("upload-api", "granted"), outcomes)
        self.assertIn(("worker", "denied"), outcomes)
        granted = next(e for e in events if e["outcome"] == "granted")
        self.assertEqual("users/42/uploads", granted["target"])
        self.assertEqual("write", granted["after"]["operation"])
        self.assertIn("capability_id", granted["after"])


if __name__ == "__main__":
    unittest.main()
