"""ADR-032 / M-001/P4: render real Compose config, reject private-pilot regressions."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/pilot"))
from check_config import ConfigFailure, load_model, validate_model  # noqa: E402


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for key in os.environ:
        if key.startswith("PILOT_"):
            monkeypatch.delenv(key)
    password, fetcher, task, admin = "a" * 64, "b" * 64, "c" * 64, "d" * 64
    files = {
        "postgres.env": f"POSTGRES_PASSWORD={password}\n",
        "asset.env": (
            f"ASSET_STORE_PG_DSN=postgresql://asset:{password}@postgres:5432/asset_store\n"
            "ASSET_STORE_S3_ACCESS_KEY=GK012345678901234567890123\n"
            f"ASSET_STORE_S3_SECRET_KEY={'e' * 64}\n"
            f"ASSET_STORE_SERVICE_CREDENTIALS=fetcher:{fetcher},task-api:{task},admin:{admin}\n"
        ),
        "fetcher.env": (
            f"ASSET_STORE_SERVICE_CREDENTIALS=task-api:{task},admin:{admin}\n"
            f"FETCHER_SERVICE_SECRET={fetcher}\n"
        ),
        "garage.toml": (
            'replication_factor = 1\nrpc_public_addr = "127.0.0.1:3901"\n'
            f'rpc_secret = "{"f" * 64}"\n[admin]\nadmin_token = "{"a" * 64}"\n'
        ),
    }
    for name, content in files.items():
        path = tmp_path / name
        path.write_text(content)
        path.chmod(0o600)
    env = tmp_path / "pilot.env"
    env.write_text(
        f"PILOT_APP_IMAGE=example/asset-store@sha256:{'1' * 64}\n"
        f"PILOT_GARAGE_IMAGE=dxflrs/garage@sha256:{'2' * 64}\n"
        f"PILOT_POSTGRES_IMAGE=postgres@sha256:{'3' * 64}\n"
        f"PILOT_GARAGE_CONFIG={tmp_path / 'garage.toml'}\n"
        f"PILOT_POSTGRES_ENV={tmp_path / 'postgres.env'}\n"
        f"PILOT_ASSET_ENV={tmp_path / 'asset.env'}\n"
        f"PILOT_FETCHER_ENV={tmp_path / 'fetcher.env'}\n"
    )
    env.chmod(0o600)
    return env


def test_pilot_compose_renders_bounded_private_durable_services(runtime: Path) -> None:
    model = load_model(runtime)
    validate_model(model)
    assert set(model["volumes"]) == {"garage-meta", "garage-data", "postgres-data"}
    for name in ("asset-store", "fetcher", "migrate", "lifecycle"):
        service = model["services"][name]
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
    for name in ("asset-store", "fetcher"):
        command = model["services"][name]["command"]
        assert command[command.index("--workers") + 1] == "1"
        assert "--no-access-log" in command


@pytest.mark.parametrize(
    "failure",
    [
        "tag",
        "backend_port",
        "public_api",
        "dev",
        "synthetic",
        "private_origin",
        "capacity",
        "byte_cap",
        "migration",
        "lifecycle",
        "credential",
        "dsn",
        "logs",
    ],
)
def test_preflight_rejects_unsafe_runtime(runtime: Path, failure: str) -> None:
    model = load_model(runtime)
    services = model["services"]
    asset, fetch = services["asset-store"], services["fetcher"]
    if failure == "tag":
        fetch["image"] = "asset-store:latest"
    elif failure == "backend_port":
        services["postgres"]["ports"] = [{"target": 5432, "published": "5432"}]
    elif failure == "public_api":
        fetch["ports"][0]["host_ip"] = "0.0.0.0"
    elif failure == "dev":
        asset["environment"]["ASSET_STORE_DEV_MODE"] = "1"
    elif failure == "synthetic":
        fetch["environment"]["FETCHER_SYNTHETIC"] = "true"
    elif failure == "private_origin":
        fetch["environment"]["FETCHER_ALLOW_PRIVATE_HOSTS"] = "true"
    elif failure == "capacity":
        asset["environment"]["ASSET_STORE_CAPACITY_BYTES"] = "{}"
    elif failure == "byte_cap":
        fetch["environment"]["FETCHER_HTTP_MAX_BYTES"] = "99999999"
    elif failure == "migration":
        asset["depends_on"]["migrate"]["condition"] = "service_started"
    elif failure == "lifecycle":
        services["lifecycle"]["profiles"] = []
    elif failure == "credential":
        fetch["environment"]["FETCHER_SERVICE_SECRET"] = "wrong"
    elif failure == "dsn":
        asset["environment"]["ASSET_STORE_PG_DSN"] = (
            "postgresql://asset:asset@localhost/asset_store"
        )
    elif failure == "logs":
        fetch["logging"]["options"] = {}
    with pytest.raises(ConfigFailure):
        validate_model(model)


@pytest.mark.parametrize("name", ["pilot.env", "asset.env", "garage.toml"])
def test_preflight_rejects_unprotected_secret_file(runtime: Path, name: str) -> None:
    (runtime.parent / name).chmod(0o644)
    with pytest.raises(ConfigFailure):
        load_model(runtime)


def test_failure_output_does_not_expose_secret(
    runtime: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from check_config import main

    asset = runtime.parent / "asset.env"
    asset.write_text(asset.read_text().replace("b" * 64, "sensitive-test-secret"))
    monkeypatch.setattr(sys, "argv", ["check_config.py", str(runtime)])
    assert main() == 1
    assert "sensitive-test-secret" not in capsys.readouterr().out
