"""Tests explicitly opt into local development credentials (ADR-022)."""

import pytest


@pytest.fixture(autouse=True)
def explicit_development_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSET_STORE_DEV_MODE", "1")
