"""URL normalization for the fetcher (ADR-014).

Normalization is the first half of the cache dedup story: two URLs that address
the **same** origin resource must normalize to the same key so the rewrite rules
([`rules.py`](rules.py)) derive the same cache alias set. This module is content-
agnostic string canonicalization only; the rule set decides cacheability and the
alias tail.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

# Only these schemes are ever fetchable; everything else is rejected as invalid.
_ALLOWED_SCHEMES = frozenset({"http", "https"})
_DEFAULT_PORTS = {"http": 80, "https": 443}


class InvalidUrl(ValueError):
    """Raised when a URL is syntactically unusable or uses a disallowed scheme."""


@dataclass(frozen=True, slots=True)
class NormalizedUrl:
    """A canonicalized origin URL split into its addressing parts."""

    scheme: str
    host: str
    port: int | None
    path: str  # leading '/', percent-decoded, no trailing slash (except root)
    query: str  # raw query string ('' when absent)

    @property
    def canonical(self) -> str:
        """Rebuild a stable canonical URL string (used as the fetch/identity key)."""

        authority = self.host if self.port is None else f"{self.host}:{self.port}"
        base = f"{self.scheme}://{authority}{self.path}"
        return f"{base}?{self.query}" if self.query else base

    @property
    def path_segments(self) -> tuple[str, ...]:
        """Path split into non-empty segments (percent-decoded)."""

        return tuple(seg for seg in self.path.split("/") if seg)


def normalize_url(raw: str) -> NormalizedUrl:
    """Parse and canonicalize ``raw`` into a :class:`NormalizedUrl`.

    Lowercases scheme and host, drops the default port and any fragment, and
    percent-decodes the path. Raises :class:`InvalidUrl` for empty input, a
    missing host, or a non-``http(s)`` scheme.
    """

    if not raw or not raw.strip():
        raise InvalidUrl("URL must be non-empty")
    parts = urlsplit(raw.strip())
    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise InvalidUrl(f"unsupported URL scheme {parts.scheme!r}; expected http or https")
    host = parts.hostname
    if not host:
        raise InvalidUrl(f"URL has no host: {raw!r}")
    host = host.lower()

    port = parts.port
    if port is not None and _DEFAULT_PORTS.get(scheme) == port:
        port = None

    path = unquote(parts.path) or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    return NormalizedUrl(scheme=scheme, host=host, port=port, path=path, query=parts.query)
