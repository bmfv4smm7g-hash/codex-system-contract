"""Canonical extraction for Codex plugin runtime capability composition.

This domain owns plugin package identity, manifest capability declaration,
configured/remote-installed plugin loading, active capability projection, and
explicit plugin mention selection. MCP transport, app execution, skill behavior,
prompt message placement, and network routing remain separate domains.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ..diagnostics import DiagnosticCollector
from ..models import SourceFile, SourceSnapshot
from .registry import ExtractorResult, register_extractor

EXTRACTOR_ID = "extractor.plugin_runtime"
SCHEMA_VERSION = "1.0.0"
SCHEMA_ID = "https://schemas.codex-system-contract.invalid/plugin/plugin-runtime-semantics-v1.schema.json"
SOURCE_IDS = {
    "model": "source_spec.extra.plugin_model",
    "outcome": "source_spec.extra.plugin_load_outcome",
    "manifest": "source_spec.extra.plugin_manifest",
    "loader": "source_spec.extra.plugin_loader",
    "manager": "source_spec.extra.plugin_manager",
    "mentions": "source_spec.extra.plugin_mentions",
    "injection": "source_spec.extra.plugin_injection",
    "render": "source_spec.extra.plugin_render",
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
    message: str,
    source: SourceFile | None,
    entity: str,
) -> None:
    diagnostics.emit(
        code=code,
        severity="error",
        category="plugin_runtime",
        message=message,
        extractor_id=EXTRACTOR_ID,
        entity_id=entity,
        source_refs=[source.spec_id] if source else [],
        details={"path": source.selected_path} if source else {},
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
            _missing(
                diagnostics,
                code=code,
                message=f"Required plugin-runtime source token is missing: {token}",
                source=source,
                entity=entity,
            )
    return complete


def _source(snapshot: SourceSnapshot, key: str) -> SourceFile | None:
    return snapshot.files.get(SOURCE_IDS[key])


def _model(
    model: SourceFile,
    outcome: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[dict[str, Any], bool]:
    model_tokens = (
        ("PLUGIN_CAPABILITY_SUMMARY_MISSING", "pub struct PluginCapabilitySummary"),
        ("PLUGIN_CONFIG_NAME_MISSING", "pub config_name: String"),
        ("PLUGIN_NAMESPACE_MISSING", "pub plugin_namespace: Option<String>"),
        ("PLUGIN_SKILL_CAPABILITY_MISSING", "pub has_skills: bool"),
        ("PLUGIN_MCP_CAPABILITY_MISSING", "pub mcp_server_names: Vec<String>"),
        ("PLUGIN_APP_CAPABILITY_MISSING", "pub app_connector_ids: Vec<AppConnectorId>"),
        ("PLUGIN_APP_DECLARATION_MISSING", "pub struct AppDeclaration"),
        ("PLUGIN_TELEMETRY_METADATA_MISSING", "pub struct PluginTelemetryMetadata"),
    )
    outcome_tokens = (
        ("PLUGIN_LOADED_PLUGIN_MISSING", "pub struct LoadedPlugin<M>"),
        ("PLUGIN_ACTIVE_PREDICATE_MISSING", "self.enabled && self.error.is_none()"),
        ("PLUGIN_OUTCOME_MISSING", "pub struct PluginLoadOutcome<M>"),
        ("PLUGIN_CAPABILITY_PROJECTION_MISSING", "plugin_capability_summary_from_loaded"),
        ("PLUGIN_EFFECTIVE_SKILLS_MISSING", "effective_plugin_skill_roots"),
        ("PLUGIN_EFFECTIVE_MCP_MISSING", "effective_mcp_servers"),
        ("PLUGIN_EFFECTIVE_APPS_MISSING", "effective_apps"),
        ("PLUGIN_EFFECTIVE_HOOKS_MISSING", "effective_plugin_hook_sources"),
        ("PLUGIN_DESCRIPTION_BOUND_MISSING", "MAX_CAPABILITY_SUMMARY_DESCRIPTION_LEN"),
    )
    complete = _require(diagnostics, model, model_tokens, entity="plugin_runtime.model")
    complete &= _require(diagnostics, outcome, outcome_tokens, entity="plugin_runtime.outcome")
    return {
        "identity": {
            "config_name": "full configured plugin ID; host plugins conventionally use <plugin>@<marketplace>",
            "display_name": "manifest name when available, otherwise config_name",
            "plugin_namespace": "namespace used to associate plugin-owned skills",
            "remote_plugin_id": "optional backend identity retained separately from local config identity",
        },
        "active_predicate": "enabled && load error is absent",
        "capability_summary": {
            "fields": ["config_name", "display_name", "plugin_namespace", "description", "has_skills", "mcp_server_names", "app_connector_ids"],
            "emitted_only_when": "active plugin has at least one enabled skill, MCP server, or app connector",
            "description_normalization": "collapse whitespace and bound to 1024 characters",
        },
        "effective_views": [
            "deduplicated plugin skill roots with identity/namespace",
            "MCP server config association from active plugins",
            "deduplicated app connector IDs from active plugins",
            "hook sources and warnings from active plugins",
        ],
        "evidence": {
            "model": _evidence(model, "PluginCapabilitySummary/PluginTelemetryMetadata"),
            "outcome": _evidence(outcome, "LoadedPlugin/PluginLoadOutcome"),
        },
    }, complete


def _manifest(source: SourceFile, diagnostics: DiagnosticCollector) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("PLUGIN_MANIFEST_FORMAT_MISSING", "enum PluginManifestFormat"),
        ("PLUGIN_LEGACY_FORMAT_MISSING", "Legacy"),
        ("PLUGIN_AGENT_FORMAT_MISSING", "AgentPlugin"),
        ("PLUGIN_RAW_MANIFEST_MISSING", "struct RawPluginManifest"),
        ("PLUGIN_MANIFEST_SKILLS_MISSING", "skills: Option<RawPluginManifestPaths>"),
        ("PLUGIN_MANIFEST_MCP_MISSING", "mcp_servers: Option<RawPluginManifestMcpServers>"),
        ("PLUGIN_MANIFEST_APPS_MISSING", "apps: Option<String>"),
        ("PLUGIN_MANIFEST_HOOKS_MISSING", "hooks: Option<RawPluginManifestHooks>"),
        ("PLUGIN_MANIFEST_INTERFACE_MISSING", "interface: Option<RawPluginManifestInterface>"),
        ("PLUGIN_AGENT_MANIFEST_PATH_MISSING", "AGENT_PLUGIN_MANIFEST_RELATIVE_PATH"),
        ("PLUGIN_OVERLAY_PATH_MISSING", 'plugin_root.join(".codex-plugin/plugin.json")'),
        ("PLUGIN_MANIFEST_PATH_CONFINEMENT_MISSING", "resolve_manifest_path"),
    )
    complete = _require(diagnostics, source, tokens, entity="plugin_runtime.manifest")
    return {
        "formats": ["legacy plugin manifest", "agent plugin manifest"],
        "declared_capabilities": ["skills", "MCP servers", "apps", "hooks", "interface metadata"],
        "agent_plugin_overlay": ".codex-plugin/plugin.json may overlay the agent-plugin manifest path",
        "resource_paths": "resolved through manifest path helpers under the plugin root rather than treated as arbitrary host paths",
        "interface_surface": ["display/developer/category text", "capabilities", "URLs", "default prompts", "brand assets", "screenshots"],
        "evidence": _evidence(source, "load_plugin_manifest_with_format/RawPluginManifest"),
    }, complete


def _loading(
    loader: SourceFile,
    manager: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[dict[str, Any], bool]:
    loader_tokens = (
        ("PLUGIN_LAYER_LOAD_MISSING", "load_plugins_from_layer_stack"),
        ("PLUGIN_ALL_CAPABILITIES_SCOPE_MISSING", "PluginLoadScope::AllCapabilities"),
        ("PLUGIN_HOOKS_ONLY_SCOPE_MISSING", "PluginLoadScope::HooksOnly"),
        ("PLUGIN_REMOTE_CONFIG_MERGE_MISSING", "merge_configured_plugins_with_remote_installed"),
        ("PLUGIN_EXCLUDED_IDS_MISSING", "excluded_plugin_ids.contains(id)"),
        ("PLUGIN_DETERMINISTIC_SORT_MISSING", "sort_unstable_by"),
        ("PLUGIN_DUPLICATE_MCP_WARNING_MISSING", "skipping duplicate plugin MCP server name"),
        ("PLUGIN_SKILL_INVENTORY_MISSING", "load_plugin_skill_inventory"),
        ("PLUGIN_APPS_LOAD_MISSING", "load_plugin_apps_from_manifest"),
        ("PLUGIN_MCP_LOAD_MISSING", "load_plugin_mcp_servers_from_manifest_with_format"),
    )
    manager_tokens = (
        ("PLUGIN_CONFIG_INPUT_MISSING", "pub struct PluginsConfigInput"),
        ("PLUGIN_ENABLED_GATE_MISSING", "if !config.plugins_enabled"),
        ("PLUGIN_MANAGER_LOAD_MISSING", "pub async fn plugins_for_config"),
        ("PLUGIN_SKILL_SNAPSHOT_MISSING", "plugin_skill_snapshots_for_config"),
        ("PLUGIN_REMOTE_FEATURE_GATE_MISSING", "config.remote_plugin_enabled"),
        ("PLUGIN_REMOTE_AUTH_GATE_MISSING", "uses_codex_backend()"),
        ("PLUGIN_EFFECTIVE_CHANGE_MISSING", "pub struct EffectivePluginsChange"),
        ("PLUGIN_LOAD_CACHE_MISSING", "LOADED_PLUGINS_CACHE_CAPACITY"),
    )
    complete = _require(diagnostics, loader, loader_tokens, entity="plugin_runtime.loading.loader")
    complete &= _require(diagnostics, manager, manager_tokens, entity="plugin_runtime.loading.manager")
    return {
        "global_gate": "plugins_enabled=false returns an empty runtime view",
        "configured_inputs": "config-layer plugins are merged with remote-installed plugin config before loading",
        "ordering": "configured plugin keys are sorted before load for deterministic plugin iteration",
        "excluded_plugins": "explicit excluded plugin IDs are removed before load",
        "load_scopes": {
            "all_capabilities": "skills, MCP associations, apps, hooks, and manifest capability state",
            "hooks_only": "hook discovery without loading the other plugin capabilities",
        },
        "remote_catalog_gate": "remote discoverability additionally requires remote_plugin_enabled and Codex-backend auth",
        "cache": "loaded plugin outcomes are cached by runtime configuration; account/auth changes invalidate usable passes",
        "boundary": {
            "remote_service_url_and_http_transport": "contract/routing",
            "MCP server execution/filtering": "contract/mcp",
            "app connector runtime": "future app/connector runtime domain",
            "skill loading semantics": "skill subsystem; plugin retains only ownership association",
        },
        "evidence": {
            "loader": _evidence(loader, "load_plugins_from_layer_stack"),
            "manager": _evidence(manager, "PluginsManager::plugins_for_config"),
        },
    }, complete


def _activation(
    mentions: SourceFile,
    injection: SourceFile,
    render: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[dict[str, Any], bool]:
    mention_tokens = (
        ("PLUGIN_EXPLICIT_MENTIONS_MISSING", "collect_explicit_plugin_mentions"),
        ("PLUGIN_EXPLICIT_IDS_MISSING", "collect_explicit_plugin_ids"),
        ("PLUGIN_ID_MATCH_MISSING", "mentioned_plugin_ids.contains(plugin.config_name.as_str())"),
        ("PLUGIN_MENTION_SIGIL_MISSING", "PLUGIN_TEXT_MENTION_SIGIL"),
        ("PLUGIN_MENTION_KIND_FILTER_MISSING", "ToolMentionKind::Plugin"),
        ("PLUGIN_CONFIG_NAME_FROM_PATH_MISSING", "plugin_config_name_from_path"),
    )
    injection_tokens = (
        ("PLUGIN_INJECTION_BUILDER_MISSING", "build_plugin_injections"),
        ("PLUGIN_VISIBLE_MCP_ASSOCIATION_MISSING", "plugin_display_names"),
        ("PLUGIN_ENABLED_APP_FILTER_MISSING", "connector.is_enabled"),
        ("PLUGIN_APPS_MCP_EXCLUSION_MISSING", "CODEX_APPS_MCP_SERVER_NAME"),
        ("PLUGIN_INSTRUCTION_FRAGMENT_MISSING", "PluginInstructions::new"),
    )
    render_tokens = (
        ("PLUGIN_EXPLICIT_RENDERER_MISSING", "render_explicit_plugin_instructions"),
        ("PLUGIN_INSTRUCTION_BOUND_MISSING", "MAX_EXPLICIT_PLUGIN_INSTRUCTIONS_BYTES"),
        ("PLUGIN_SKILL_PREFIX_MISSING", "Skills from this plugin are prefixed"),
        ("PLUGIN_AVAILABLE_APPS_MISSING", "Apps from this plugin available in this session"),
        ("PLUGIN_AVAILABLE_MCP_MISSING", "MCP servers from this plugin available in this session"),
        ("PLUGIN_EMPTY_CAPABILITY_SUPPRESSION_MISSING", "if lines.len() == 1"),
    )
    complete = _require(diagnostics, mentions, mention_tokens, entity="plugin_runtime.activation.mentions")
    complete &= _require(diagnostics, injection, injection_tokens, entity="plugin_runtime.activation.injection")
    complete &= _require(diagnostics, render, render_tokens, entity="plugin_runtime.activation.render")
    return {
        "selection_identity": "explicit structured/text plugin references resolve to exact config_name IDs, not display-name matching",
        "text_sigil": "plugin plaintext links use the plugin mention sigil rather than the ordinary tool sigil",
        "activation_projection": "explicitly mentioned active plugins are projected to currently visible associated capabilities",
        "visible_associations": {
            "skills": "plugin namespace prefix when the plugin has enabled skills",
            "mcp": "session-visible non-apps MCP servers whose plugin display-name metadata contains the plugin display name",
            "apps": "enabled session connectors whose plugin display-name metadata contains the plugin display name",
        },
        "instruction_bound_bytes": 4096,
        "empty_projection": "no plugin instruction is emitted when the selected plugin has no currently visible associated capability",
        "placement_boundary": "contract/prompt owns where the returned contextual fragment appears in model input",
        "evidence": {
            "mentions": _evidence(mentions, "collect_explicit_plugin_mentions/collect_explicit_plugin_ids"),
            "injection": _evidence(injection, "build_plugin_injections"),
            "render": _evidence(render, "render_explicit_plugin_instructions"),
        },
    }, complete


class PluginRuntimeExtractor:
    extractor_id = EXTRACTOR_ID
    source_spec_ids = tuple(SOURCE_IDS.values())

    def extract(self, snapshot: SourceSnapshot, diagnostics: DiagnosticCollector) -> ExtractorResult:
        sources = {key: _source(snapshot, key) for key in SOURCE_IDS}
        missing = [key for key, source in sources.items() if source is None]
        if missing:
            for key in missing:
                _missing(
                    diagnostics,
                    code="PLUGIN_RUNTIME_SOURCE_UNAVAILABLE",
                    message=f"Plugin runtime source is unavailable: {key}",
                    source=None,
                    entity=f"plugin_runtime.source.{key}",
                )
            return ExtractorResult(
                extractor_id=EXTRACTOR_ID,
                schema_version=SCHEMA_VERSION,
                data={},
                semantic_complete=False,
                source_spec_ids=self.source_spec_ids,
            )

        model, model_ok = _model(sources["model"], sources["outcome"], diagnostics)  # type: ignore[arg-type]
        manifest, manifest_ok = _manifest(sources["manifest"], diagnostics)  # type: ignore[arg-type]
        loading, loading_ok = _loading(sources["loader"], sources["manager"], diagnostics)  # type: ignore[arg-type]
        activation, activation_ok = _activation(
            sources["mentions"], sources["injection"], sources["render"], diagnostics  # type: ignore[arg-type]
        )
        complete = model_ok and manifest_ok and loading_ok and activation_ok
        body: dict[str, Any] = {
            "$schema": SCHEMA_ID,
            "schema_version": SCHEMA_VERSION,
            "ownership": {
                "owns": [
                    "plugin package/config identity",
                    "manifest-declared plugin capability association",
                    "configured and remote-installed plugin load composition",
                    "enabled/error active-plugin predicate",
                    "effective plugin skill/MCP/app/hook associations",
                    "explicit plugin mention resolution",
                    "bounded plugin capability instruction rendering",
                ],
                "does_not_own": [
                    "MCP transport, tool filtering, or tool execution",
                    "app connector execution/runtime policy",
                    "skill content discovery/execution semantics",
                    "prompt/world-state placement of plugin fragments",
                    "plugin marketplace or remote-service HTTP/proxy routing",
                ],
            },
            "model": model,
            "manifest": manifest,
            "loading": loading,
            "activation": activation,
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
def _factory() -> PluginRuntimeExtractor:
    return PluginRuntimeExtractor()
