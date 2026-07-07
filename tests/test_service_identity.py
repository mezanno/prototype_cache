"""Unit tests for service-identity authentication (FR-014)."""

from __future__ import annotations

import unittest

from asset_store_core.errors import ServiceAuthError, ValidationError
from asset_store_core.service_identity import (
    ENV_VAR,
    ServiceCredentialStore,
    dev_secret,
)


class ServiceCredentialStoreTest(unittest.TestCase):
    def test_authenticates_valid_credential(self) -> None:
        store = ServiceCredentialStore({"upload-api": "s3cret"})
        self.assertEqual("upload-api", store.authenticate("upload-api", "s3cret"))

    def test_trims_whitespace_around_identity(self) -> None:
        store = ServiceCredentialStore({"upload-api": "s3cret"})
        self.assertEqual("upload-api", store.authenticate("  upload-api ", "s3cret"))

    def test_rejects_wrong_secret(self) -> None:
        store = ServiceCredentialStore({"upload-api": "s3cret"})
        with self.assertRaises(ServiceAuthError):
            store.authenticate("upload-api", "nope")

    def test_rejects_unknown_identity(self) -> None:
        store = ServiceCredentialStore({"upload-api": "s3cret"})
        with self.assertRaises(ServiceAuthError):
            store.authenticate("ghost", "s3cret")

    def test_rejects_empty_secret(self) -> None:
        store = ServiceCredentialStore({"upload-api": "s3cret"})
        with self.assertRaises(ServiceAuthError):
            store.authenticate("upload-api", "")

    def test_empty_credentials_map_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ServiceCredentialStore({})

    def test_blank_secret_in_map_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ServiceCredentialStore({"upload-api": ""})

    def test_dev_default_authenticates_known_identities(self) -> None:
        store = ServiceCredentialStore.dev_default()
        for service_id in ("upload-api", "worker", "admin", "bulk-loader"):
            self.assertEqual(service_id, store.authenticate(service_id, dev_secret(service_id)))

    def test_from_env_parses_pairs(self) -> None:
        store = ServiceCredentialStore.from_env({ENV_VAR: "svc-a:secret-a, svc-b:secret-b"})
        self.assertEqual("svc-a", store.authenticate("svc-a", "secret-a"))
        self.assertEqual("svc-b", store.authenticate("svc-b", "secret-b"))

    def test_from_env_falls_back_to_dev_default_when_unset(self) -> None:
        store = ServiceCredentialStore.from_env({})
        self.assertEqual("worker", store.authenticate("worker", dev_secret("worker")))

    def test_from_env_rejects_malformed_entry(self) -> None:
        with self.assertRaises(ValidationError):
            ServiceCredentialStore.from_env({ENV_VAR: "no-colon-here"})


if __name__ == "__main__":
    unittest.main()
