"""Tests for the observability skeleton: metrics, JSON logs, correlation ids."""

from __future__ import annotations

import json
import logging
import unittest

from fastapi.testclient import TestClient

from asset_store_core.api import create_app
from asset_store_core.api.observability import (
    CORRELATION_ID_HEADER,
    JsonLogFormatter,
)
from asset_store_core.service_identity import dev_secret

CORRELATION_HEADER = CORRELATION_ID_HEADER.decode()


class MetricsEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def test_metrics_endpoint_exposes_prometheus_text(self) -> None:
        response = self.client.get("/metrics")
        self.assertEqual(200, response.status_code)
        self.assertIn("text/plain", response.headers["content-type"])
        self.assertIn("asset_store_requests_total", response.text)
        self.assertIn("asset_store_request_duration_seconds", response.text)

    def test_request_increments_counter_with_endpoint_label(self) -> None:
        self.client.get("/healthz")
        body = self.client.get("/metrics").text
        self.assertIn('endpoint="healthz"', body)
        self.assertIn('result_class="2xx"', body)

    def test_capability_mint_records_outcome(self) -> None:
        self.client.post(
            "/capabilities",
            json={
                "operation": "write",
                "scope_prefix": "users/42/uploads",
                "ttl_seconds": 300,
            },
            headers={"Authorization": f"Service upload-api:{dev_secret('upload-api')}"},
        )
        self.client.post(
            "/capabilities",
            json={
                "operation": "write",
                "scope_prefix": "users/42/uploads",
                "ttl_seconds": 300,
            },
            headers={"Authorization": f"Service worker:{dev_secret('worker')}"},
        )
        body = self.client.get("/metrics").text
        self.assertIn("asset_store_capability_issued_total", body)
        self.assertIn('outcome="granted"', body)
        self.assertIn('outcome="denied"', body)


class CorrelationIdTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def test_response_always_carries_a_correlation_id(self) -> None:
        response = self.client.get("/healthz")
        self.assertTrue(response.headers.get(CORRELATION_HEADER))

    def test_inbound_correlation_id_is_echoed(self) -> None:
        response = self.client.get("/healthz", headers={CORRELATION_HEADER: "trace-123"})
        self.assertEqual("trace-123", response.headers[CORRELATION_HEADER])


class JsonLogFormatterTest(unittest.TestCase):
    def test_formats_record_as_json_with_spec_fields(self) -> None:
        record = logging.LogRecord(
            name="asset_store",
            level=logging.INFO,
            pathname="f.py",
            lineno=1,
            msg="request handled",
            args=None,
            exc_info=None,
        )
        record.event = "http.request"
        record.correlation_id = "abc"
        record.endpoint = "resolve"
        record.status = 200

        payload = json.loads(JsonLogFormatter().format(record))

        self.assertEqual("asset-store", payload["service"])
        self.assertEqual("info", payload["level"])
        self.assertEqual("http.request", payload["event"])
        self.assertEqual("request handled", payload["message"])
        self.assertEqual("abc", payload["correlation_id"])
        self.assertEqual("resolve", payload["endpoint"])
        self.assertEqual(200, payload["status"])
        self.assertIn("ts", payload)


if __name__ == "__main__":
    unittest.main()
