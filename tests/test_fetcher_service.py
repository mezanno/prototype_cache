"""fetcher-service Step-1 (stub) tests — B-020.

Unit tests for URL normalization and the rewrite-rule engine (pure functions,
including the ADR-014 dedup property), plus contract tests of ``ensure_url`` and
the FastAPI app driven against an in-memory asset-store via ``TestClient``. No
outbound network: the synthetic fetcher supplies deterministic bytes.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import sleep

import httpx
import pytest
from fastapi.testclient import TestClient

from asset_store_core.api import create_app as create_asset_store_app
from fetcher_service.app import create_app as create_fetcher_app
from fetcher_service.client import AssetStoreClient
from fetcher_service.config import RuleConfigError, load_rule_set, rule_set_from_env
from fetcher_service.fetcher import FetchedContent, HttpFetcher, SyntheticFetcher
from fetcher_service.normalize import InvalidUrl, normalize_url
from fetcher_service.rules import (
    HostPassthroughRule,
    IIIFImageRule,
    RuleSet,
    default_rule_set,
)
from fetcher_service.service import (
    InvalidRequestError,
    UpstreamError,
    UpstreamTimeoutError,
    ensure_url,
)

FETCHER_SECRET = "dev-secret:fetcher"


class _FailingFetcher:
    """Test double: always fails the outbound fetch (Step-2 error taxonomy)."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def fetch(self, url: str) -> FetchedContent:
        raise self._exc


def _asset_store_client() -> tuple[AssetStoreClient, TestClient]:
    """Build an AssetStoreClient wired to a fresh in-memory asset-store app."""

    http = TestClient(create_asset_store_app())
    return AssetStoreClient(http, service_id="fetcher", service_secret=FETCHER_SECRET), http


# --------------------------------------------------------------------------- #
# URL normalization
# --------------------------------------------------------------------------- #


def test_normalize_lowercases_and_drops_default_port() -> None:
    n = normalize_url("HTTPS://Gallica.BNF.fr:443/iiif/ark:/12148/x/full/full/0/default.jpg")
    assert n.scheme == "https"
    assert n.host == "gallica.bnf.fr"
    assert n.port is None
    assert n.canonical.startswith("https://gallica.bnf.fr/iiif/")


def test_normalize_strips_trailing_slash_and_fragment() -> None:
    n = normalize_url("https://images.example.org/a/b/#frag")
    assert n.path == "/a/b"
    assert "frag" not in n.canonical


@pytest.mark.parametrize("bad", ["", "   ", "ftp://host/x", "file:///etc/passwd", "https://"])
def test_normalize_rejects_bad_urls(bad: str) -> None:
    with pytest.raises(InvalidUrl):
        normalize_url(bad)


# --------------------------------------------------------------------------- #
# Rewrite-rule engine (ADR-014)
# --------------------------------------------------------------------------- #


def test_iiif_rule_derives_normalized_alias() -> None:
    rules = default_rule_set()
    match = rules.evaluate(
        normalize_url("https://gallica.bnf.fr/iiif/ark:/12148/btv1/full/full/0/default.jpg")
    )
    assert match is not None
    assert match.mirror_id == "gallica"
    assert match.primary_alias == "iiif/ark:/12148/btv1/full/full/0/default.jpg"


def test_iiif_rule_dedups_native_and_default_quality() -> None:
    """v1 'native' and v2/v3 'default' quality address byte-identical content."""

    rules = default_rule_set()
    v1 = rules.evaluate(
        normalize_url("https://gallica.bnf.fr/iiif/ark:/12148/btv1/full/full/0/native.jpg")
    )
    v2 = rules.evaluate(
        normalize_url("https://gallica.bnf.fr/iiif/ark:/12148/btv1/full/full/0/default.jpg")
    )
    assert v1 is not None and v2 is not None
    assert v1.aliases == v2.aliases


def test_iiif_rule_normalizes_rotation_and_case() -> None:
    rules = RuleSet(rules=(IIIFImageRule(host="gallica.bnf.fr", mirror_id="gallica"),))
    a = rules.evaluate(normalize_url("https://gallica.bnf.fr/iiif/ID/FULL/MAX/000/DEFAULT.JPG"))
    b = rules.evaluate(normalize_url("https://gallica.bnf.fr/iiif/ID/full/max/0/default.jpg"))
    assert a is not None and b is not None
    assert a.aliases == b.aliases == ("iiif/ID/full/max/0/default.jpg",)


def test_distinct_image_params_map_to_distinct_aliases() -> None:
    rules = default_rule_set()
    full = rules.evaluate(
        normalize_url("https://gallica.bnf.fr/iiif/ark:/x/full/full/0/default.jpg")
    )
    region = rules.evaluate(
        normalize_url("https://gallica.bnf.fr/iiif/ark:/x/0,0,100,100/full/0/default.jpg")
    )
    assert full is not None and region is not None
    assert full.aliases != region.aliases


def test_passthrough_rule_uses_normalized_path() -> None:
    rules = RuleSet(rules=(HostPassthroughRule(host="images.example.org", mirror_id="example"),))
    match = rules.evaluate(normalize_url("https://images.example.org/photos/cat.jpg"))
    assert match is not None
    assert match.mirror_id == "example"
    assert match.primary_alias == "photos/cat.jpg"


def test_unmatched_host_is_not_cacheable() -> None:
    assert default_rule_set().evaluate(normalize_url("https://evil.example.net/x.jpg")) is None


def test_passthrough_query_distinguishes_aliases() -> None:
    """Extra query parameters produce distinct passthrough aliases (distinct bytes)."""

    rules = RuleSet(rules=(HostPassthroughRule(host="images.example.org", mirror_id="example"),))
    plain = rules.evaluate(normalize_url("https://images.example.org/img/cat.jpg"))
    sized = rules.evaluate(normalize_url("https://images.example.org/img/cat.jpg?w=200"))
    assert plain is not None and sized is not None
    assert plain.aliases != sized.aliases
    assert sized.primary_alias == "img/cat.jpg?w=200"


def test_iiif_ignores_query_parameters() -> None:
    """IIIF identity is fully in the path; tracking query params must not fork the alias."""

    rules = default_rule_set()
    bare = rules.evaluate(
        normalize_url("https://gallica.bnf.fr/iiif/ark:/x/full/full/0/default.jpg")
    )
    tracked = rules.evaluate(
        normalize_url("https://gallica.bnf.fr/iiif/ark:/x/full/full/0/default.jpg?utm=abc")
    )
    assert bare is not None and tracked is not None
    assert bare.aliases == tracked.aliases


# --------------------------------------------------------------------------- #
# Declarative rule-config loader (TOML)
# --------------------------------------------------------------------------- #


def test_config_loads_typed_rules() -> None:
    rules = load_rule_set(
        """
        [[rule]]
        type = "iiif"
        host = "gallica.bnf.fr"
        mirror_id = "gallica"

        [[rule]]
        type = "passthrough"
        host = "images.example.org"
        mirror_id = "example"
        """
    )
    iiif = rules.evaluate(
        normalize_url("https://gallica.bnf.fr/iiif/ark:/x/full/full/0/native.jpg")
    )
    passthrough = rules.evaluate(normalize_url("https://images.example.org/a/b.jpg"))
    assert iiif is not None
    assert iiif.primary_alias == "iiif/ark:/x/full/full/0/default.jpg"
    assert passthrough is not None
    assert passthrough.primary_alias == "a/b.jpg"


def test_config_iiif_custom_path_prefix() -> None:
    rules = load_rule_set(
        """
        [[rule]]
        type = "iiif"
        host = "img.example.org"
        mirror_id = "example"
        path_prefix = ["images", "iiif"]
        """
    )
    match = rules.evaluate(
        normalize_url("https://img.example.org/images/iiif/ID/full/full/0/default.jpg")
    )
    assert match is not None
    assert match.primary_alias == "iiif/ID/full/full/0/default.jpg"


def test_config_regex_rule_matches_and_extracts() -> None:
    rules = load_rule_set(
        r"""
        [[rule]]
        type = "regex"
        host = "images.example.org"
        mirror_id = "example"
        path_match = '^img/(?P<id>[^/]+)\.(?P<fmt>jpg|png)$'
        alias_template = "img/{id}.{fmt}"
        """
    )
    match = rules.evaluate(normalize_url("https://images.example.org/img/cat.png"))
    assert match is not None
    assert match.mirror_id == "example"
    assert match.primary_alias == "img/cat.png"
    # Non-matching path falls through to default-deny.
    assert rules.evaluate(normalize_url("https://images.example.org/other/cat.png")) is None


def test_config_regex_first_match_wins_over_passthrough() -> None:
    rules = load_rule_set(
        r"""
        [[rule]]
        type = "regex"
        host = "images.example.org"
        mirror_id = "example"
        path_match = '^img/(?P<id>[^/]+)\.jpg$'
        alias_template = "canonical/{id}"

        [[rule]]
        type = "passthrough"
        host = "images.example.org"
        mirror_id = "example"
        """
    )
    match = rules.evaluate(normalize_url("https://images.example.org/img/cat.jpg"))
    assert match is not None
    assert match.primary_alias == "canonical/cat"


def test_config_rejects_unknown_type() -> None:
    with pytest.raises(RuleConfigError, match="unknown type"):
        load_rule_set('[[rule]]\ntype = "bogus"\nhost = "h"\nmirror_id = "m"\n')


def test_config_rejects_missing_field() -> None:
    with pytest.raises(RuleConfigError, match="mirror_id"):
        load_rule_set('[[rule]]\ntype = "passthrough"\nhost = "h"\n')


def test_config_rejects_unsafe_regex_construct() -> None:
    with pytest.raises(RuleConfigError, match="disallowed construct"):
        load_rule_set(
            '[[rule]]\ntype = "regex"\nhost = "h"\nmirror_id = "m"\n'
            "path_match = '^(?=x)(?P<id>.+)$'\nalias_template = \"{id}\"\n"
        )


def test_config_rejects_template_with_unknown_group() -> None:
    with pytest.raises(RuleConfigError, match="unknown group"):
        load_rule_set(
            '[[rule]]\ntype = "regex"\nhost = "h"\nmirror_id = "m"\n'
            "path_match = '^(?P<id>.+)$'\nalias_template = \"{id}/{missing}\"\n"
        )


def test_config_rejects_invalid_toml() -> None:
    with pytest.raises(RuleConfigError, match="invalid TOML"):
        load_rule_set("this is = = not toml")


def test_config_from_env_loads_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "rules.toml"
    path.write_text(
        '[[rule]]\ntype = "passthrough"\nhost = "images.example.org"\nmirror_id = "example"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("FETCHER_RULES_FILE", str(path))
    rules = rule_set_from_env()
    assert rules is not None
    match = rules.evaluate(normalize_url("https://images.example.org/a.jpg"))
    assert match is not None and match.primary_alias == "a.jpg"


def test_config_from_env_unset_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FETCHER_RULES_FILE", raising=False)
    assert rule_set_from_env() is None


# --------------------------------------------------------------------------- #
# ensure_url orchestration
# --------------------------------------------------------------------------- #


def test_ensure_url_cache_miss_then_hit_is_idempotent() -> None:
    client, http = _asset_store_client()
    rules = default_rule_set()
    fetcher = SyntheticFetcher()
    url = "https://gallica.bnf.fr/iiif/ark:/12148/btv1/full/full/0/default.jpg"

    first = ensure_url(client, rules, fetcher, url=url)
    assert first.cache_hit is False
    assert first.bucket == "cache"
    assert first.partition_id == "gallica"
    assert first.qualified_alias == "cache/gallica/iiif/ark:/12148/btv1/full/full/0/default.jpg"

    second = ensure_url(client, rules, fetcher, url=url)
    assert second.cache_hit is True
    assert second.asset_id == first.asset_id
    assert second.qualified_alias == first.qualified_alias

    # Stored bytes are the verifiable synthetic payload echoing the URL.
    read = http.get(
        f"/objects/{first.qualified_alias}",
        headers={"Authorization": f"Capability {_read_cap(client)}"},
    )
    assert read.status_code == 200
    payload = json.loads(read.content)
    assert payload["stub"] is True
    assert payload["url"].startswith("https://gallica.bnf.fr/iiif/")


def _read_cap(client: AssetStoreClient) -> str:
    """Mint a read capability for the gallica cache prefix (test helper)."""

    response = client._http.post(  # noqa: SLF001 - test-only access
        "/capabilities",
        headers={"Authorization": "Service fetcher:dev-secret:fetcher"},
        json={
            "operation": "read",
            "scope_prefix": "cache/gallica",
            "ttl_seconds": 300,
            "single_use": False,
        },
    )
    cap_id: str = response.json()["capability_id"]
    return cap_id


def test_ensure_url_two_variants_hit_same_asset() -> None:
    client, _ = _asset_store_client()
    rules = default_rule_set()
    fetcher = SyntheticFetcher()

    first = ensure_url(
        client,
        rules,
        fetcher,
        url="https://gallica.bnf.fr/iiif/ark:/x/full/full/0/native.jpg",
    )
    second = ensure_url(
        client,
        rules,
        fetcher,
        url="https://gallica.bnf.fr/iiif/ark:/x/full/full/0/default.jpg",
    )
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.asset_id == first.asset_id


def test_ensure_url_non_cacheable_requires_tmp_id() -> None:
    client, _ = _asset_store_client()
    with pytest.raises(InvalidRequestError):
        ensure_url(
            client,
            default_rule_set(),
            SyntheticFetcher(),
            url="https://evil.example.net/x.jpg",
        )


def test_ensure_url_non_cacheable_stages_in_tmp() -> None:
    client, _ = _asset_store_client()
    result = ensure_url(
        client,
        default_rule_set(),
        SyntheticFetcher(),
        url="https://evil.example.net/x.jpg",
        tmp_id="task-42",
    )
    assert result.bucket == "tmp"
    assert result.partition_id == "task-42"
    assert result.qualified_alias.startswith("tmp/task-42/")
    assert result.cache_hit is False


def test_ensure_url_invalid_url_raises() -> None:
    client, _ = _asset_store_client()
    with pytest.raises(InvalidRequestError):
        ensure_url(client, default_rule_set(), SyntheticFetcher(), url="not-a-url")


def test_ensure_url_propagates_upstream_error() -> None:
    client, _ = _asset_store_client()
    fetcher = _FailingFetcher(UpstreamError("origin returned 500"))
    with pytest.raises(UpstreamError):
        ensure_url(
            client,
            default_rule_set(),
            fetcher,
            url="https://gallica.bnf.fr/iiif/ark:/x/full/full/0/default.jpg",
        )


# --------------------------------------------------------------------------- #
# FastAPI app contract
# --------------------------------------------------------------------------- #


def test_app_ensure_url_endpoint_happy_path() -> None:
    store_client, _ = _asset_store_client()
    app = create_fetcher_app(asset_store_client=store_client, fetcher=SyntheticFetcher())
    fetcher_client = TestClient(app)

    resp = fetcher_client.post(
        "/v1/ensure-url",
        json={"url": "https://gallica.bnf.fr/iiif/ark:/x/full/full/0/default.jpg"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["cache_hit"] is False
    assert body["bucket"] == "cache"
    assert body["partition_id"] == "gallica"


def test_app_ensure_url_invalid_url_returns_400() -> None:
    store_client, _ = _asset_store_client()
    app = create_fetcher_app(asset_store_client=store_client)
    fetcher_client = TestClient(app)

    resp = fetcher_client.post("/v1/ensure-url", json={"url": "ftp://x/y"})
    assert resp.status_code == 400
    assert resp.json()["title"] == "Invalid request"


def test_app_healthz() -> None:
    store_client, _ = _asset_store_client()
    app = create_fetcher_app(asset_store_client=store_client)
    fetcher_client = TestClient(app)
    assert fetcher_client.get("/healthz").json() == {"status": "ok"}


def test_app_upstream_error_returns_502() -> None:
    store_client, _ = _asset_store_client()
    app = create_fetcher_app(
        asset_store_client=store_client,
        fetcher=_FailingFetcher(UpstreamError("origin 500")),
    )
    fetcher_client = TestClient(app)
    resp = fetcher_client.post(
        "/v1/ensure-url",
        json={"url": "https://gallica.bnf.fr/iiif/ark:/x/full/full/0/default.jpg"},
    )
    assert resp.status_code == 502
    assert resp.json()["title"] == "Upstream fetch failed"


def test_app_upstream_timeout_returns_504() -> None:
    store_client, _ = _asset_store_client()
    app = create_fetcher_app(
        asset_store_client=store_client,
        fetcher=_FailingFetcher(UpstreamTimeoutError("origin timed out")),
    )
    fetcher_client = TestClient(app)
    resp = fetcher_client.post(
        "/v1/ensure-url",
        json={"url": "https://gallica.bnf.fr/iiif/ark:/x/full/full/0/default.jpg"},
    )
    assert resp.status_code == 504
    assert resp.json()["title"] == "Upstream timeout"


# --------------------------------------------------------------------------- #
# HttpFetcher — real outbound HTTP against a loopback origin
# --------------------------------------------------------------------------- #


class _OriginHandler(BaseHTTPRequestHandler):
    """Canned routes for the in-process origin used by HttpFetcher tests."""

    def log_message(self, *args: object) -> None:  # silence test-server logging
        pass

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == "/ok":
            body = b"hello world"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
        elif self.path == "/loop":
            self.send_response(302)
            self.send_header("Location", "/loop")
            self.end_headers()
        elif self.path == "/slow":
            sleep(0.5)
            self.send_response(200)
            self.send_header("Content-Length", "1")
            self.end_headers()
            self.wfile.write(b"x")
        elif self.path == "/big":
            body = b"x" * 1024
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture
def origin() -> Iterator[str]:
    """Start a threaded loopback HTTP origin and yield its base URL."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), _OriginHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _loopback_fetcher(**kwargs: object) -> HttpFetcher:
    """HttpFetcher permitted to reach the loopback origin (private hosts allowed)."""

    return HttpFetcher(allow_private_hosts=True, **kwargs)  # type: ignore[arg-type]


def test_http_fetcher_success(origin: str) -> None:
    result = _loopback_fetcher().fetch(f"{origin}/ok")
    assert result.data == b"hello world"
    assert result.mime == "text/plain"


def test_http_fetcher_follows_redirect(origin: str) -> None:
    result = _loopback_fetcher().fetch(f"{origin}/redirect")
    assert result.data == b"hello world"


def test_http_fetcher_redirect_cap(origin: str) -> None:
    with pytest.raises(UpstreamError, match="too many redirects"):
        _loopback_fetcher(max_redirects=2).fetch(f"{origin}/loop")


def test_http_fetcher_timeout(origin: str) -> None:
    with pytest.raises(UpstreamTimeoutError):
        _loopback_fetcher(read_timeout=0.1).fetch(f"{origin}/slow")


def test_http_fetcher_body_cap(origin: str) -> None:
    with pytest.raises(UpstreamError, match="max_bytes"):
        _loopback_fetcher(max_bytes=100).fetch(f"{origin}/big")


def test_http_fetcher_http_error(origin: str) -> None:
    with pytest.raises(UpstreamError, match="HTTP 404"):
        _loopback_fetcher().fetch(f"{origin}/missing")


@pytest.mark.parametrize("blocked", ["http://127.0.0.1/x", "http://10.0.0.1/x", "http://[::1]/x"])
def test_http_fetcher_ssrf_blocks_private(blocked: str) -> None:
    with pytest.raises(UpstreamError, match="blocked address"):
        HttpFetcher(allow_private_hosts=False).fetch(blocked)


def test_http_fetcher_rejects_non_http_scheme() -> None:
    with pytest.raises(UpstreamError, match="not allowed"):
        HttpFetcher().fetch("ftp://example.org/x")


def test_http_fetcher_revalidates_ssrf_after_redirect() -> None:
    """A redirect to a private address is blocked on the second hop (no network)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "http://10.0.0.1/next"})
        return httpx.Response(200, content=b"should-not-reach")

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    fetcher = HttpFetcher(allow_private_hosts=False, client=client)
    # Start at a public literal IP (allowed); the redirect target must be rejected.
    with pytest.raises(UpstreamError, match="blocked address"):
        fetcher.fetch("http://93.184.216.34/start")
