"""M-001/P4 sanitized preflight for a rendered private Compose configuration."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


class ConfigFailure(RuntimeError):
    """Operator-safe failure; never include configuration values."""


def validate_model(model: dict[str, Any]) -> None:
    services = model.get("services", {})
    if set(services) != {"garage", "postgres", "migrate", "asset-store", "fetcher", "lifecycle"}:
        raise ConfigFailure("unexpected service set")
    for service in services.values():
        if re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", service.get("image", "")) is None:
            raise ConfigFailure("every image must be pinned by SHA-256 digest")
        if not service.get("mem_limit") or not service.get("cpus") or not service.get("pids_limit"):
            raise ConfigFailure("every service needs memory, CPU and PID limits")
        log = service.get("logging", {})
        if log.get("driver") != "json-file" or log.get("options") != {
            "max-size": "10m",
            "max-file": "3",
        }:
            raise ConfigFailure("every service needs bounded log rotation")
    for name in ("garage", "postgres", "migrate", "lifecycle"):
        if services[name].get("ports"):
            raise ConfigFailure("backend and maintenance ports must remain unpublished")
    for name in ("asset-store", "fetcher"):
        ports = services[name].get("ports", [])
        if len(ports) != 1 or ports[0].get("host_ip") != "127.0.0.1":
            raise ConfigFailure("API publication must be loopback-only")
        if services[name]["environment"].get("ASSET_STORE_DEV_MODE") != "0":
            raise ConfigFailure("development credential fallback must be disabled")
    fetch = services["fetcher"]["environment"]
    for key, expected in {
        "FETCHER_PILOT_MODE": "true",
        "FETCHER_SYNTHETIC": "false",
        "FETCHER_ALLOW_PRIVATE_HOSTS": "false",
        "ASSET_STORE_BASE_URL": "http://asset-store:8000",
    }.items():
        if fetch.get(key) != expected:
            raise ConfigFailure("fetcher must use the real approved-origin pilot path")
    asset = services["asset-store"]["environment"]
    if asset.get("ASSET_STORE_S3_ENDPOINT") != "http://garage:3900":
        raise ConfigFailure("asset-store must use the private Garage endpoint")
    try:
        budgets = json.loads(asset["ASSET_STORE_CAPACITY_BYTES"])
        if set(budgets) != {"cache", "tmp", "users", "results"} or any(
            type(v) is not int or v <= 0 for v in budgets.values()
        ):
            raise ValueError
        if int(asset["ASSET_STORE_MAX_UPLOAD_BYTES"]) != int(fetch["FETCHER_HTTP_MAX_BYTES"]):
            raise ValueError
    except (KeyError, ValueError, TypeError) as exc:
        raise ConfigFailure("configure all bucket budgets and matching byte caps") from exc
    worker = services["lifecycle"]
    if worker.get("profiles") != ["maintenance"] or worker["environment"] != asset:
        raise ConfigFailure("lifecycle must be opt-in and share API storage budgets/credentials")
    if (
        services["asset-store"].get("depends_on", {}).get("migrate", {}).get("condition")
        != "service_completed_successfully"
    ):
        raise ConfigFailure("asset-store must wait for successful migrations")
    if services["migrate"].get("command") != ["alembic", "upgrade", "head"]:
        raise ConfigFailure("migration must upgrade the packaged schema")
    app_image = services["asset-store"]["image"]
    if any(services[n]["image"] != app_image for n in ("fetcher", "migrate", "lifecycle")):
        raise ConfigFailure("all application services must use the same pinned image")

    def credentials(raw: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for entry in raw.split(","):
            identity, sep, secret = entry.partition(":")
            if (
                not sep
                or identity in result
                or len(secret) < 32
                or any(c.isspace() for c in secret)
            ):
                raise ConfigFailure(
                    "service credentials must be distinct entries with random secrets"
                )
            if "REPLACE" in secret or "dev-secret" in secret:
                raise ConfigFailure("replace all placeholder/development credentials")
            result[identity] = secret
        return result

    storage_creds = credentials(asset.get("ASSET_STORE_SERVICE_CREDENTIALS", ""))
    dispatch_creds = credentials(fetch.get("ASSET_STORE_SERVICE_CREDENTIALS", ""))
    if set(storage_creds) != {"fetcher", "task-api", "admin"} or set(dispatch_creds) != {
        "task-api",
        "admin",
    }:
        raise ConfigFailure("configure only the pilot service identities")
    if fetch.get("FETCHER_SERVICE_SECRET") != storage_creds["fetcher"] or any(
        dispatch_creds[k] != storage_creds[k] for k in dispatch_creds
    ):
        raise ConfigFailure("cross-service credentials must match")
    if len(set(storage_creds.values())) != len(storage_creds):
        raise ConfigFailure("each service identity needs a different secret")
    postgres = services["postgres"]["environment"]
    password = postgres.get("POSTGRES_PASSWORD", "")
    dsn = urlsplit(asset.get("ASSET_STORE_PG_DSN", ""))
    if (
        len(password) < 32
        or "REPLACE" in password
        or dsn.hostname != "postgres"
        or dsn.username != "asset"
        or dsn.path != "/asset_store"
        or unquote(dsn.password or "") != password
    ):
        raise ConfigFailure("configure a matching private database DSN and random password")
    for key in ("ASSET_STORE_S3_ACCESS_KEY", "ASSET_STORE_S3_SECRET_KEY"):
        value = asset.get(key, "")
        if not value or "REPLACE" in value or value.startswith("GKa55e700000"):
            raise ConfigFailure("configure provisioned non-development Garage credentials")


def load_model(env_file: Path) -> dict[str, Any]:
    if not env_file.is_file() or env_file.stat().st_mode & 0o077:
        raise ConfigFailure("protect the pilot env file with mode 600")
    compose = Path(__file__).with_name("compose.yml")
    command = [
        "docker",
        "compose",
        "--env-file",
        str(env_file.resolve()),
        "-f",
        str(compose),
        "--profile",
        "maintenance",
        "config",
        "--format",
        "json",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise ConfigFailure("Compose configuration failed; check required file paths and variables")
    model: dict[str, Any] = json.loads(result.stdout)
    # Inspect runtime source paths without printing Docker's secret-bearing output.
    paths = subprocess.run(
        command + ["--no-env-resolution"], capture_output=True, text=True, check=False
    )
    if paths.returncode:
        raise ConfigFailure("Compose runtime file inspection failed")
    source = json.loads(paths.stdout)
    for service in source["services"].values():
        for item in service.get("env_file", []):
            path = Path(item["path"])
            if not path.is_absolute() or not path.is_file() or path.stat().st_mode & 0o077:
                raise ConfigFailure("runtime env files must be absolute protected mode-600 files")
    garage = next(
        (
            v
            for v in source["services"]["garage"].get("volumes", [])
            if v.get("target") == "/etc/garage.toml"
        ),
        None,
    )
    if garage is None:
        raise ConfigFailure("mount a protected Garage config")
    garage_path = Path(garage["source"])
    if not garage_path.is_file() or garage_path.stat().st_mode & 0o077:
        raise ConfigFailure("protect Garage configuration with mode 600")
    config = tomllib.loads(garage_path.read_text())
    rpc = config.get("rpc_secret", "")
    token = config.get("admin", {}).get("admin_token", "")
    if (
        re.fullmatch(r"[0-9a-f]{64}", rpc) is None
        or len(token) < 32
        or "REPLACE" in token
        or token.startswith("dev-")
        or rpc == "1799bccfd7411eddcf9ebd316bc1f5287ad12a68094e1c6ac6abde7e6feae1ec"
    ):
        raise ConfigFailure("replace Garage RPC/admin secrets with random non-development values")
    if config.get("replication_factor") != 1 or config.get("rpc_public_addr") != "127.0.0.1:3901":
        raise ConfigFailure("Garage must use the private single-node pilot topology")
    return model


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("env_file", type=Path)
    args = parser.parse_args()
    try:
        validate_model(load_model(args.env_file))
    except (ConfigFailure, OSError, ValueError) as exc:
        print(
            "FAIL: " + (str(exc) if isinstance(exc, ConfigFailure) else "configuration read failed")
        )
        return 1
    print("PASS: private pilot configuration validated; no deployment performed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
