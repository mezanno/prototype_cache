"""Contract tests for the capability-guarded data plane (FR-010..015, ADR-003)."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from asset_store_core.api import create_app
from asset_store_core.capabilities import Capability, Operation

PROBLEM = "application/problem+json"


class DataPlaneTest(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app()
        self.client = TestClient(self.app)

    def _mint(
        self,
        *,
        operation: str,
        scope: str,
        service: str,
        single_use: bool = False,
        ttl: int = 300,
    ) -> str:
        response = self.client.post(
            "/capabilities",
            json={
                "operation": operation,
                "scope_prefix": scope,
                "caller_service_id": service,
                "ttl_seconds": ttl,
                "single_use": single_use,
            },
        )
        self.assertEqual(201, response.status_code)
        return str(response.json()["capability_id"])

    @staticmethod
    def _auth(capability_id: str) -> dict[str, str]:
        return {"Authorization": f"Capability {capability_id}"}

    def _write_file(self, alias: str, data: bytes, service: str = "upload-api") -> None:
        scope = alias.rsplit("/", 1)[0]
        write_cap = self._mint(operation="write", scope=scope, service=service)
        response = self.client.put(f"/objects/{alias}", content=data, headers=self._auth(write_cap))
        self.assertEqual(201, response.status_code, response.text)

    def test_write_then_read_round_trip(self) -> None:
        alias = "users/42/uploads/a.txt"
        payload = b"hello world"

        write_cap = self._mint(operation="write", scope="users/42/uploads", service="upload-api")
        written = self.client.put(
            f"/objects/{alias}", content=payload, headers=self._auth(write_cap)
        )
        self.assertEqual(201, written.status_code, written.text)
        body = written.json()
        self.assertEqual("available", body["state"])
        self.assertIn(alias, body["aliases"])
        self.assertIsNotNone(body["checksum"])

        read_cap = self._mint(operation="read", scope="users/42/uploads", service="upload-api")
        read = self.client.get(f"/objects/{alias}", headers=self._auth(read_cap))
        self.assertEqual(200, read.status_code)
        self.assertEqual(payload, read.content)

    def test_missing_credential_is_denied(self) -> None:
        response = self.client.get("/objects/users/42/uploads/a.txt")
        self.assertEqual(403, response.status_code)
        self.assertTrue(response.headers["content-type"].startswith(PROBLEM))
        self.assertEqual("CapabilityDeniedError", response.json()["title"])

    def test_unknown_credential_is_denied(self) -> None:
        response = self.client.get(
            "/objects/users/42/uploads/a.txt", headers=self._auth("cap-nope")
        )
        self.assertEqual(403, response.status_code)
        self.assertEqual("CapabilityDeniedError", response.json()["title"])

    def test_scope_mismatch_is_denied(self) -> None:
        write_cap = self._mint(operation="write", scope="users/42/uploads", service="upload-api")
        response = self.client.put(
            "/objects/users/42/other/a.txt", content=b"x", headers=self._auth(write_cap)
        )
        self.assertEqual(403, response.status_code)
        self.assertEqual("CapabilityDeniedError", response.json()["title"])

    def test_operation_mismatch_is_denied(self) -> None:
        read_cap = self._mint(operation="read", scope="users/42/uploads", service="upload-api")
        response = self.client.put(
            "/objects/users/42/uploads/a.txt", content=b"x", headers=self._auth(read_cap)
        )
        self.assertEqual(403, response.status_code)
        self.assertEqual("CapabilityDeniedError", response.json()["title"])

    def test_single_use_read_is_consumed_after_success(self) -> None:
        alias = "users/42/uploads/a.txt"
        self._write_file(alias, b"once")

        read_cap = self._mint(
            operation="read", scope="users/42/uploads", service="upload-api", single_use=True
        )
        first = self.client.get(f"/objects/{alias}", headers=self._auth(read_cap))
        self.assertEqual(200, first.status_code)

        second = self.client.get(f"/objects/{alias}", headers=self._auth(read_cap))
        self.assertEqual(403, second.status_code)
        self.assertEqual("CapabilityAlreadyConsumedError", second.json()["title"])

    def test_expired_capability_is_denied(self) -> None:
        expired = Capability(
            capability_id="cap-expired",
            operation=Operation.READ,
            scope_prefix="users/42/uploads",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
            caller_service_id="upload-api",
        )
        self.app.state.capabilities["cap-expired"] = expired

        response = self.client.get(
            "/objects/users/42/uploads/a.txt", headers=self._auth("cap-expired")
        )
        self.assertEqual(403, response.status_code)
        self.assertEqual("CapabilityDeniedError", response.json()["title"])


if __name__ == "__main__":
    unittest.main()
