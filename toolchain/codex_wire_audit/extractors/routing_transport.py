"""Canonical extraction for network proxy and outbound route semantics.

This domain owns managed proxy/controller composition and HTTP/WebSocket outbound
proxy selection. Permission-profile network authority is an input owned by
contract/policy; process environment construction is owned by
contract/environment.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ..diagnostics import DiagnosticCollector
from ..models import SourceFile, SourceSnapshot
from .registry import ExtractorResult, register_extractor

EXTRACTOR_ID = "extractor.routing_transport"
SCHEMA_VERSION = "1.0.0"
SCHEMA_ID = "https://schemas.codex-system-contract.invalid/routing/routing-transport-semantics-v1.schema.json"
SOURCE_IDS = {
    "proxy_spec": "source_spec.extra.routing_proxy_spec",
    "proxy_config": "source_spec.extra.routing_proxy_config",
    "requirements": "source_spec.extra.routing_requirements",
    "outbound": "source_spec.extra.routing_outbound_proxy",
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
        category="routing_transport",
        message=f"Required routing source token is missing: {token}",
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


def _source(snapshot: SourceSnapshot, key: str) -> SourceFile | None:
    return snapshot.files.get(SOURCE_IDS[key])


def _managed_proxy(
    proxy_spec: SourceFile,
    requirements: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[dict[str, Any], bool]:
    spec_tokens = (
        ("ROUTING_PROXY_SPEC_MISSING", "pub struct NetworkProxySpec"),
        ("ROUTING_PROXY_START_MISSING", "pub async fn start_proxy"),
        ("ROUTING_REQUIREMENT_APPLY_MISSING", "fn apply_requirements"),
        ("ROUTING_CONSTRAINT_VALIDATION_MISSING", "validate_policy_against_constraints"),
        ("ROUTING_ENVIRONMENT_POLICY_MISSING", "pub fn environment_policy"),
        ("ROUTING_ENVIRONMENT_COMPOSITION_MISSING", "pub(crate) fn for_environment"),
        ("ROUTING_EXEC_NETWORK_RULES_MISSING", "compiled_network_domains"),
        ("ROUTING_POLICY_DECIDER_MISSING", "NetworkPolicyDecider"),
        ("ROUTING_APPROVAL_FLOW_MISSING", "enable_network_approval_flow"),
        ("ROUTING_HARD_DENY_MISSING", "hard_deny_allowlist_misses"),
    )
    requirement_tokens = (
        ("ROUTING_NETWORK_REQUIREMENTS_MISSING", "pub struct NetworkRequirementsToml"),
        ("ROUTING_MANAGED_DOMAIN_ONLY_MISSING", "managed_allowed_domains_only"),
        ("ROUTING_HEADER_INJECTION_MISSING", "header_injections"),
        ("ROUTING_UPSTREAM_REQUIREMENT_MISSING", "allow_upstream_proxy"),
        ("ROUTING_HTTP_PORT_REQUIREMENT_MISSING", "http_port"),
        ("ROUTING_SOCKS_PORT_REQUIREMENT_MISSING", "socks_port"),
        ("ROUTING_UNIX_SOCKET_REQUIREMENT_MISSING", "unix_sockets"),
    )
    complete = _require(diagnostics, proxy_spec, spec_tokens, entity="routing_transport.managed_proxy")
    complete &= _require(diagnostics, requirements, requirement_tokens, entity="routing_transport.managed_proxy")
    return {
        "composition": [
            "configured proxy policy supplies a base configuration",
            "managed network requirements constrain and may seed the effective policy",
            "permission-profile network authority determines whether managed enforcement/approval expansion is available",
            "environment network policy can narrow/extend within controller constraints",
            "saved exec-policy network grants may extend only a reviewable expandable allowlist",
            "managed/owner denials are restored as protected denials",
        ],
        "managed_constraints": [
            "enabled state",
            "HTTP/SOCKS listener ports",
            "upstream-proxy permission",
            "non-loopback listener permission",
            "unix-socket permission",
            "domain allow/deny sets",
            "managed-only allowlist mode",
            "local binding",
            "header injections",
        ],
        "approval_flow": "when enabled and allowlist misses are reviewable, a policy decider may ask for network approval; managed-only allowlist misses remain hard denies",
        "environment_boundary": "environment policy can be applied only under managed network enforcement and cannot override a disabled controller proxy",
        "policy_boundary": "PermissionProfile and exec-policy rules are consumed as authority inputs but their selection/approval semantics stay owned by contract/policy",
        "evidence": [
            _evidence(proxy_spec, "NetworkProxySpec"),
            _evidence(requirements, "NetworkRequirementsToml"),
        ],
    }, complete


def _proxy_runtime(proxy_config: SourceFile, diagnostics: DiagnosticCollector) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("ROUTING_PROXY_CONFIG_MISSING", "pub struct NetworkProxyConfig"),
        ("ROUTING_DOMAIN_PERMISSION_MISSING", "pub enum NetworkDomainPermission"),
        ("ROUTING_DENY_PRECEDENCE_MISSING", "None < Allow < Deny"),
        ("ROUTING_MODE_MISSING", "pub enum NetworkMode"),
        ("ROUTING_LIMITED_METHODS_MISSING", "matches!(method, \"GET\" | \"HEAD\" | \"OPTIONS\")"),
        ("ROUTING_PROXY_DEFAULT_MISSING", "http://127.0.0.1:3128"),
        ("ROUTING_SOCKS_DEFAULT_MISSING", "http://127.0.0.1:8081"),
        ("ROUTING_BIND_CLAMP_MISSING", "fn clamp_non_loopback"),
        ("ROUTING_UNIX_LOOPBACK_MISSING", "unix socket proxying is enabled"),
        ("ROUTING_RUNTIME_RESOLVE_MISSING", "pub fn resolve_runtime"),
        ("ROUTING_MANAGED_PORTS_MISSING", "pub fn managed_proxy_ports"),
    )
    complete = _require(diagnostics, proxy_config, tokens, entity="routing_transport.proxy_runtime")
    return {
        "listeners": {
            "http_default": "127.0.0.1:3128",
            "socks_default": "127.0.0.1:8081",
            "non_loopback": "clamped to loopback unless the explicit dangerous override is enabled",
            "unix_socket_bridge": "forces HTTP and SOCKS listeners back to loopback even when non-loopback was otherwise allowed",
        },
        "network_modes": {
            "full": "all HTTP methods are permitted by mode",
            "limited": "GET/HEAD/OPTIONS only; HTTPS/SOCKS behavior is further constrained so method policy remains enforceable",
        },
        "domain_precedence": "for duplicate domain patterns deny outranks allow, and allow outranks none",
        "upstream_proxy": "explicitly controlled by allow_upstream_proxy; this is managed-proxy behavior, separate from system-proxy client discovery",
        "credential_boundary": "credential-broker/MITM options are part of proxy runtime config but credential material itself is not a routing contract claim",
        "evidence": _evidence(proxy_config, "NetworkProxyConfig/NetworkMode/resolve_runtime"),
    }, complete


def _outbound(outbound: SourceFile, diagnostics: DiagnosticCollector) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("ROUTING_OUTBOUND_POLICY_MISSING", "pub enum OutboundProxyPolicy"),
        ("ROUTING_REQWEST_DEFAULT_MISSING", "ReqwestDefault"),
        ("ROUTING_SYSTEM_PROXY_POLICY_MISSING", "RespectSystemProxy"),
        ("ROUTING_ROUTE_ENUM_MISSING", "pub enum OutboundProxyRoute"),
        ("ROUTING_SYSTEM_FALLBACK_MISSING", "SystemProxyDecision::Unavailable"),
        ("ROUTING_HTTPS_PROXY_MISSING", "HTTPS_PROXY"),
        ("ROUTING_HTTP_PROXY_MISSING", "HTTP_PROXY"),
        ("ROUTING_ALL_PROXY_MISSING", "ALL_PROXY"),
        ("ROUTING_NO_PROXY_MISSING", "NO_PROXY"),
        ("ROUTING_WSS_NORMALIZATION_MISSING", "strip_prefix(\"wss://\")"),
        ("ROUTING_WS_NORMALIZATION_MISSING", "strip_prefix(\"ws://\")"),
        ("ROUTING_PROXY_REDACTION_MISSING", "<redacted>"),
        ("ROUTING_FACTORY_MISSING", "pub struct HttpClientFactory"),
    )
    complete = _require(diagnostics, outbound, tokens, entity="routing_transport.outbound")
    return {
        "policies": {
            "reqwest_default": "preserve transport-native proxy behavior",
            "respect_system_proxy": "resolve platform system/PAC/WPAD first, environment proxy second, direct last",
        },
        "routes": ["transport_default", "direct", "proxy"],
        "environment_fallback": {
            "https": ["HTTPS_PROXY", "ALL_PROXY"],
            "wss": ["HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"],
            "http_or_ws": ["HTTP_PROXY", "ALL_PROXY"],
            "other": ["ALL_PROXY"],
            "bypass": "NO_PROXY is attached to an environment-selected proxy route",
        },
        "scheme_normalization": "wss resolves system proxy as https; ws resolves as http",
        "failure_behavior": "system proxy unavailability falls back, but a failure after selecting a concrete proxy route does not retry alternate PAC/proxy/direct candidates",
        "privacy": "concrete proxy URLs and no-proxy data are redacted from debug output",
        "evidence": _evidence(outbound, "OutboundProxyPolicy/HttpClientFactory/resolve_proxy_route"),
    }, complete


class RoutingTransportExtractor:
    extractor_id = EXTRACTOR_ID
    source_spec_ids = tuple(SOURCE_IDS.values())

    def extract(self, snapshot: SourceSnapshot, diagnostics: DiagnosticCollector) -> ExtractorResult:
        sources = {key: _source(snapshot, key) for key in SOURCE_IDS}
        missing = [key for key, source in sources.items() if source is None]
        if missing:
            for key in missing:
                _missing(
                    diagnostics,
                    code="ROUTING_TRANSPORT_SOURCE_UNAVAILABLE",
                    token=key,
                    source=None,
                    entity=f"routing_transport.source.{key}",
                )
            return ExtractorResult(
                extractor_id=EXTRACTOR_ID,
                schema_version=SCHEMA_VERSION,
                data={},
                semantic_complete=False,
                source_spec_ids=self.source_spec_ids,
            )

        managed, managed_ok = _managed_proxy(
            sources["proxy_spec"], sources["requirements"], diagnostics  # type: ignore[arg-type]
        )
        runtime, runtime_ok = _proxy_runtime(sources["proxy_config"], diagnostics)  # type: ignore[arg-type]
        outbound, outbound_ok = _outbound(sources["outbound"], diagnostics)  # type: ignore[arg-type]
        complete = managed_ok and runtime_ok and outbound_ok
        body: dict[str, Any] = {
            "$schema": SCHEMA_ID,
            "schema_version": SCHEMA_VERSION,
            "ownership": {
                "owns": [
                    "managed proxy/controller policy composition",
                    "proxy listener and network-mode semantics",
                    "domain/unix-socket routing constraints",
                    "network-approval routing hook placement",
                    "system/environment/direct outbound proxy route selection",
                    "HTTP/WebSocket proxy scheme normalization",
                ],
                "does_not_own": [
                    "permission-profile selection or network sandbox authority",
                    "exec-policy command approval semantics",
                    "child-process environment construction",
                    "environment identity/cwd/shell selection",
                    "provider protocol schemas or application endpoint semantics",
                    "plugin or MCP capability semantics",
                ],
            },
            "managed_proxy": managed,
            "proxy_runtime": runtime,
            "outbound_proxy": outbound,
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
def _factory() -> RoutingTransportExtractor:
    return RoutingTransportExtractor()
