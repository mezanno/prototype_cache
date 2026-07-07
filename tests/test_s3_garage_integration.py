"""Garage backend certification tests (S-001 / S-004, ADR-001/ADR-011).

These exercise the real S3 data path against a running Garage instance and are
**skipped unless** Garage is reachable and its credentials are exported. Bring it
up first:

    cd deploy/compose
    docker compose -f docker-compose.garage.yml up -d
    ./garage-init.sh
    set -a && source .env.garage && set +a

Then run: ``uv run pytest tests/test_s3_garage_integration.py -q``.

The default ``uv run pytest`` run skips this module when the env vars are absent,
so unit CI stays Docker-free.
"""

from __future__ import annotations

import os
import unittest
import urllib.request
import uuid

from fastapi.testclient import TestClient

from asset_store_core.api import create_app
from asset_store_core.errors import ObjectNotFoundError
from asset_store_core.object_store import compute_checksum
from asset_store_core.s3_object_store import S3ObjectStore
from asset_store_core.service_identity import dev_secret
from asset_store_core.storage import ObjectStoreLocation

_ENDPOINT = os.environ.get("ASSET_STORE_S3_ENDPOINT")
_REGION = os.environ.get("ASSET_STORE_S3_REGION", "garage")
_ACCESS_KEY = os.environ.get("ASSET_STORE_S3_ACCESS_KEY")
_SECRET_KEY = os.environ.get("ASSET_STORE_S3_SECRET_KEY")


def _garage_available() -> bool:
    """Whether Garage credentials are present and the endpoint answers."""

    if not (_ENDPOINT and _ACCESS_KEY and _SECRET_KEY):
        return False
    try:
        store = _build_store()
        # A cheap reachability probe: stat a key that does not exist.
        store.stat_object(ObjectStoreLocation(bucket="cache", key="__probe__/none"))
    except Exception:
        return False
    return True


def _build_store() -> S3ObjectStore:
    assert _ENDPOINT and _ACCESS_KEY and _SECRET_KEY
    return S3ObjectStore(
        endpoint_url=_ENDPOINT,
        region=_REGION,
        access_key=_ACCESS_KEY,
        secret_key=_SECRET_KEY,
    )


_SKIP_REASON = "Garage not reachable; export deploy/compose/.env.garage to run these tests"


@unittest.skipUnless(_garage_available(), _SKIP_REASON)
class S3ObjectStoreGarageTest(unittest.TestCase):
    """Certify the four ObjectStoreBackend operations against real Garage."""

    def setUp(self) -> None:
        self.store = _build_store()
        self._written: list[ObjectStoreLocation] = []

    def tearDown(self) -> None:
        for location in self._written:
            self.store.delete_object(location)

    def _location(self) -> ObjectStoreLocation:
        location = ObjectStoreLocation(bucket="cache", key=f"itest/assets/{uuid.uuid4().hex}")
        self._written.append(location)
        return location

    def test_put_then_get_round_trip(self) -> None:
        location = self._location()
        payload = b"garage round trip payload"

        stat = self.store.put_object(location, payload)
        self.assertEqual(len(payload), stat.size_bytes)
        self.assertEqual(compute_checksum(payload), stat.checksum)
        self.assertEqual(payload, self.store.get_object(location))

    def test_stat_returns_size_and_checksum(self) -> None:
        location = self._location()
        payload = b"x" * 4096

        self.store.put_object(location, payload)
        stat = self.store.stat_object(location)
        self.assertIsNotNone(stat)
        assert stat is not None
        self.assertEqual(4096, stat.size_bytes)
        self.assertEqual(compute_checksum(payload), stat.checksum)

    def test_get_missing_raises_object_not_found(self) -> None:
        missing = ObjectStoreLocation(bucket="cache", key=f"itest/missing/{uuid.uuid4().hex}")
        with self.assertRaises(ObjectNotFoundError):
            self.store.get_object(missing)

    def test_stat_missing_returns_none(self) -> None:
        missing = ObjectStoreLocation(bucket="cache", key=f"itest/missing/{uuid.uuid4().hex}")
        self.assertIsNone(self.store.stat_object(missing))

    def test_delete_is_idempotent(self) -> None:
        location = self._location()
        self.store.put_object(location, b"to delete")
        self.store.delete_object(location)
        # Deleting an already-absent key must not raise.
        self.store.delete_object(location)
        self.assertIsNone(self.store.stat_object(location))

    def test_overwrite_replaces_payload(self) -> None:
        location = self._location()
        self.store.put_object(location, b"first")
        stat = self.store.put_object(location, b"second-and-longer")
        self.assertEqual(b"second-and-longer", self.store.get_object(location))
        self.assertEqual(compute_checksum(b"second-and-longer"), stat.checksum)

    def test_multipart_round_trip(self) -> None:
        """Certify Garage multipart upload via the adapter (S-001).

        12 MiB at the default 8 MiB threshold/part size spans two parts (8 MiB +
        4 MiB), exercising create -> upload_part x2 -> complete on real Garage.
        """

        location = self._location()
        payload = b"m" * (12 * 1024 * 1024)

        stat = self.store.put_object(location, payload)
        self.assertEqual(len(payload), stat.size_bytes)
        self.assertEqual(compute_checksum(payload), stat.checksum)
        self.assertEqual(payload, self.store.get_object(location))

        readback = self.store.stat_object(location)
        assert readback is not None
        self.assertEqual(len(payload), readback.size_bytes)
        self.assertEqual(compute_checksum(payload), readback.checksum)

    def test_presigned_get_url_round_trip(self) -> None:
        """Certify Garage presigned-URL GET works (S-001, future hybrid mode)."""

        import boto3
        from botocore.client import Config

        location = self._location()
        payload = b"presigned payload"
        self.store.put_object(location, payload)

        client = boto3.client(
            "s3",
            endpoint_url=_ENDPOINT,
            region_name=_REGION,
            aws_access_key_id=_ACCESS_KEY,
            aws_secret_access_key=_SECRET_KEY,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": location.bucket, "Key": location.key},
            ExpiresIn=60,
        )
        with urllib.request.urlopen(url) as response:  # noqa: S310 - local dev endpoint
            self.assertEqual(payload, response.read())


@unittest.skipUnless(_garage_available(), _SKIP_REASON)
class GarageDataPlaneEndToEndTest(unittest.TestCase):
    """Certify the full HTTP data plane (reserve -> PUT -> commit -> GET) on Garage."""

    def setUp(self) -> None:
        store = _build_store()
        self.client = TestClient(create_app(store=store))

    def _mint(self, *, operation: str, scope: str, service: str) -> str:
        response = self.client.post(
            "/capabilities",
            json={
                "operation": operation,
                "scope_prefix": scope,
                "ttl_seconds": 300,
            },
            headers={"Authorization": f"Service {service}:{dev_secret(service)}"},
        )
        self.assertEqual(201, response.status_code, response.text)
        return str(response.json()["capability_id"])

    @staticmethod
    def _auth(capability_id: str) -> dict[str, str]:
        return {"Authorization": f"Capability {capability_id}"}

    def test_guarded_write_then_read_through_garage(self) -> None:
        alias = f"users/42/uploads/{uuid.uuid4().hex}.txt"
        scope = alias.rsplit("/", 1)[0]
        payload = b"end-to-end through real garage"

        write_cap = self._mint(operation="write", scope=scope, service="upload-api")
        written = self.client.put(
            f"/objects/{alias}", content=payload, headers=self._auth(write_cap)
        )
        self.assertEqual(201, written.status_code, written.text)
        self.assertEqual("available", written.json()["state"])
        self.assertEqual(compute_checksum(payload), written.json()["checksum"])

        read_cap = self._mint(operation="read", scope=scope, service="upload-api")
        read = self.client.get(f"/objects/{alias}", headers=self._auth(read_cap))
        self.assertEqual(200, read.status_code)
        self.assertEqual(payload, read.content)

    def test_presigned_read_through_endpoint(self) -> None:
        alias = f"users/42/uploads/{uuid.uuid4().hex}.txt"
        scope = alias.rsplit("/", 1)[0]
        payload = b"presign via the guard endpoint"

        write_cap = self._mint(operation="write", scope=scope, service="upload-api")
        self.client.put(f"/objects/{alias}", content=payload, headers=self._auth(write_cap))

        read_cap = self._mint(operation="read", scope=scope, service="upload-api")
        response = self.client.get(
            f"/objects/{alias}",
            params={"mode": "presign", "expires_in": 60},
            headers=self._auth(read_cap),
        )
        self.assertEqual(200, response.status_code, response.text)
        url = response.json()["url"]
        with urllib.request.urlopen(url) as fetched:  # noqa: S310 - local dev endpoint
            self.assertEqual(payload, fetched.read())


if __name__ == "__main__":
    unittest.main()
