"""Multipart-upload branching tests for S3ObjectStore (S-001).

These are Docker-free: a fake boto3 client is injected so the create/upload/
complete/abort orchestration is verified deterministically without a backend.
The live multipart round-trip is certified in ``test_s3_garage_integration.py``.
"""

from __future__ import annotations

import unittest
from typing import Any

from asset_store_core.object_store import compute_checksum
from asset_store_core.s3_object_store import S3ObjectStore
from asset_store_core.storage import ObjectStoreLocation

_LOC = ObjectStoreLocation(bucket="cache", key="part/assets/obj")


class _FakeS3Client:
    """Records calls and mimics the multipart contract; never touches a network."""

    def __init__(self, *, fail_on_part: int | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.aborted = False
        self._fail_on_part = fail_on_part

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("put_object", kwargs))
        return {}

    def create_multipart_upload(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create", kwargs))
        return {"UploadId": "uid-1"}

    def upload_part(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("upload_part", kwargs))
        if self._fail_on_part is not None and kwargs["PartNumber"] == self._fail_on_part:
            raise RuntimeError("boom")
        return {"ETag": f'"etag-{kwargs["PartNumber"]}"'}

    def complete_multipart_upload(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("complete", kwargs))
        return {}

    def abort_multipart_upload(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("abort", kwargs))
        self.aborted = True
        return {}


def _store_with_fake(fake: _FakeS3Client, *, threshold: int, part_size: int) -> S3ObjectStore:
    # boto3.client() does not open a connection, so dummy creds are safe offline.
    store = S3ObjectStore(
        endpoint_url="http://localhost:3900",
        region="garage",
        access_key="dummy",
        secret_key="dummy",
        multipart_threshold=threshold,
        part_size=part_size,
    )
    store._client = fake
    return store


class MultipartBranchingTest(unittest.TestCase):
    def test_small_payload_uses_single_put(self) -> None:
        fake = _FakeS3Client()
        store = _store_with_fake(fake, threshold=1024, part_size=512)

        stat = store.put_object(_LOC, b"small payload")

        self.assertEqual(["put_object"], [name for name, _ in fake.calls])
        self.assertEqual(compute_checksum(b"small payload"), stat.checksum)
        self.assertEqual(stat.checksum, fake.calls[0][1]["Metadata"]["checksum"])

    def test_large_payload_uploads_each_part_then_completes(self) -> None:
        fake = _FakeS3Client()
        store = _store_with_fake(fake, threshold=512, part_size=512)
        payload = b"a" * 1300  # 512 + 512 + 276 -> three parts

        stat = store.put_object(_LOC, payload)

        self.assertEqual(
            ["create", "upload_part", "upload_part", "upload_part", "complete"],
            [name for name, _ in fake.calls],
        )
        self.assertEqual(1300, stat.size_bytes)
        self.assertEqual(compute_checksum(payload), stat.checksum)
        # Checksum metadata is set at initiation so head_object/stat can read it.
        self.assertEqual(stat.checksum, fake.calls[0][1]["Metadata"]["checksum"])
        completed_parts = fake.calls[-1][1]["MultipartUpload"]["Parts"]
        self.assertEqual([1, 2, 3], [p["PartNumber"] for p in completed_parts])
        self.assertEqual(['"etag-1"', '"etag-2"', '"etag-3"'], [p["ETag"] for p in completed_parts])

    def test_part_failure_aborts_upload_and_propagates(self) -> None:
        fake = _FakeS3Client(fail_on_part=2)
        store = _store_with_fake(fake, threshold=512, part_size=512)
        payload = b"a" * 1300

        with self.assertRaises(RuntimeError):
            store.put_object(_LOC, payload)

        names = [name for name, _ in fake.calls]
        self.assertIn("abort", names)
        self.assertNotIn("complete", names)
        self.assertTrue(fake.aborted)


if __name__ == "__main__":
    unittest.main()
