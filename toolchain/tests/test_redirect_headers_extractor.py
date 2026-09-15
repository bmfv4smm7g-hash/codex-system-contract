from __future__ import annotations

from codex_wire_audit.diagnostics import DiagnosticCollector
from codex_wire_audit.extractors.redirect_headers import RedirectHeadersExtractor
from codex_wire_audit.legacy import load_legacy_modules
from codex_wire_audit.models import SourceFile, SourceGroup, SourceRevision, SourceSnapshot, SourceSpec
from codex_wire_audit.orchestrator import build_registry


def _file(spec_id: str, key: str, path: str, text: str) -> SourceFile:
    spec = SourceSpec(
        id=spec_id,
        legacy_key=key,
        group=SourceGroup.EXTRA,
        path_candidates=(path,),
        required=False,
        roles=("legacy_extra",),
        expected_symbols=(),
        extractor_ids=(),
    )
    return SourceFile.create(spec=spec, selected_path=path, raw_bytes=text.encode())


def _snapshot(*, omit: str | None = None, break_sensitive: bool = False) -> SourceSnapshot:
    route = '''
use http::header::AUTHORIZATION;
use http::header::COOKIE;
use http::header::PROXY_AUTHORIZATION;
use http::header::WWW_AUTHENTICATE;
const MAX_REDIRECTS: usize = 10;
enum OutboundProxyPolicy { RespectSystemProxy }
pub(super) fn redirect_request() {
    StatusCode::TEMPORARY_REDIRECT;
    StatusCode::PERMANENT_REDIRECT;
}
pub(super) fn remove_sensitive_headers(headers: &mut HeaderMap) {
    headers.remove("cookie2");
}
pub(super) fn insert_referer(previous: &Url, next: &Url) {
    if next.scheme() == "http" && previous.scheme() == "https" { return; }
    referer.set_path("/");
    referer.set_query(None);
}
fn same_origin() {}
'''
    if break_sensitive:
        route = route.replace("use http::header::PROXY_AUTHORIZATION;", "")
    mcp = '''
const MAX_REDIRECTS: usize = 10;
pub(crate) struct SameOriginRedirectHttpClient;
fn execute() {
    params.redirect_policy = HttpRedirectPolicy::Stop;
    if next_url.origin() != original_origin { "MCP HTTP redirect to a different origin is not allowed"; }
    "MCP HTTP redirects for non-loopback hostnames require HTTPS";
    deadline.checked_duration_since(Instant::now());
    "MCP HTTP request exceeded the redirect limit";
    header.name.eq_ignore_ascii_case("proxy-authorization");
    name: "referer".to_string();
    referer.set_username("");
    referer.set_password(None);
    referer.set_fragment(None);
    StatusCode::TEMPORARY_REDIRECT;
    StatusCode::PERMANENT_REDIRECT;
}
'''
    headers = '''
const HELPER_TIMEOUT: Duration = Duration::from_secs(10);
const MAX_HELPER_OUTPUT_BYTES: usize = 64 * 1024;
struct HttpHeadersProvider { server_origin: Origin, refresh_epoch: u64 }
struct RawHeaderEntries { has_exact_duplicate: bool }
fn apply_headers() {
    params.redirect_policy = HttpRedirectPolicy::Stop;
    header.name.eq_ignore_ascii_case("authorization");
}
fn reject_proxy_authorization_redirect() {
    "MCP HTTP redirect cannot safely replay Proxy-Authorization credentials";
}
fn retry_request() {
    matches!(response.status, 401 | 403);
    insufficient_scope_challenge(&response.headers);
    refresh_epoch;
}
fn run_helper() {
    process.env_clear();
    create_env_for_mcp_server();
}
'''
    rows = {
        "route": _file(
            "source_spec.extra.route_aware_redirect",
            "route_aware_redirect",
            "codex-rs/http-client/src/route_aware_redirect.rs",
            route,
        ),
        "mcp": _file(
            "source_spec.extra.mcp_http_redirect",
            "mcp_http_redirect",
            "codex-rs/rmcp-client/src/http_client_redirect.rs",
            mcp,
        ),
        "headers": _file(
            "source_spec.extra.mcp_http_headers",
            "mcp_http_headers",
            "codex-rs/rmcp-client/src/http_headers.rs",
            headers,
        ),
    }
    if omit:
        rows.pop(omit)
    files = {row.spec_id: row for row in rows.values()}
    revision = SourceRevision(
        "fixture",
        "openai/codex",
        "fixture",
        "2" * 40,
        SourceSnapshot.digest_files(files),
        False,
    )
    return SourceSnapshot(revision, files)


def test_default_registry_assigns_redirect_sources_to_routing_domain():
    registry = build_registry(load_legacy_modules())
    expected = {
        "source_spec.extra.route_aware_redirect",
        "source_spec.extra.mcp_http_redirect",
        "source_spec.extra.mcp_http_headers",
    }
    observed = {
        spec.id
        for spec in registry.specs
        if "extractor.redirect_headers" in spec.extractor_ids
    }
    assert observed == expected
    assert all("redirect_headers" in registry.get(spec_id).roles for spec_id in expected)


def test_redirect_extractor_captures_route_and_mcp_header_boundaries():
    diagnostics = DiagnosticCollector()
    result = RedirectHeadersExtractor().extract(_snapshot(), diagnostics)
    assert result.semantic_complete
    assert diagnostics.summary()["error"] == 0
    assert result.data["route_aware_redirect"]["max_redirects"] == 10
    assert result.data["route_aware_redirect"]["sensitive_headers"]["cross_origin_removed"] == [
        "authorization",
        "cookie",
        "cookie2",
        "proxy-authorization",
        "www-authenticate",
    ]
    assert result.data["mcp_same_origin_redirect"]["max_redirects"] == 10
    assert result.data["mcp_header_helper"]["helper_timeout_seconds"] == 10
    assert result.data["mcp_header_helper"]["helper_max_output_bytes"] == 65536


def test_redirect_extractor_keeps_authority_outside_routing():
    result = RedirectHeadersExtractor().extract(_snapshot(), DiagnosticCollector())
    assert "permission or approval authority" in result.data["ownership"]["does_not_own"]
    assert "MCP server/tool discovery or tool-call semantics" in result.data["ownership"]["does_not_own"]


def test_missing_redirect_source_fails_closed():
    diagnostics = DiagnosticCollector()
    result = RedirectHeadersExtractor().extract(_snapshot(omit="mcp"), diagnostics)
    assert not result.semantic_complete
    assert result.data == {}
    assert any(item.code == "REDIRECT_HEADERS_SOURCE_UNAVAILABLE" for item in diagnostics.values())


def test_sensitive_header_drift_is_error_not_fallback():
    diagnostics = DiagnosticCollector()
    result = RedirectHeadersExtractor().extract(_snapshot(break_sensitive=True), diagnostics)
    assert not result.semantic_complete
    assert any(item.code == "REDIRECT_ROUTE_PROXY_AUTH_MISSING" for item in diagnostics.values())


def test_redirect_source_identity_is_exact():
    registry = build_registry(load_legacy_modules())
    assert registry.get("source_spec.extra.route_aware_redirect").primary_path == "codex-rs/http-client/src/route_aware_redirect.rs"
    assert registry.get("source_spec.extra.mcp_http_redirect").primary_path == "codex-rs/rmcp-client/src/http_client_redirect.rs"
    assert registry.get("source_spec.extra.mcp_http_headers").primary_path == "codex-rs/rmcp-client/src/http_headers.rs"
