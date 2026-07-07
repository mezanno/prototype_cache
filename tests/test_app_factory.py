"""Tests for the environment-driven app factory (B-002).

``create_app_from_env`` is the uvicorn ASGI factory used by the compose/Swarm
stacks; it selects the object-store backend from the environment. These tests
run without Docker or network access: building ``S3ObjectStore`` only constructs
a boto3 client, it makes no calls.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from asset_store_core.api import create_app_from_env
from asset_store_core.object_store import LocalObjectStore
from asset_store_core.s3_object_store import S3ObjectStore

_S3_ENV = {
    "ASSET_STORE_S3_ENDPOINT": "http://garage:3900",
    "ASSET_STORE_S3_REGION": "garage",
    "ASSET_STORE_S3_ACCESS_KEY": "GKtest",
    "ASSET_STORE_S3_SECRET_KEY": "secrettest",
}


class CreateAppFromEnvTest(unittest.TestCase):
    def test_defaults_to_in_memory_store(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            app = create_app_from_env()
        self.assertIsInstance(app.state.store, LocalObjectStore)

    def test_selects_s3_store_when_endpoint_set(self) -> None:
        with mock.patch.dict(os.environ, _S3_ENV, clear=True):
            app = create_app_from_env()
        self.assertIsInstance(app.state.store, S3ObjectStore)

    def test_missing_s3_credentials_raise_clear_error(self) -> None:
        env = {"ASSET_STORE_S3_ENDPOINT": "http://garage:3900"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                create_app_from_env()
        self.assertIn("ASSET_STORE_S3_ACCESS_KEY", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
