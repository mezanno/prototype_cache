"""Stage actual fixture bytes for the authenticated raw commit contract."""

from fastapi.testclient import TestClient

from asset_store_core.object_store import ObjectStoreBackend
from asset_store_core.registry_base import AssetRegistry
from asset_store_core.storage import ObjectStoreLocation


def stage_payload(client: TestClient, asset_id: str, size: int) -> str:
    registry: AssetRegistry = getattr(client.app, "state").registry
    store: ObjectStoreBackend = getattr(client.app, "state").store
    asset = registry.get_asset(asset_id)
    location = ObjectStoreLocation.for_asset(
        space=asset.space, partition_id=asset.partition_id, asset_id=asset.asset_id
    )
    return store.put_object(location, b"x" * size).checksum
