"""Canonical extraction for redirect and redirect-header semantics.

Routing owns URL-hop validation, route re-resolution, redirect replay, and
origin-sensitive header behavior. MCP/provider/application semantics remain in
their own domains; this extractor only describes the transport boundary.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from ..diagnostics import DiagnosticCollector
from ..models import SourceFile, SourceSnapshot
from .registry import ExtractorResult, register_extractor

EXTRACTOR_ID = "extractor.redirect_headers"
SCHEMA_VERSION = "1.0.0"
SCHEMA_ID = "https://schemas.codex-system-contract.invalid/routing/redirect-header-semantics-v1.schema.json"
SOURCE_IDS = {
    "route_aware": "source_spec.extra.route_aware_redirect",
    "mcp_redirect": "source_spec.extra.mcp_http_redirect",
    "mcp_headers": "source_spec.extra.mcp_http_headers",
}


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _evidence(source: SourceFile, symbol: str) -> dict[str, Any]:
    return {
        "source_spec_id": source.spec_id,
        "path": source.selected_path,
        "sha256": source.content_sha256,
        "git_blob_sha": source.git_blob_sha,
        "symbol": symbol,
    }


def _missing(
    diagnostics: DiagnosticCollector,
    *,
    code: str,
    token: str,
    source: SourceFile | None,
    entity: str,
) -> None:
    diagnostics.emit(
        code=code,
        severity="error",
        category="redirect_headers",
        message=f"Required redirect/header source token is missing: {token}",
        extractor_id=EXTRACTOR_ID,
        entity_id=entity,
        source_refs=[source.spec_id] if source else [],
        details={"path": source.selected_path, "token": token} if source else {"token": token},
        recoverable=False,
        strict_failure=True,
    )


def _require(
    diagnostics: DiagnosticCollector,
    source: SourceFile,
    tokens: tuple[tuple[str, str], ...],
    *,
    entity: str,
) -> bool:
    complete = True
    for code, token in tokens:
        if token not in source.text:
            complete = False
            _missing(diagnostics, code=code, token=token, source=source, entity=entity)
    return complete


def _usize_constant(text: str, name: str) -> int | None:
    match = re.search(rf"const\s+{re.escape(name)}\s*:\s*usize\s*=\s*([0-9_]+)", text)
    return int(match.group(1).replace("_", "")) if match else None


def _duration_seconds(text: str, name: str) -> int | None:
    match = re.search(
        rf"const\s+{re.escape(name)}\s*:\s*Duration\s*=\s*Duration::from_secs\(([0-9_]+)\)",
        text,
    )
    return int(match.group(1).replace("_", "")) if match else None


def _helper_output_bytes(text: str) -> int | None:
    match = re.search(
        r"const\s+MAX_HELPER_OUTPUT_BYTES\s*:\s*usize\s*=\s*([0-9_]+)\s*\*\s*([0-9_]+)",
        text,
    )
    if not match:
        return None
    return int(match.group(1).replace("_", "")) * int(match.group(2).replace("_", ""))


def _route_aware(
    source: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("REDIRECT_ROUTE_POLICY_MISSING", "RespectSystemProxy"),
        ("REDIRECT_ROUTE_REQUEST_MISSING", "pub(super) fn redirect_request"),
        ("REDIRECT_ROUTE_SENSITIVE_MISSING", "pub(super) fn remove_sensitive_headers"),
        ("REDIRECT_ROUTE_AUTH_MISSING", "AUTHORIZATION"),
        ("REDIRECT_ROUTE_COOKIE_MISSING", "COOKIE"),
        ("REDIRECT_ROUTE_PROXY_AUTH_MISSING", "PROXY_AUTHORIZATION"),
        ("REDIRECT_ROUTE_WWW_AUTH_MISSING", "WWW_AUTHENTICATE"),
        ("REDIRECT_ROUTE_COOKIE2_MISSING", 'headers.remove("cookie2")'),
        ("REDIRECT_ROUTE_REFERER_MISSING", "pub(super) fn insert_referer"),
        ("REDIRECT_ROUTE_DOWNGRADE_MISSING", 'next.scheme() == "http" && previous.scheme() == "https"'),
        ("REDIRECT_ROUTE_REFERER_ORIGIN_MISSING", 'referer.set_path("/")'),
        ("REDIRECT_ROUTE_REFERER_QUERY_MISSING", "referer.set_query(None)"),
        ("REDIRECT_ROUTE_SAME_ORIGIN_MISSING", "fn same_origin"),
        ("REDIRECT_ROUTE_307_MISSING", "StatusCode::TEMPORARY_REDIRECT"),
        ("REDIRECT_ROUTE_308_MISSING", "StatusCode::PERMANENT_REDIRECT"),
    )
    complete = _require(diagnostics, source, tokens, entity="redirect_headers.route_aware")
    limit = _usize_constant(source.text, "MAX_REDIRECTS")
    if limit != 10:
        complete = False
        _missing(
            diagnostics,
            code="REDIRECT_ROUTE_LIMIT_DRIFT",
            token="MAX_REDIRECTS = 10",
            source=source,
            entity="redirect_headers.route_aware",
        )
    return {
        "owner": "route-aware HTTP client transport",
        "activation": "when RespectSystemProxy owns route selection, redirects are surfaced to the client pool so every destination can resolve its own proxy route",
        "max_redirects": limit,
        "statuses": [301, 302, 303, 307, 308],
        "method_and_body": {
            "post_301_302": "switch to GET and drop the body",
            "303": "switch to GET except HEAD and drop the body",
            "307_308": "retain method/body only when the original request is replayable",
            "dropped_body_headers": ["content-type", "content-length", "content-encoding", "transfer-encoding"],
        },
        "sensitive_headers": {
            "cross_origin_removed": ["authorization", "cookie", "cookie2", "proxy-authorization", "www-authenticate"],
            "same_origin": "preserve ordinary credentials; route selection still re-runs for the destination URL",
        },
        "referer": {
            "existing_value": "removed before synthesis",
            "https_to_http": "omitted on downgrade",
            "same_origin": "previous URL without userinfo or fragment",
            "cross_origin": "origin-only previous URL with path / and no query",
        },
        "origin_identity": "scheme + host + effective port",
        "evidence": _evidence(source, "redirect_request/remove_sensitive_headers/insert_referer"),
    }, complete


def _mcp_redirect(
    source: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("REDIRECT_MCP_CLIENT_MISSING", "pub(crate) struct SameOriginRedirectHttpClient"),
        ("REDIRECT_MCP_STOP_MISSING", "params.redirect_policy = HttpRedirectPolicy::Stop"),
        ("REDIRECT_MCP_ORIGIN_MISSING", "next_url.origin() != original_origin"),
        ("REDIRECT_MCP_ORIGIN_ERROR_MISSING", "MCP HTTP redirect to a different origin is not allowed"),
        ("REDIRECT_MCP_HTTP_HOST_MISSING", "MCP HTTP redirects for non-loopback hostnames require HTTPS"),
        ("REDIRECT_MCP_TIMEOUT_MISSING", "checked_duration_since"),
        ("REDIRECT_MCP_LIMIT_ERROR_MISSING", "MCP HTTP request exceeded the redirect limit"),
        ("REDIRECT_MCP_PROXY_AUTH_MISSING", 'header.name.eq_ignore_ascii_case("proxy-authorization")'),
        ("REDIRECT_MCP_REFERER_MISSING", 'name: "referer".to_string()'),
        ("REDIRECT_MCP_USERINFO_MISSING", 'referer.set_username("")'),
        ("REDIRECT_MCP_PASSWORD_MISSING", "referer.set_password(None)"),
        ("REDIRECT_MCP_FRAGMENT_MISSING", "referer.set_fragment(None)"),
        ("REDIRECT_MCP_307_MISSING", "StatusCode::TEMPORARY_REDIRECT"),
        ("REDIRECT_MCP_308_MISSING", "StatusCode::PERMANENT_REDIRECT"),
    )
    complete = _require(diagnostics, source, tokens, entity="redirect_headers.mcp_redirect")
    limit = _usize_constant(source.text, "MAX_REDIRECTS")
    if limit != 10:
        complete = False
        _missing(
            diagnostics,
            code="REDIRECT_MCP_LIMIT_DRIFT",
            token="MAX_REDIRECTS = 10",
            source=source,
            entity="redirect_headers.mcp_redirect",
        )
    return {
        "owner": "MCP same-origin HTTP redirect wrapper",
        "max_redirects": limit,
        "inspection": "the underlying client is forced to Stop so every Location is validated before sensitive request data can be replayed",
        "origin_policy": "every hop must match the original configured origin; a later hop cannot escape through a same-origin intermediate",
        "plaintext_hostname_policy": "HTTP redirects to non-localhost domain names are rejected because a later DNS answer could rebind; HTTPS authenticates the hostname",
        "timeout": "all redirect hops share the original request deadline",
        "method_and_body": "301/302 POST and 303 follow bodyless-GET behavior; 307/308 retain method/body",
        "proxy_authorization": "never replay Proxy-Authorization over plaintext redirect hops; HTTPS may retain it only inside the already-validated origin",
        "referer": "replace any existing Referer with the previous URL stripped of username, password, and fragment",
        "stop_policy": "an explicitly Stop request delegates directly and does not synthesize redirect behavior",
        "evidence": _evidence(source, "SameOriginRedirectHttpClient::execute"),
    }, complete


def _header_helper(
    source: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("REDIRECT_HELPER_PROVIDER_MISSING", "struct HttpHeadersProvider"),
        ("REDIRECT_HELPER_ORIGIN_MISSING", "server_origin"),
        ("REDIRECT_HELPER_STOP_MISSING", "params.redirect_policy = HttpRedirectPolicy::Stop"),
        ("REDIRECT_HELPER_AUTH_PRECEDENCE_MISSING", 'header.name.eq_ignore_ascii_case("authorization")'),
        ("REDIRECT_HELPER_PROXY_REPLAY_MISSING", "MCP HTTP redirect cannot safely replay Proxy-Authorization credentials"),
        ("REDIRECT_HELPER_401_403_MISSING", "matches!(response.status, 401 | 403)"),
        ("REDIRECT_HELPER_SCOPE_MISSING", "insufficient_scope_challenge"),
        ("REDIRECT_HELPER_REFRESH_EPOCH_MISSING", "refresh_epoch"),
        ("REDIRECT_HELPER_ENV_CLEAR_MISSING", ".env_clear()"),
        ("REDIRECT_HELPER_ENV_POLICY_MISSING", "create_env_for_mcp_server"),
        ("REDIRECT_HELPER_DUPLICATE_MISSING", "has_exact_duplicate"),
    )
    complete = _require(diagnostics, source, tokens, entity="redirect_headers.mcp_header_helper")
    timeout = _duration_seconds(source.text, "HELPER_TIMEOUT")
    output_bytes = _helper_output_bytes(source.text)
    if timeout != 10:
        complete = False
        _missing(
            diagnostics,
            code="REDIRECT_HELPER_TIMEOUT_DRIFT",
            token="HELPER_TIMEOUT = 10 seconds",
            source=source,
            entity="redirect_headers.mcp_header_helper",
        )
    if output_bytes != 65536:
        complete = False
        _missing(
            diagnostics,
            code="REDIRECT_HELPER_OUTPUT_LIMIT_DRIFT",
            token="MAX_HELPER_OUTPUT_BYTES = 64 KiB",
            source=source,
            entity="redirect_headers.mcp_header_helper",
        )
    return {
        "owner": "MCP helper-generated HTTP header replay boundary",
        "helper_timeout_seconds": timeout,
        "helper_max_output_bytes": output_bytes,
        "origin_scope": "helper headers apply only to requests whose URL origin matches the configured MCP server origin",
        "authorization_precedence": "an explicit bearer/OAuth Authorization already on the request wins over helper Authorization",
        "redirect_policy": "helper-decorated requests stop redirects; plaintext Proxy-Authorization + Location is rejected rather than replayed unsafely",
        "refresh": {
            "trigger": "one refresh path after POST 401/403",
            "insufficient_scope": "403 insufficient-scope OAuth challenges are not converted into helper refresh retries",
            "coalescing": "refresh_epoch groups concurrent rejected requests onto one helper attempt",
            "retry_condition": "retry only when the effective helper header set changes",
        },
        "process_boundary": "helper subprocess starts with a cleared ambient environment and the local MCP subprocess environment policy; credentials belong in JSON output, not command text",
        "evidence": _evidence(source, "HttpHeadersProvider/HttpHeadersClient"),
    }, complete


class RedirectHeadersExtractor:
    extractor_id = EXTRACTOR_ID
    source_spec_ids = tuple(SOURCE_IDS.values())

    def extract(self, snapshot: SourceSnapshot, diagnostics: DiagnosticCollector) -> ExtractorResult:
        sources = {key: snapshot.files.get(spec_id) for key, spec_id in SOURCE_IDS.items()}
        missing = [key for key, source in sources.items() if source is None]
        if missing:
            for key in missing:
                _missing(
                    diagnostics,
                    code="REDIRECT_HEADERS_SOURCE_UNAVAILABLE",
                    token=key,
                    source=None,
                    entity=f"redirect_headers.source.{key}",
                )
            return ExtractorResult(
                extractor_id=EXTRACTOR_ID,
                schema_version=SCHEMA_VERSION,
                data={},
                semantic_complete=False,
                source_spec_ids=self.source_spec_ids,
            )

        route, route_ok = _route_aware(sources["route_aware"], diagnostics)  # type: ignore[arg-type]
        mcp_redirect, mcp_ok = _mcp_redirect(sources["mcp_redirect"], diagnostics)  # type: ignore[arg-type]
        helper, helper_ok = _header_helper(sources["mcp_headers"], diagnostics)  # type: ignore[arg-type]
        complete = route_ok and mcp_ok and helper_ok
        body: dict[str, Any] = {
            "$schema": SCHEMA_ID,
            "schema_version": SCHEMA_VERSION,
            "ownership": {
                "owns": [
                    "redirect status/method/body replay semantics",
                    "per-hop route re-resolution boundary",
                    "origin-sensitive credential/header stripping",
                    "Referer synthesis across redirect hops",
                    "MCP same-origin redirect enforcement",
                    "MCP helper-header replay/refresh safety",
                ],
                "does_not_own": [
                    "MCP server/tool discovery or tool-call semantics",
                    "permission or approval authority",
                    "process environment construction outside helper launch",
                    "Responses request/event schemas",
                    "provider authentication policy",
                ],
            },
            "route_aware_redirect": route,
            "mcp_same_origin_redirect": mcp_redirect,
            "mcp_header_helper": helper,
            "evidence": {
                key: _evidence(source, key)
                for key, source in sources.items()
                if source is not None
            },
            "semantic_complete": complete,
        }
        body["semantic_digest"] = hashlib.sha256(_canonical(body)).hexdigest()
        return ExtractorResult(
            extractor_id=EXTRACTOR_ID,
            schema_version=SCHEMA_VERSION,
            data=body,
            semantic_complete=complete,
            source_spec_ids=self.source_spec_ids,
        )


@register_extractor(EXTRACTOR_ID)
def _factory() -> RedirectHeadersExtractor:
    return RedirectHeadersExtractor()
