"""HTTP API for the asset-store prototype."""

from __future__ import annotations

from asset_store_core.api.app import create_app, create_app_from_env

__all__ = ["create_app", "create_app_from_env"]
