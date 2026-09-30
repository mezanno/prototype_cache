"""Service-identity authentication for the storage-guard (FR-014).

Calling services authenticate to the guard with a **static shared secret** before
it will mint any capability. This anchors the FR-015 bucket allowlist to a
*verified* identity instead of a self-declared ``caller_service_id`` field, which
a caller could otherwise spoof.

Credentials are provisioned out-of-band (one secret per service identity) and
supplied via the ``ASSET_STORE_SERVICE_CREDENTIALS`` environment variable in the
form ``id1:secret1,id2:secret2``. When the variable is unset, startup fails unless
``ASSET_STORE_DEV_MODE=1`` explicitly enables deterministic development credentials.
mTLS / OIDC remain forward steps (ADR-006).
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Mapping

from asset_store_core.errors import ServiceAuthError, ValidationError
from asset_store_core.service_policy import KNOWN_SERVICE_IDS

ENV_VAR = "ASSET_STORE_SERVICE_CREDENTIALS"


def dev_secret(service_id: str) -> str:
    """Return the deterministic dev-only secret for ``service_id``.

    Used by the fallback credential store and by tests. **Never** a production
    secret — it is derived from the public service id on purpose.
    """

    return f"dev-secret:{service_id.strip()}"


class ServiceCredentialStore:
    """Static ``service_id -> secret`` credentials with constant-time checks."""

    __slots__ = ("_secrets",)

    def __init__(self, credentials: Mapping[str, str]) -> None:
        cleaned: dict[str, str] = {}
        for raw_id, secret in credentials.items():
            service_id = raw_id.strip()
            if not service_id:
                raise ValidationError("service credential id must not be empty")
            if not secret:
                raise ValidationError(f"service credential for {service_id!r} must not be empty")
            cleaned[service_id] = secret
        if not cleaned:
            raise ValidationError("credential store must define at least one identity")
        self._secrets = cleaned

    @property
    def service_ids(self) -> frozenset[str]:
        """Finite configured identity set for rate admission (ADR-030)."""
        return frozenset(self._secrets)

    def authenticate(self, service_id: str, secret: str) -> str:
        """Return the verified service id, or raise :class:`ServiceAuthError`.

        The comparison is constant-time and runs even for unknown identities so
        the response time does not leak which service ids exist.
        """

        candidate = service_id.strip()
        expected = self._secrets.get(candidate)
        # Compare against a placeholder when the id is unknown to keep timing flat.
        reference = expected if expected is not None else "\0"
        ok = hmac.compare_digest(reference.encode("utf-8"), (secret or "").encode("utf-8"))
        if expected is None or not ok:
            raise ServiceAuthError("invalid service credential")
        return candidate

    @classmethod
    def dev_default(cls) -> ServiceCredentialStore:
        """Build the dev-only store: every known identity with its ``dev_secret``."""

        return cls({service_id: dev_secret(service_id) for service_id in KNOWN_SERVICE_IDS})

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ServiceCredentialStore:
        """Build from ``ASSET_STORE_SERVICE_CREDENTIALS`` or an explicitly enabled dev default.

        Format: ``id1:secret1,id2:secret2``. Whitespace around entries is ignored.
        """

        source = env if env is not None else os.environ
        raw = source.get(ENV_VAR)
        if not raw or not raw.strip():
            if source.get("ASSET_STORE_DEV_MODE", "").lower() in {"1", "true", "yes"}:
                return cls.dev_default()
            raise ValidationError(
                "configure ASSET_STORE_SERVICE_CREDENTIALS or explicitly enable "
                "ASSET_STORE_DEV_MODE=1"
            )
        credentials: dict[str, str] = {}
        for entry in raw.split(","):
            item = entry.strip()
            if not item:
                continue
            service_id, sep, secret = item.partition(":")
            if not sep:
                raise ValidationError(f"invalid {ENV_VAR} entry; expected 'service_id:secret'")
            credentials[service_id.strip()] = secret.strip()
        return cls(credentials)
