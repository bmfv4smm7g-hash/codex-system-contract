from __future__ import annotations

from codex_wire_audit.diagnostics import DiagnosticCollector
from codex_wire_audit.extractors.mcp_projection import McpProjectionExtractor
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
        roles=("mcp_projection",),
        expected_symbols=(),
        extractor_ids=("extractor.mcp_projection",),
    )
    return SourceFile.create(spec=spec, selected_path=path, raw_bytes=text.encode())


def _snapshot(*, omit: str | None = None, break_identity: bool = False) -> SourceSnapshot:
    catalog = """
    pub enum McpServerSource Plugin SelectedPlugin Config Compatibility Extension
    pub struct McpServerRegistration pub enum McpEnvironmentAuthority
    pub struct McpCatalogBuilder build_with_environment_authority
    pub struct ResolvedMcpCatalog pub struct McpServerConflict
    """
    runtime = """
    pub struct McpConfig server_permission_profiles pub fn effective_mcp_servers
    host_owned_codex_apps_enabled for_threadless_operations MCP_TOOL_NAME_PREFIX
    MCP_TOOL_NAME_DELIMITER pub struct ToolPluginProvenance pub fn configured_mcp_servers
    """
    tools = """
    pub struct ToolInfo pub server_name: String pub callable_name: String
    pub callable_namespace: String pub tool: Tool pub fn canonical_tool_name
    pub(crate) struct ToolFilter normalize_tools_for_model_with_prefix
    seen_raw_names colliding_namespaces colliding_tools MAX_TOOL_NAME_LENGTH
    """
    if break_identity:
        tools = tools.replace("seen_raw_names", "")
    exposure = """
    pub(crate) struct McpHandlerCache append_mcp_tools tool_is_model_visible
    AppToolPolicyEvaluator ToolExposure::Direct ToolExposure::Deferred ToolExposure::Hidden
    MAX_AGENT_PLUGIN_MCP_SPEC_BYTES MAX_AGENT_PLUGIN_MCP_TOTAL_BYTES
    """
    plan = """
    append_mcp_tools omit_tools_from direct_only_tool_namespaces
    ToolExposure::CodeModeOnly ToolExposure::DirectModelOnly ToolExposure::DeferredModelOnly
    search_tool_enabled
    """
    handler = """
    pub struct McpHandler self.tool_info.canonical_tool_name() prepare_mcp_call
    &self.tool_info.server_name self.tool_info.tool.name.as_ref()
    handle_mcp_tool_call wait_for_mcp_server mcp_server hook_tool_name
    """
    rows = {
        "catalog": _file("source_spec.extra.mcp_catalog", "mcp_catalog", "codex-rs/codex-mcp/src/catalog.rs", catalog),
        "runtime": _file("source_spec.extra.mcp_runtime", "mcp_runtime", "codex-rs/codex-mcp/src/mcp/mod.rs", runtime),
        "tools": _file("source_spec.extra.mcp_tools", "mcp_tools", "codex-rs/codex-mcp/src/tools.rs", tools),
        "exposure": _file("source_spec.extra.mcp_tool_exposure", "mcp_tool_exposure", "codex-rs/core/src/mcp_tool_exposure.rs", exposure),
        "plan": _file("source_spec.extra.mcp_tool_plan", "mcp_tool_plan", "codex-rs/core/src/tools/spec_plan.rs", plan),
        "handler": _file("source_spec.extra.mcp_handler", "mcp_handler", "codex-rs/core/src/tools/handlers/mcp.rs", handler),
    }
    if omit:
        rows.pop(omit)
    files = {value.spec_id: value for value in rows.values()}
    revision = SourceRevision(
        "fixture", "openai/codex", "fixture", "1" * 40,
        SourceSnapshot.digest_files(files), False,
    )
    return SourceSnapshot(revision, files)


def test_default_registry_assigns_mcp_sources_to_mcp_domain():
    registry = build_registry(load_legacy_modules())
    expected = {
        "source_spec.extra.mcp_catalog",
        "source_spec.extra.mcp_runtime",
        "source_spec.extra.mcp_tools",
        "source_spec.extra.mcp_tool_exposure",
        "source_spec.extra.mcp_tool_plan",
        "source_spec.extra.mcp_handler",
    }
    observed = {
        spec.id for spec in registry.specs
        if "extractor.mcp_projection" in spec.extractor_ids
    }
    assert observed == expected
    assert all("mcp_projection" in registry.get(spec_id).roles for spec_id in expected)
    assert "legacy_extra" in registry.get("source_spec.extra.mcp_catalog").roles
    assert "legacy_extra" in registry.get("source_spec.extra.mcp_runtime").roles
    assert "legacy_extra" in registry.get("source_spec.extra.mcp_handler").roles


def test_mcp_projection_preserves_raw_execution_identity():
    diagnostics = DiagnosticCollector()
    result = McpProjectionExtractor().extract(_snapshot(), diagnostics)
    assert result.semantic_complete
    assert diagnostics.summary()["error"] == 0
    assert result.data["$schema"].endswith("mcp-projection-semantics-v1.schema.json")
    assert result.data["tool_identity"]["identity_invariant"].startswith("normalizing model names")
    assert result.data["execution"]["protocol_target"].startswith("prepare_mcp_call")
    assert "plugin package discovery/loading or capability composition" in result.data["ownership"]["does_not_own"]
    assert "permission-profile or approval-policy authority" in result.data["ownership"]["does_not_own"]
    assert len(result.data["semantic_digest"]) == 64


def test_missing_mcp_source_fails_closed():
    diagnostics = DiagnosticCollector()
    result = McpProjectionExtractor().extract(_snapshot(omit="handler"), diagnostics)
    assert not result.semantic_complete
    assert result.data == {}
    assert any(item.code == "MCP_PROJECTION_SOURCE_UNAVAILABLE" for item in diagnostics.values())


def test_tool_identity_drift_is_error_not_fallback():
    diagnostics = DiagnosticCollector()
    result = McpProjectionExtractor().extract(_snapshot(break_identity=True), diagnostics)
    assert not result.semantic_complete
    assert any(item.code == "MCP_DUPLICATE_IDENTITY_MISSING" for item in diagnostics.values())


def test_mcp_source_identity_is_exact():
    registry = build_registry(load_legacy_modules())
    assert registry.get("source_spec.extra.mcp_catalog").primary_path == "codex-rs/codex-mcp/src/catalog.rs"
    assert registry.get("source_spec.extra.mcp_tools").primary_path == "codex-rs/codex-mcp/src/tools.rs"
    assert registry.get("source_spec.extra.mcp_handler").primary_path == "codex-rs/core/src/tools/handlers/mcp.rs"
