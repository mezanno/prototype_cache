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
_NUMBER = r"[0-9]+(?:\.[0-9]+)?"
_REGION = rf"(?:full|square|(?:pct:)?{_NUMBER},{_NUMBER},{_NUMBER},{_NUMBER})"
_SIZE = rf"(?:full|max|pct:{_NUMBER}|!?[0-9]+,[0-9]*|!?[0-9]*,[0-9]+)"
_IMAGE = re.compile(
    rf"/iiif/ark:/12148/[A-Za-z0-9]+/f[1-9][0-9]*/{_REGION}/{_SIZE}/"
    rf"!?{_NUMBER}/(?:native|default|color|gray|bitonal)\.(?:jpg|jpeg|tif|tiff)"
)


@dataclass(frozen=True)
class PilotTarget:
    origin_url: str
    path: str

    @property
    def relative_alias(self) -> str:
        return f"{PARTITION}/{self.path.lstrip('/')}"


class GallicaPolicy:
    """HTTPS, exact host, image paths; no queries or ambiguous encodings."""

    def require(self, raw: str) -> PilotTarget:
        if not raw or len(raw) > 2048 or any(not 33 <= ord(c) <= 126 for c in raw):
            raise PilotDeniedError("URL is outside the approved Gallica image policy")
        try:
            parts = urlsplit(raw)
        except ValueError as exc:
            raise PilotDeniedError("URL is outside the approved Gallica image policy") from exc
        if parts.scheme != "https" or parts.netloc.lower() != HOST or "?" in raw or "#" in raw:
            raise PilotDeniedError("URL is outside the approved Gallica image policy")
        # Decode exactly once. Encoded separators, percent and reserved URL
        # delimiters cannot change path structure or hide a second decode.
        if re.search(r"%(?![0-9A-Fa-f]{2})", parts.path):
            raise PilotDeniedError("invalid path encoding")
        for encoded in re.findall(r"%[0-9A-Fa-f]{2}", parts.path):
            if chr(int(encoded[1:], 16)) in "/\\%?#":
                raise PilotDeniedError("ambiguous path encoding")
        path = unquote(parts.path)
        if _IMAGE.fullmatch(path) is None:
            raise PilotDeniedError("URL is outside the approved Gallica image policy")
        return PilotTarget(origin_url=f"https://{HOST}{path}", path=path)

    def require_read(self, raw_path: bytes, query: bytes) -> PilotTarget:
        try:
            path = raw_path.decode("ascii")
        except UnicodeDecodeError as exc:
            raise PilotDeniedError("invalid read path") from exc
        if query or not path.startswith(f"/{HOST}/"):
            raise PilotDeniedError("read is outside the approved Gallica image policy")
        return self.require("https:/" + path)

    def match(self, url: NormalizedUrl) -> RuleMatch | None:
        target = self.require(url.canonical)
        return RuleMatch(mirror_id=PARTITION, aliases=(target.path.lstrip("/"),))
