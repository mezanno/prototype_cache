"""Service → bucket allowlist (FR-015)."""

from __future__ import annotations

import unittest

from asset_store_core import (
    CapabilityDeniedError,
    Operation,
    assert_service_bucket_allowed,
    buckets_for_service,
)


class ServicePolicyTest(unittest.TestCase):
    def test_upload_api_writes_users_not_results(self) -> None:
        assert_service_bucket_allowed("upload-api", "users", operation=Operation.WRITE)
        with self.assertRaises(CapabilityDeniedError):
            assert_service_bucket_allowed("upload-api", "results", operation=Operation.WRITE)

    def test_worker_writes_results_only(self) -> None:
        assert_service_bucket_allowed("worker", "results", operation=Operation.WRITE)
        with self.assertRaises(CapabilityDeniedError):
            assert_service_bucket_allowed("worker", "users", operation=Operation.WRITE)

    def test_fetcher_cache_and_tmp(self) -> None:
        write = buckets_for_service("fetcher", operation=Operation.WRITE)
        self.assertEqual(frozenset({"cache", "tmp"}), write)
