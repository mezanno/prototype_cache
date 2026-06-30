"""S3-compatible :class:`ObjectStoreBackend` adapter (ADR-001, ADR-011).

Wraps a boto3 S3 client so the registry data plane can store opaque, durable
bytes in an S3-compatible backend (self-hosted Garage or hosted OVH S3) behind
the exact same :class:`~asset_store_core.object_store.ObjectStoreBackend`
protocol as the in-memory :class:`~asset_store_core.object_store.LocalObjectStore`.

The asset layer stays authoritative (ADR-011): this adapter computes the
canonical ``sha256:<hex>`` checksum itself on write (FR-022, never trusting the
S3 ETag, which is MD5/multipart-dependent) and stashes it in object metadata so
``stat_object`` can return it without re-reading the payload.

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

    __slots__ = ("_client",)

    def __init__(
        self,
        *,
        endpoint_url: str,
        region: str,
        access_key: str,
        secret_key: str,
    ) -> None:
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
        self._client.put_object(
            Bucket=location.bucket,
            Key=location.key,
            Body=payload,
            Metadata={_CHECKSUM_META_KEY: checksum},
        )
        return StoredObjectStat(size_bytes=len(payload), checksum=checksum)

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
