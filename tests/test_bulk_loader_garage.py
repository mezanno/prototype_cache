"""Garage-gated end-to-end test for the bulk-loader (B-011, S-001/S-004).

Runs the loader against an app backed by the real ``S3ObjectStore`` + a live
Garage instance and reads the uploaded bytes back out of the bucket, proving the
whole ingestion path down to S3 storage. **Skipped unless** Garage is reachable
and its credentials are exported:

    cd deploy/compose
    docker compose -f docker-compose.garage.yml up -d && ./garage-init.sh
    set -a && source .env.garage && set +a
    uv run pytest tests/test_bulk_loader_garage.py -q
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from asset_store_core.api import create_app
from asset_store_core.s3_object_store import S3ObjectStore
from asset_store_core.service_identity import dev_secret
from asset_store_core.storage import ObjectStoreLocation

_TOOL_DIR = Path(__file__).resolve().parent.parent / "tools" / "bulk-loader"
if str(_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOL_DIR))

import bulk_loader  # noqa: E402

_ENDPOINT = os.environ.get("ASSET_STORE_S3_ENDPOINT")
_REGION = os.environ.get("ASSET_STORE_S3_REGION", "garage")
_ACCESS_KEY = os.environ.get("ASSET_STORE_S3_ACCESS_KEY")
_SECRET_KEY = os.environ.get("ASSET_STORE_S3_SECRET_KEY")


def _build_store() -> S3ObjectStore:
    assert _ENDPOINT and _ACCESS_KEY and _SECRET_KEY
    return S3ObjectStore(
        endpoint_url=_ENDPOINT,
        region=_REGION,
        access_key=_ACCESS_KEY,
        secret_key=_SECRET_KEY,
    )


def _garage_available() -> bool:
    if not (_ENDPOINT and _ACCESS_KEY and _SECRET_KEY):
        return False
    try:
        _build_store().stat_object(ObjectStoreLocation(bucket="cache", key="__probe__/none"))
    except Exception:
        return False
    return True


_SKIP_REASON = "Garage not reachable; export deploy/compose/.env.garage to run these tests"


@unittest.skipUnless(_garage_available(), _SKIP_REASON)
class BulkLoaderGarageEndToEndTest(unittest.TestCase):
    """Drive the loader against real Garage and verify bytes land in the bucket."""

    def setUp(self) -> None:
        self.store = _build_store()
        self.client = TestClient(create_app(store=self.store))
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._dir.name)
        self._written: list[ObjectStoreLocation] = []
        # Unique mirror per run so parallel/repeat runs never collide.
        self.mirror_id = f"itest-{uuid.uuid4().hex[:8]}"

    def tearDown(self) -> None:
        for location in self._written:
            self.store.delete_object(location)
        self._dir.cleanup()

    def _register_for_cleanup(self, alias: str) -> ObjectStoreLocation | None:
        """Resolve an alias and register its object for teardown deletion.

        Returns ``None`` if the alias did not commit, so cleanup is best-effort
        and never itself raises during a partially-failed run.
        """

        resolved = self.client.get(
            "/resolve", params={"space": "cache", "alias": f"{self.mirror_id}/{alias}"}
        )
        if resolved.status_code != 200:
            return None
        body = resolved.json()
        location = ObjectStoreLocation(bucket=body["space"], key=body["storage_key"])
        self._written.append(location)
        return location

    def test_bulk_load_bytes_land_in_garage(self) -> None:
        payload_a = b"garage bulk payload A"
        payload_b = b"garage bulk payload B" * 10
        (self.tmp / "a.bin").write_bytes(payload_a)
        (self.tmp / "b.bin").write_bytes(payload_b)
        rows = [
            bulk_loader.ManifestRow("img/a.bin", "application/octet-stream", "a.bin"),
            bulk_loader.ManifestRow("img/b.bin", "application/octet-stream", "b.bin"),
        ]

        report = bulk_loader.run_bulk_load(
            self.client,
            mirror_id=self.mirror_id,
            rows=rows,
            service_id="bulk-loader",
            service_secret=dev_secret("bulk-loader"),
            base_dir=self.tmp,
        )

        # Register every committed object for teardown BEFORE any assertion that
        # could fail, so a failing assertion never leaks bytes on Garage.
        loc_a = self._register_for_cleanup("img/a.bin")
        loc_b = self._register_for_cleanup("img/b.bin")

        self.assertFalse(report.any_failed, [r.error for r in report.failed])
        self.assertEqual(2, len(report.ok))

        # Read the bytes straight back out of the Garage bucket.
        assert loc_a is not None and loc_b is not None
        self.assertEqual(payload_a, self.store.get_object(loc_a))
        self.assertEqual(payload_b, self.store.get_object(loc_b))


if __name__ == "__main__":
    unittest.main()
