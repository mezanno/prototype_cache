"""S3-compatible :class:`ObjectStoreBackend` adapter (ADR-001, ADR-011).

Wraps a boto3 S3 client so the registry data plane can store opaque, durable
bytes in an S3-compatible backend (self-hosted Garage or hosted OVH S3) behind
the exact same :class:`~asset_store_core.object_store.ObjectStoreBackend`
protocol as the in-memory :class:`~asset_store_core.object_store.LocalObjectStore`.

The asset layer stays authoritative (ADR-011): this adapter computes the
canonical ``sha256:<hex>`` checksum itself on write (FR-022, never trusting the
S3 ETag, which is MD5/multipart-dependent) and stashes it in object metadata so
``stat_object`` can return it without re-reading the payload.

Large payloads are uploaded via S3 **multipart** transparently inside
``put_object`` once they reach ``multipart_threshold``; the protocol seam stays a
single ``put_object(location, bytes)`` call (S-001).

``boto3`` is an optional dependency; install it with the ``s3`` extra
(``pip install asset-store-prototype[s3]``). Importing this module without boto3
raises a clear :class:`ImportError`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from asset_store_core.errors import ObjectNotFoundError
from asset_store_core.object_store import StoredObjectStat, compute_checksum
from asset_store_core.storage import ObjectStoreLocation

try:
    import boto3
    from botocore.client import Config
    from botocore.exceptions import ClientError
except ImportError as exc:  # pragma: no cover - exercised only without the s3 extra
    raise ImportError(
        "S3ObjectStore requires boto3; install the 's3' extra: pip install "
        "asset-store-prototype[s3]"
    ) from exc

if TYPE_CHECKING:
    from collections.abc import Mapping

# Object-metadata key under which we persist our canonical checksum string.
_CHECKSUM_META_KEY = "checksum"

# S3 (and Garage) require every part except the last to be >= 5 MiB.
_S3_MIN_PART_SIZE = 5 * 1024 * 1024
_DEFAULT_MULTIPART_THRESHOLD = 8 * 1024 * 1024
_DEFAULT_PART_SIZE = 8 * 1024 * 1024


def _is_not_found(error: ClientError) -> bool:
    """Whether a botocore ``ClientError`` denotes a missing key (404 / NoSuchKey)."""

    response: Mapping[str, Any] = error.response
    code = str(response.get("Error", {}).get("Code", ""))
    status = int(response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
    return code in {"NoSuchKey", "NoSuchBucket", "404"} or status == 404


class S3ObjectStore:
    """:class:`ObjectStoreBackend` backed by an S3-compatible service.

    Use path-style addressing and SigV4, which Garage and OVH S3 both require
    (virtual-host addressing needs per-bucket DNS we do not control in dev).
    """

    __slots__ = ("_client", "_multipart_threshold", "_part_size")

    def __init__(
        self,
        *,
        endpoint_url: str,
        region: str,
        access_key: str,
        secret_key: str,
        multipart_threshold: int = _DEFAULT_MULTIPART_THRESHOLD,
        part_size: int = _DEFAULT_PART_SIZE,
    ) -> None:
        self._multipart_threshold = multipart_threshold
        self._part_size = part_size
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    def put_object(self, location: ObjectStoreLocation, data: bytes) -> StoredObjectStat:
        payload = bytes(data)
        checksum = compute_checksum(payload)
        metadata = {_CHECKSUM_META_KEY: checksum}
        if len(payload) >= self._multipart_threshold:
            self._put_multipart(location, payload, metadata)
        else:
            self._client.put_object(
                Bucket=location.bucket,
                Key=location.key,
                Body=payload,
                Metadata=metadata,
            )
        return StoredObjectStat(size_bytes=len(payload), checksum=checksum)

    def _put_multipart(
        self,
        location: ObjectStoreLocation,
        payload: bytes,
        metadata: dict[str, str],
    ) -> None:
        """Upload ``payload`` via S3 multipart, aborting the upload on any failure.

        ``part_size`` must be >= 5 MiB for real S3/Garage backends (every part but
        the last is subject to that floor); the default satisfies it.
        """

        created = self._client.create_multipart_upload(
            Bucket=location.bucket, Key=location.key, Metadata=metadata
        )
        upload_id = created["UploadId"]
        try:
            parts: list[dict[str, Any]] = []
            for part_number, start in enumerate(range(0, len(payload), self._part_size), start=1):
                chunk = payload[start : start + self._part_size]
                result = self._client.upload_part(
                    Bucket=location.bucket,
                    Key=location.key,
                    UploadId=upload_id,
                    PartNumber=part_number,
                    Body=chunk,
                )
                parts.append({"ETag": result["ETag"], "PartNumber": part_number})
            self._client.complete_multipart_upload(
                Bucket=location.bucket,
                Key=location.key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )
        except Exception:
            self._client.abort_multipart_upload(
                Bucket=location.bucket, Key=location.key, UploadId=upload_id
            )
            raise

    def get_object(self, location: ObjectStoreLocation) -> bytes:
        try:
            response = self._client.get_object(Bucket=location.bucket, Key=location.key)
        except ClientError as exc:
            if _is_not_found(exc):
                raise ObjectNotFoundError(f"{location.bucket}/{location.key}") from exc
            raise
        data: bytes = response["Body"].read()
        return data

    def stat_object(self, location: ObjectStoreLocation) -> StoredObjectStat | None:
        try:
            response = self._client.head_object(Bucket=location.bucket, Key=location.key)
        except ClientError as exc:
            if _is_not_found(exc):
                return None
            raise
        size: int = int(response["ContentLength"])
        metadata: Mapping[str, str] = response.get("Metadata", {})
        checksum = metadata.get(_CHECKSUM_META_KEY)
        if checksum is None:
            # Object written outside this adapter: recompute from the payload.
            checksum = compute_checksum(self.get_object(location))
        return StoredObjectStat(size_bytes=size, checksum=checksum)

    def delete_object(self, location: ObjectStoreLocation) -> None:
        # S3 delete is idempotent; missing keys are not an error (mirrors LocalObjectStore).
        self._client.delete_object(Bucket=location.bucket, Key=location.key)
