"""Per-identity issuance admission for M-001/P2 (FR-014/050, ADR-030)."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from threading import Lock
from time import monotonic

from asset_store_core.errors import CapabilityRateError, ServiceAuthError, ValidationError


@dataclass
class _Credit:
    tokens: float
    updated_at: float


class IssuanceRateLimiter:
    """A token bucket for each configured identity, with atomic consumption.

    Rejected or failed work cannot refund an attempt; one identity cannot
    consume another's credit. Arbitrary request identities never grow state.
    """

    def __init__(
        self,
        identities: Iterable[str],
        *,
        per_minute: int,
        burst: int,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if per_minute <= 0 or burst <= 0:
            raise ValidationError("capability rate and burst must be positive")
        self._clock = clock
        self._rate = per_minute / 60
        self._burst = burst
        now = clock()
        self._credit = {identity: _Credit(float(burst), now) for identity in identities}
        self._lock = Lock()

    def admit(self, identity: str) -> None:
        """Consume one attempt or report the rounded-up refill delay (ADR-030)."""
        with self._lock:
            credit = self._credit.get(identity)
            if credit is None:
                raise ServiceAuthError("identity is not configured for issuance")
            now = self._clock()
            credit.tokens = min(
                self._burst, credit.tokens + max(0.0, now - credit.updated_at) * self._rate
            )
            credit.updated_at = max(now, credit.updated_at)
            if credit.tokens < 1:
                raise CapabilityRateError(max(1, math.ceil((1 - credit.tokens) / self._rate)))
            credit.tokens -= 1
