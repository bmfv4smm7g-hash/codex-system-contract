from __future__ import annotations

from codex_wire_audit.diagnostics import DiagnosticCollector
from codex_wire_audit.extractors.plugin_runtime import PluginRuntimeExtractor
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
        roles=("plugin_runtime",),
        expected_symbols=(),
        extractor_ids=("extractor.plugin_runtime",),
    )
    return SourceFile.create(spec=spec, selected_path=path, raw_bytes=text.encode())


def _snapshot(*, omit: str | None = None, break_mentions: bool = False) -> SourceSnapshot:
    model = '''
    pub struct AppDeclaration
    pub struct PluginCapabilitySummary {
      pub config_name: String,
      pub plugin_namespace: Option<String>,
      pub has_skills: bool,
      pub mcp_server_names: Vec<String>,
      pub app_connector_ids: Vec<AppConnectorId>,
    }
    pub struct PluginTelemetryMetadata
    '''
    outcome = '''
    const MAX_CAPABILITY_SUMMARY_DESCRIPTION_LEN: usize = 1024;
    pub struct LoadedPlugin<M>
    self.enabled && self.error.is_none()
    pub struct PluginLoadOutcome<M>
    plugin_capability_summary_from_loaded
    effective_plugin_skill_roots effective_mcp_servers effective_apps effective_plugin_hook_sources
    '''
    manifest = '''
    enum PluginManifestFormat { Legacy, AgentPlugin }
    struct RawPluginManifest {
      skills: Option<RawPluginManifestPaths>,
      mcp_servers: Option<RawPluginManifestMcpServers>,
      apps: Option<String>,
      hooks: Option<RawPluginManifestHooks>,
      interface: Option<RawPluginManifestInterface>,
    }
    AGENT_PLUGIN_MANIFEST_RELATIVE_PATH
    plugin_root.join(".codex-plugin/plugin.json")
    resolve_manifest_path
    '''
    loader = '''
    load_plugins_from_layer_stack
    PluginLoadScope::AllCapabilities PluginLoadScope::HooksOnly
    merge_configured_plugins_with_remote_installed
    excluded_plugin_ids.contains(id)
    sort_unstable_by
    skipping duplicate plugin MCP server name
    load_plugin_skill_inventory load_plugin_apps_from_manifest
    load_plugin_mcp_servers_from_manifest_with_format
    '''
    manager = '''
    pub struct PluginsConfigInput
    if !config.plugins_enabled
    pub async fn plugins_for_config
    plugin_skill_snapshots_for_config
    config.remote_plugin_enabled
    uses_codex_backend()
    pub struct EffectivePluginsChange
    LOADED_PLUGINS_CACHE_CAPACITY
    '''
    mentions = '''
    collect_explicit_plugin_mentions collect_explicit_plugin_ids
    mentioned_plugin_ids.contains(plugin.config_name.as_str())
    PLUGIN_TEXT_MENTION_SIGIL ToolMentionKind::Plugin plugin_config_name_from_path
    '''
    if break_mentions:
        mentions = mentions.replace("mentioned_plugin_ids.contains(plugin.config_name.as_str())", "")
    injection = '''
    build_plugin_injections
    plugin_display_names connector.is_enabled CODEX_APPS_MCP_SERVER_NAME
    PluginInstructions::new
    '''
    render = '''
    const MAX_EXPLICIT_PLUGIN_INSTRUCTIONS_BYTES: usize = 4 * 1024;
    render_explicit_plugin_instructions
    Skills from this plugin are prefixed
    Apps from this plugin available in this session
    MCP servers from this plugin available in this session
    if lines.len() == 1
    '''
    rows = {
        "model": _file("source_spec.extra.plugin_model", "plugin_model", "codex-rs/plugin/src/lib.rs", model),
        "outcome": _file("source_spec.extra.plugin_load_outcome", "plugin_load_outcome", "codex-rs/plugin/src/load_outcome.rs", outcome),
        "manifest": _file("source_spec.extra.plugin_manifest", "plugin_manifest", "codex-rs/core-plugins/src/manifest.rs", manifest),
        "loader": _file("source_spec.extra.plugin_loader", "plugin_loader", "codex-rs/core-plugins/src/loader.rs", loader),
        "manager": _file("source_spec.extra.plugin_manager", "plugin_manager", "codex-rs/core-plugins/src/manager.rs", manager),
        "mentions": _file("source_spec.extra.plugin_mentions", "plugin_mentions", "codex-rs/core/src/plugins/mentions.rs", mentions),
        "injection": _file("source_spec.extra.plugin_injection", "plugin_injection", "codex-rs/core/src/plugins/injection.rs", injection),
        "render": _file("source_spec.extra.plugin_render", "plugin_render", "codex-rs/core/src/plugins/render.rs", render),
    }
    if omit:
        rows.pop(omit)
    files = {value.spec_id: value for value in rows.values()}
    revision = SourceRevision(
        "fixture", "openai/codex", "fixture", "2" * 40,
        SourceSnapshot.digest_files(files), False,
    )
    return SourceSnapshot(revision, files)


def test_default_registry_assigns_plugin_sources_to_plugin_domain():
    registry = build_registry(load_legacy_modules())
    expected = {
        "source_spec.extra.plugin_model",
        "source_spec.extra.plugin_load_outcome",
        "source_spec.extra.plugin_manifest",
        "source_spec.extra.plugin_loader",
        "source_spec.extra.plugin_manager",
        "source_spec.extra.plugin_mentions",
        "source_spec.extra.plugin_injection",
        "source_spec.extra.plugin_render",
    }
    observed = {
        spec.id for spec in registry.specs if "extractor.plugin_runtime" in spec.extractor_ids
    }
    assert observed == expected
    assert all(registry.get(spec_id).roles == ("plugin_runtime",) for spec_id in expected)


def test_plugin_runtime_extracts_capabilities_without_claiming_transport():
    diagnostics = DiagnosticCollector()
    result = PluginRuntimeExtractor().extract(_snapshot(), diagnostics)
    assert result.semantic_complete
    assert diagnostics.summary()["error"] == 0
    assert result.data["model"]["active_predicate"] == "enabled && load error is absent"
    assert result.data["activation"]["instruction_bound_bytes"] == 4096
    assert "MCP transport, tool filtering, or tool execution" in result.data["ownership"]["does_not_own"]
    assert "plugin marketplace or remote-service HTTP/proxy routing" in result.data["ownership"]["does_not_own"]
    assert len(result.data["semantic_digest"]) == 64


def test_missing_plugin_source_fails_closed():
    diagnostics = DiagnosticCollector()
    result = PluginRuntimeExtractor().extract(_snapshot(omit="loader"), diagnostics)
    assert not result.semantic_complete
    assert result.data == {}
    assert any(item.code == "PLUGIN_RUNTIME_SOURCE_UNAVAILABLE" for item in diagnostics.values())


def test_plugin_identity_matching_drift_is_error():
    diagnostics = DiagnosticCollector()
    result = PluginRuntimeExtractor().extract(_snapshot(break_mentions=True), diagnostics)
    assert not result.semantic_complete
    assert any(item.code == "PLUGIN_ID_MATCH_MISSING" for item in diagnostics.values())


def test_plugin_source_identity_cannot_be_repurposed_by_overlay():
    registry = build_registry(load_legacy_modules())
    spec = registry.get("source_spec.extra.plugin_model")
    assert spec.primary_path == "codex-rs/plugin/src/lib.rs"
    assert spec.legacy_key == "plugin_model"
    assert spec.group is SourceGroup.EXTRA
