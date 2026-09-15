from __future__ import annotations

from codex_wire_audit.diagnostics import DiagnosticCollector
from codex_wire_audit.extractors.routing_transport import RoutingTransportExtractor
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
        roles=("routing_transport",),
        expected_symbols=(),
        extractor_ids=("extractor.routing_transport",),
    )
    return SourceFile.create(spec=spec, selected_path=path, raw_bytes=text.encode())


def _snapshot(*, omit: str | None = None, break_outbound: bool = False) -> SourceSnapshot:
    proxy_spec = """
    pub struct NetworkProxySpec pub async fn start_proxy fn apply_requirements
    validate_policy_against_constraints pub fn environment_policy pub(crate) fn for_environment
    compiled_network_domains NetworkPolicyDecider enable_network_approval_flow hard_deny_allowlist_misses
    """
    requirements = """
    pub struct NetworkRequirementsToml managed_allowed_domains_only header_injections
    allow_upstream_proxy http_port socks_port unix_sockets
    """
    proxy_config = """
    pub struct NetworkProxyConfig pub enum NetworkDomainPermission None < Allow < Deny
    pub enum NetworkMode matches!(method, "GET" | "HEAD" | "OPTIONS")
    http://127.0.0.1:3128 http://127.0.0.1:8081 fn clamp_non_loopback
    unix socket proxying is enabled pub fn resolve_runtime pub fn managed_proxy_ports
    """
    outbound = """
    pub enum OutboundProxyPolicy ReqwestDefault RespectSystemProxy
    pub enum OutboundProxyRoute SystemProxyDecision::Unavailable
    HTTPS_PROXY HTTP_PROXY ALL_PROXY NO_PROXY strip_prefix("wss://") strip_prefix("ws://")
    <redacted> pub struct HttpClientFactory
    """
    if break_outbound:
        outbound = outbound.replace("RespectSystemProxy", "")
    rows = {
        "proxy_spec": _file(
            "source_spec.extra.routing_proxy_spec", "routing_proxy_spec",
            "codex-rs/core/src/config/network_proxy_spec.rs", proxy_spec,
        ),
        "requirements": _file(
            "source_spec.extra.routing_requirements", "routing_requirements",
            "codex-rs/config/src/config_requirements.rs", requirements,
        ),
        "proxy_config": _file(
            "source_spec.extra.routing_proxy_config", "routing_proxy_config",
            "codex-rs/network-proxy/src/config.rs", proxy_config,
        ),
        "outbound": _file(
            "source_spec.extra.routing_outbound_proxy", "routing_outbound_proxy",
            "codex-rs/http-client/src/outbound_proxy.rs", outbound,
        ),
    }
    if omit:
        rows.pop(omit)
    files = {value.spec_id: value for value in rows.values()}
    revision = SourceRevision(
        "fixture", "openai/codex", "fixture", "1" * 40,
        SourceSnapshot.digest_files(files), False,
    )
    return SourceSnapshot(revision, files)


def test_default_registry_assigns_routing_sources_to_routing_domain():
    registry = build_registry(load_legacy_modules())
    expected = {
        "source_spec.extra.routing_proxy_spec",
        "source_spec.extra.routing_proxy_config",
        "source_spec.extra.routing_requirements",
        "source_spec.extra.routing_outbound_proxy",
    }
    observed = {
        spec.id for spec in registry.specs
        if "extractor.routing_transport" in spec.extractor_ids
    }
    assert observed == expected
    assert all(registry.get(spec_id).roles == ("routing_transport",) for spec_id in expected)


def test_routing_transport_extracts_proxy_semantics_without_stealing_authority():
    diagnostics = DiagnosticCollector()
    result = RoutingTransportExtractor().extract(_snapshot(), diagnostics)
    assert result.semantic_complete
    assert diagnostics.summary()["error"] == 0
    assert result.data["$schema"].endswith("routing-transport-semantics-v1.schema.json")
    assert result.data["proxy_runtime"]["domain_precedence"].startswith("for duplicate domain patterns deny")
    assert result.data["outbound_proxy"]["policies"]["respect_system_proxy"].startswith("resolve platform system")
    assert result.data["outbound_proxy"]["environment_fallback"]["wss"] == ["HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"]
    assert "permission-profile selection or network sandbox authority" in result.data["ownership"]["does_not_own"]
    assert "child-process environment construction" in result.data["ownership"]["does_not_own"]
    assert len(result.data["semantic_digest"]) == 64


def test_missing_routing_source_fails_closed():
    diagnostics = DiagnosticCollector()
    result = RoutingTransportExtractor().extract(_snapshot(omit="requirements"), diagnostics)
    assert not result.semantic_complete
    assert result.data == {}
    assert any(item.code == "ROUTING_TRANSPORT_SOURCE_UNAVAILABLE" for item in diagnostics.values())


def test_outbound_route_drift_is_error_not_fallback():
    diagnostics = DiagnosticCollector()
    result = RoutingTransportExtractor().extract(_snapshot(break_outbound=True), diagnostics)
    assert not result.semantic_complete
    assert any(item.code == "ROUTING_SYSTEM_PROXY_POLICY_MISSING" for item in diagnostics.values())


def test_routing_source_identity_is_exact():
    registry = build_registry(load_legacy_modules())
    assert registry.get("source_spec.extra.routing_proxy_spec").primary_path == "codex-rs/core/src/config/network_proxy_spec.rs"
    assert registry.get("source_spec.extra.routing_proxy_config").primary_path == "codex-rs/network-proxy/src/config.rs"
    assert registry.get("source_spec.extra.routing_outbound_proxy").primary_path == "codex-rs/http-client/src/outbound_proxy.rs"
