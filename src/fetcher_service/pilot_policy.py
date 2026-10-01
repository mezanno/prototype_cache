"""Shared exact-rendition Gallica policy (B-024, SCN-010, ADR-031)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from fetcher_service.errors import PilotDeniedError
from fetcher_service.normalize import NormalizedUrl
from fetcher_service.rules import RuleMatch

HOST = "gallica.bnf.fr"
PARTITION = "gallica-pilot"
V3_HOST = "openapi.bnf.fr"
IMAGE_MIMES = frozenset({"image/jpeg", "image/tiff", "image/webp"})
_NUMBER = r"[0-9]+(?:\.[0-9]+)?"
_REGION = rf"(?:full|square|(?:pct:)?{_NUMBER},{_NUMBER},{_NUMBER},{_NUMBER})"
_SIZE = rf"(?:full|max|pct:{_NUMBER}|!?[0-9]+,[0-9]*|!?[0-9]*,[0-9]+)"
_IMAGE = re.compile(
    rf"/iiif/ark:/12148/[A-Za-z0-9]+/f[1-9][0-9]*/{_REGION}/{_SIZE}/"
    rf"!?{_NUMBER}/(?:native|default|color|gray|bitonal)\.(?:jpg|jpeg|tif|tiff)"
)

_V3_IMAGE = re.compile(
    rf"/iiif/image/v3/ark:/12148/[A-Za-z0-9]+/f[1-9][0-9]*/{_REGION}/{_SIZE}/"
    rf"!?{_NUMBER}/(?:native|default|color|gray|bitonal)\.(?:jpg|jpeg|tif|tiff|webp)"
)
_LEGACY_FULL = re.compile(r"/iiif/(ark:/12148/[A-Za-z0-9]+/f[1-9][0-9]*)/full/full/0/native\.jpg")
_POLICIES = {HOST: _IMAGE, V3_HOST: _V3_IMAGE}


@dataclass(frozen=True)
class PilotTarget:
    origin_url: str
    path: str
    host: str = HOST

    @property
    def fetch_url(self) -> str:
        """Owner-approved full-image legacy mapping; fetch the current endpoint."""
        match = _LEGACY_FULL.fullmatch(self.path) if self.host == HOST else None
        if match:
            return f"https://{V3_HOST}/iiif/image/v3/{match[1]}/full/max/0/default.jpg"
        return self.origin_url

    @property
    def relative_alias(self) -> str:
        if self.fetch_url != self.origin_url:
            canonical = urlsplit(self.fetch_url)
            return f"{PARTITION}/{V3_HOST}/{canonical.path.lstrip('/')}"
        prefix = "" if self.host == HOST else f"{self.host}/"
        return f"{PARTITION}/{prefix}{self.path.lstrip('/')}"


class GallicaPolicy:
    """HTTPS, exact host, image paths; no queries or ambiguous encodings."""

    def require(self, raw: str) -> PilotTarget:
        if not raw or len(raw) > 2048 or any(not 33 <= ord(c) <= 126 for c in raw):
            raise PilotDeniedError("URL is outside the approved Gallica image policy")
        try:
            parts = urlsplit(raw)
        except ValueError as exc:
            raise PilotDeniedError("URL is outside the approved Gallica image policy") from exc
        host = parts.netloc.lower()
        if parts.scheme != "https" or host not in _POLICIES or "?" in raw or "#" in raw:
            raise PilotDeniedError("URL is outside the approved Gallica image policy")
        # Decode exactly once. Encoded separators, percent and reserved URL
        # delimiters cannot change path structure or hide a second decode.
        if re.search(r"%(?![0-9A-Fa-f]{2})", parts.path):
            raise PilotDeniedError("invalid path encoding")
        for encoded in re.findall(r"%[0-9A-Fa-f]{2}", parts.path):
            if chr(int(encoded[1:], 16)) in "/\\%?#":
                raise PilotDeniedError("ambiguous path encoding")
        path = unquote(parts.path)
        if _POLICIES[host].fullmatch(path) is None:
            raise PilotDeniedError("URL is outside the approved Gallica image policy")
        return PilotTarget(origin_url=f"https://{host}{path}", path=path, host=host)

    def require_read(self, raw_path: bytes, query: bytes) -> PilotTarget:
        try:
            path = raw_path.decode("ascii")
        except UnicodeDecodeError as exc:
            raise PilotDeniedError("invalid read path") from exc
        if query or not any(path.startswith(f"/{host}/") for host in _POLICIES):
            raise PilotDeniedError("read is outside the approved Gallica image policy")
        return self.require("https:/" + path)

    def match(self, url: NormalizedUrl) -> RuleMatch | None:
        target = self.require(url.canonical)
        return RuleMatch(
            mirror_id=PARTITION, aliases=(target.relative_alias.removeprefix(PARTITION + "/"),)
        )
