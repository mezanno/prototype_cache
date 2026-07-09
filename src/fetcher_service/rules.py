"""Declarative URL→alias rewrite rules (ADR-014).

The rule set does three jobs at once: **allowlisting** (a URL matching no rule is
not cacheable), **canonical naming** (the alias tail), and **cross-URL dedup**
(byte-identical variants yield the same alias set → same ``asset_id``). Rules are
evaluated in order; the first match wins. Asset-store stays content-agnostic —
these rules live in the fetcher, not the registry (ADR-011).

The MVP ships one IIIF Image API rule (Gallica-style) plus a generic host
passthrough, and is default-deny for everything else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from fetcher_service.normalize import NormalizedUrl

# IIIF Image API v1 used ``native`` as the default quality; v2/v3 renamed it to
# ``default``. Normalizing them together dedups the two API revisions (ADR-014).
_IIIF_QUALITY_ALIASES = {"native": "default"}


@dataclass(frozen=True, slots=True)
class RuleMatch:
    """A cacheable match: the mirror partition and the alias tails it yields.

    ``aliases`` are relative to ``cache/{mirror_id}/``. The first entry is the
    canonical/primary alias; any others are equivalent names bound to the same
    asset (attachment of the non-primary aliases is a Step-2 concern).
    """

    mirror_id: str
    aliases: tuple[str, ...]

    @property
    def primary_alias(self) -> str:
        return self.aliases[0]


@runtime_checkable
class CacheRule(Protocol):
    """A single ordered rewrite rule."""

    def match(self, url: NormalizedUrl) -> RuleMatch | None:
        """Return a :class:`RuleMatch` if this rule cacheably matches ``url``."""


def _host_matches(url: NormalizedUrl, host: str) -> bool:
    """Exact host or dotted-suffix (subdomain) match."""

    return url.host == host or url.host.endswith(f".{host}")


def _normalize_rotation(rotation: str) -> str:
    """Canonicalize a numeric IIIF rotation ('000' → '0', '090' → '90')."""

    body = rotation[1:] if rotation.startswith("!") else rotation
    try:
        value = int(body)
    except ValueError:
        return rotation
    return f"!{value}" if rotation.startswith("!") else str(value)


@dataclass(frozen=True, slots=True)
class IIIFImageRule:
    """Match a IIIF Image API request and produce a normalized cache alias.

    The IIIF Image API URL tail is
    ``{prefix}/{identifier}/{region}/{size}/{rotation}/{quality}.{format}``. The
    canonical alias tail is
    ``iiif/{resource_id}/{region}/{size}/{rotation}/{quality}.{format}`` with
    lowercased region/size/format, a canonical rotation, and the v1→v2 quality
    rename applied so equivalent API revisions dedup (ADR-014).

    ``path_prefix`` is the server route prefix that precedes the identifier (e.g.
    ``iiif`` for ``…/iiif/{identifier}/…``); it is stripped before deriving the
    resource id and is not part of the alias.
    """

    host: str
    mirror_id: str
    path_prefix: tuple[str, ...] = ("iiif",)

    def match(self, url: NormalizedUrl) -> RuleMatch | None:
        if not _host_matches(url, self.host):
            return None
        segments = url.path_segments
        if self.path_prefix:
            if segments[: len(self.path_prefix)] != self.path_prefix:
                return None
            segments = segments[len(self.path_prefix) :]
        # Need at least identifier/region/size/rotation/quality.format (5 tail parts).
        if len(segments) < 5:
            return None
        quality_format = segments[-1]
        if "." not in quality_format:
            return None
        quality, _, fmt = quality_format.rpartition(".")
        rotation = segments[-2]
        size = segments[-3]
        region = segments[-4]
        resource_id = "/".join(segments[:-4])
        if not resource_id:
            return None

        quality = _IIIF_QUALITY_ALIASES.get(quality.lower(), quality.lower())
        tail = (
            f"iiif/{resource_id}/{region.lower()}/{size.lower()}/"
            f"{_normalize_rotation(rotation)}/{quality}.{fmt.lower()}"
        )
        return RuleMatch(mirror_id=self.mirror_id, aliases=(tail,))


@dataclass(frozen=True, slots=True)
class HostPassthroughRule:
    """Cache any URL on ``host`` under ``cache/{mirror_id}/{normalized-path}``.

    The alias tail is the normalized path (leading slash stripped). A query string,
    when present, is appended as a stable ``?<query>`` suffix so distinct query
    variants map to distinct aliases.
    """

    host: str
    mirror_id: str

    def match(self, url: NormalizedUrl) -> RuleMatch | None:
        if not _host_matches(url, self.host):
            return None
        segments = url.path_segments
        if not segments:
            return None
        tail = "/".join(segments)
        if url.query:
            tail = f"{tail}?{url.query}"
        return RuleMatch(mirror_id=self.mirror_id, aliases=(tail,))


@dataclass(frozen=True, slots=True)
class RuleSet:
    """An ordered collection of rules evaluated first-match-wins (default-deny)."""

    rules: tuple[CacheRule, ...]

    def evaluate(self, url: NormalizedUrl) -> RuleMatch | None:
        """Return the first matching rule's result, or ``None`` (not cacheable)."""

        for rule in self.rules:
            match = rule.match(url)
            if match is not None:
                return match
        return None


def default_rule_set() -> RuleSet:
    """The MVP rule set: Gallica IIIF + a generic example host, default-deny."""

    return RuleSet(
        rules=(
            IIIFImageRule(host="gallica.bnf.fr", mirror_id="gallica"),
            HostPassthroughRule(host="images.example.org", mirror_id="example"),
        )
    )
