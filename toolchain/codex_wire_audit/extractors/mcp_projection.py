"""Canonical extraction for MCP catalog, model projection, and call routing.

MCP owns server resolution, raw/model tool identity translation, model exposure,
and exact server/tool routing. Plugin package loading, Apps business policy,
permission authority, prompt placement, and generic non-MCP tools stay outside
this domain.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ..diagnostics import DiagnosticCollector
from ..models import SourceFile, SourceSnapshot
from .registry import ExtractorResult, register_extractor

EXTRACTOR_ID = "extractor.mcp_projection"
SCHEMA_VERSION = "1.0.0"
SCHEMA_ID = "https://schemas.codex-system-contract.invalid/mcp/mcp-projection-semantics-v1.schema.json"
SOURCE_IDS = {
    "catalog": "source_spec.extra.mcp_catalog",
    "runtime": "source_spec.extra.mcp_runtime",
    "tools": "source_spec.extra.mcp_tools",
    "exposure": "source_spec.extra.mcp_tool_exposure",
    "plan": "source_spec.extra.mcp_tool_plan",
    "handler": "source_spec.extra.mcp_handler",
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
        category="mcp_projection",
        message=f"Required MCP projection source token is missing: {token}",
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


def _catalog(source: SourceFile, diagnostics: DiagnosticCollector) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("MCP_SERVER_SOURCE_MISSING", "pub enum McpServerSource"),
        ("MCP_REGISTRATION_MISSING", "pub struct McpServerRegistration"),
        ("MCP_ENVIRONMENT_AUTHORITY_MISSING", "pub enum McpEnvironmentAuthority"),
        ("MCP_CATALOG_BUILDER_MISSING", "pub struct McpCatalogBuilder"),
        ("MCP_ENVIRONMENT_FILTER_MISSING", "build_with_environment_authority"),
        ("MCP_RESOLVED_CATALOG_MISSING", "pub struct ResolvedMcpCatalog"),
        ("MCP_CONFLICT_MISSING", "pub struct McpServerConflict"),
        ("MCP_SELECTED_PLUGIN_SOURCE_MISSING", "SelectedPlugin"),
        ("MCP_CONFIG_PRECEDENCE_MISSING", "Config"),
        ("MCP_EXTENSION_SOURCE_MISSING", "Extension"),
    )
    complete = _require(diagnostics, source, tokens, entity="mcp_projection.catalog")
    return {
        "registration_sources": ["plugin", "selected_plugin", "config", "compatibility", "extension"],
        "precedence": "stable precedence resolution produces one immutable winning registration per logical server name; same-tier collisions are retained as conflict evidence",
        "environment_authority": {
            "unrestricted": "selected environment adds no restrictions",
            "selected_plugins_only": "only explicitly selected plugin MCP registrations may use an unattached executor",
            "unavailable": "pending/failed environment disables attachment-owned servers",
            "restricted": "config/compatibility/extension and plugin registrations must satisfy the owner environment MCP policy",
        },
        "disable_semantics": "resolved disabled winners remain disabled; selected-plugin policy applies to its registration rather than becoming a global name veto",
        "plugin_boundary": "plugin identity/attribution is consumed as catalog provenance; plugin package discovery/loading remains contract/plugin owned",
        "evidence": _evidence(source, "McpCatalogBuilder/ResolvedMcpCatalog"),
    }, complete


def _runtime(source: SourceFile, diagnostics: DiagnosticCollector) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("MCP_CONFIG_MISSING", "pub struct McpConfig"),
        ("MCP_SERVER_PERMISSION_MAP_MISSING", "server_permission_profiles"),
        ("MCP_EFFECTIVE_SERVERS_MISSING", "pub fn effective_mcp_servers"),
        ("MCP_AUTH_GATING_MISSING", "host_owned_codex_apps_enabled"),
        ("MCP_THREADLESS_AUTHORITY_MISSING", "for_threadless_operations"),
        ("MCP_RAW_PREFIX_MISSING", "MCP_TOOL_NAME_PREFIX"),
        ("MCP_NAME_DELIMITER_MISSING", "MCP_TOOL_NAME_DELIMITER"),
        ("MCP_PLUGIN_PROVENANCE_MISSING", "pub struct ToolPluginProvenance"),
        ("MCP_CONFIGURED_SERVERS_MISSING", "pub fn configured_mcp_servers"),
    )
    complete = _require(diagnostics, source, tokens, entity="mcp_projection.runtime")
    return {
        "snapshot": "published MCP runtime captures catalog, approval/profile inputs, environment cwd/profile bindings, protocol mode, connector provenance, and naming compatibility settings together",
        "server_authority": "enabled servers receive the exact environment or fallback permission profile selected for that server; threadless discovery/resource reads intentionally receive default authority instead of thread execution authority",
        "apps_auth_gate": "controller-owned codex_apps is present only when Apps are enabled and auth uses the Codex backend",
        "plugin_provenance": "connector/server plugin attribution is retained for display/telemetry without transferring plugin-package ownership to MCP",
        "policy_boundary": "approval and permission profiles are frozen inputs owned by contract/policy; MCP owns how they are bound to MCP runtime/server operations",
        "evidence": _evidence(source, "McpConfig/effective_mcp_servers"),
    }, complete


def _tool_identity(source: SourceFile, diagnostics: DiagnosticCollector) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("MCP_TOOL_INFO_MISSING", "pub struct ToolInfo"),
        ("MCP_RAW_SERVER_NAME_MISSING", "pub server_name: String"),
        ("MCP_CALLABLE_NAME_MISSING", "pub callable_name: String"),
        ("MCP_CALLABLE_NAMESPACE_MISSING", "pub callable_namespace: String"),
        ("MCP_RAW_TOOL_DEFINITION_MISSING", "pub tool: Tool"),
        ("MCP_CANONICAL_NAME_MISSING", "pub fn canonical_tool_name"),
        ("MCP_TOOL_FILTER_MISSING", "pub(crate) struct ToolFilter"),
        ("MCP_MODEL_NORMALIZATION_MISSING", "normalize_tools_for_model_with_prefix"),
        ("MCP_DUPLICATE_IDENTITY_MISSING", "seen_raw_names"),
        ("MCP_NAMESPACE_COLLISION_MISSING", "colliding_namespaces"),
        ("MCP_TOOL_COLLISION_MISSING", "colliding_tools"),
        ("MCP_NAME_LIMIT_MISSING", "MAX_TOOL_NAME_LENGTH"),
    )
    complete = _require(diagnostics, source, tokens, entity="mcp_projection.tool_identity")
    return {
        "raw_identity": "raw server name + raw MCP tool.name are preserved for protocol execution",
        "model_identity": "callable namespace/name are sanitized and represented as canonical ToolName namespace + name",
        "filter_order": "server enabled_tools allowlist and disabled_tools denylist apply to raw MCP tool names before model projection",
        "normalization": "model-visible names are sanitized, deterministic collisions receive hash suffixes, duplicate raw identities are dropped, and final names fit the 128-byte Responses API limit",
        "prefix_compatibility": "legacy mcp__ namespace prefix may be retained globally except for configured non-prefixed servers",
        "identity_invariant": "normalizing model names never replaces the raw server/tool identity used for the actual MCP call",
        "evidence": _evidence(source, "ToolInfo/normalize_tools_for_model_with_prefix"),
    }, complete


def _exposure(
    exposure: SourceFile,
    plan: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[dict[str, Any], bool]:
    exposure_tokens = (
        ("MCP_HANDLER_CACHE_MISSING", "pub(crate) struct McpHandlerCache"),
        ("MCP_APPEND_TO_REGISTRY_MISSING", "append_mcp_tools"),
        ("MCP_MODEL_VISIBLE_FILTER_MISSING", "tool_is_model_visible"),
        ("MCP_APPS_POLICY_MISSING", "AppToolPolicyEvaluator"),
        ("MCP_EXPOSURE_DIRECT_MISSING", "ToolExposure::Direct"),
        ("MCP_EXPOSURE_DEFERRED_MISSING", "ToolExposure::Deferred"),
        ("MCP_EXPOSURE_HIDDEN_MISSING", "ToolExposure::Hidden"),
        ("MCP_AGENT_SPEC_BUDGET_MISSING", "MAX_AGENT_PLUGIN_MCP_SPEC_BYTES"),
        ("MCP_AGENT_TOTAL_BUDGET_MISSING", "MAX_AGENT_PLUGIN_MCP_TOTAL_BYTES"),
    )
    plan_tokens = (
        ("MCP_PLAN_APPEND_MISSING", "append_mcp_tools"),
        ("MCP_OMIT_EXPOSURES_MISSING", "omit_tools_from"),
        ("MCP_DIRECT_ONLY_NAMESPACE_MISSING", "direct_only_tool_namespaces"),
        ("MCP_CODE_MODE_ONLY_MISSING", "ToolExposure::CodeModeOnly"),
        ("MCP_DIRECT_MODEL_ONLY_MISSING", "ToolExposure::DirectModelOnly"),
        ("MCP_DEFERRED_MODEL_ONLY_MISSING", "ToolExposure::DeferredModelOnly"),
        ("MCP_SEARCH_TOOL_GATE_MISSING", "search_tool_enabled"),
    )
    complete = _require(diagnostics, exposure, exposure_tokens, entity="mcp_projection.exposure")
    complete &= _require(diagnostics, plan, plan_tokens, entity="mcp_projection.exposure")
    return {
        "registration": "regular MCP tools that are model-visible are registered first; codex_apps tools additionally require Apps enabled, connector identity, and Apps tool policy",
        "initial_exposure": "tool search enabled starts eligible MCP tools as deferred; otherwise direct",
        "agent_plugin_budget": "agent-plugin MCP specs exceeding per-tool or aggregate model-spec byte budgets are hidden rather than advertised",
        "server_omit_policy": "resolved server omit_tools_from removes direct/deferred/code-mode exposure dimensions before final projection",
        "direct_only_namespace": "configured direct-only namespaces cannot be deferred or code-mode exposed",
        "final_modes": ["hidden", "code_mode_only", "direct_model_only", "direct", "deferred_model_only", "deferred"],
        "apps_boundary": "MCP applies Apps exposure policy to codex_apps tools; connector/plugin discovery and business capability composition remain outside this extractor",
        "prompt_boundary": "ToolRouter is produced here for model/tool execution; placement of its model-visible specs in the request remains contract/prompt owned",
        "evidence": [
            _evidence(exposure, "McpHandlerCache/append_mcp_tools"),
            _evidence(plan, "build_tool_router/apply_mcp_tool_exposure_policy"),
        ],
    }, complete


def _execution(source: SourceFile, diagnostics: DiagnosticCollector) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("MCP_HANDLER_MISSING", "pub struct McpHandler"),
        ("MCP_HANDLER_TOOL_NAME_MISSING", "self.tool_info.canonical_tool_name()"),
        ("MCP_PREPARE_CALL_MISSING", "prepare_mcp_call"),
        ("MCP_RAW_SERVER_ROUTE_MISSING", "&self.tool_info.server_name"),
        ("MCP_RAW_TOOL_ROUTE_MISSING", "self.tool_info.tool.name.as_ref()"),
        ("MCP_HANDLE_CALL_MISSING", "handle_mcp_tool_call"),
        ("MCP_READY_GATE_MISSING", "wait_for_mcp_server"),
        ("MCP_SERVER_TELEMETRY_MISSING", "mcp_server"),
        ("MCP_HOOK_NAME_MISSING", "hook_tool_name"),
    )
    complete = _require(diagnostics, source, tokens, entity="mcp_projection.execution")
    return {
        "model_dispatch_key": "canonical model-visible ToolName",
        "protocol_target": "prepare_mcp_call and execution use preserved raw server_name and raw MCP tool.name",
        "readiness": "tool runtime can wait for its owning MCP server before execution",
        "prepared_call": "runtime authority/output limits are captured in the prepared MCP call before tool execution",
        "hooks_and_telemetry": "hook identity is normalized back to MCP-prefixed naming while telemetry retains raw MCP server origin/name",
        "identity_invariant": "a model-visible collision-safe name cannot redirect the protocol call to a different raw MCP server/tool pair",
        "evidence": _evidence(source, "McpHandler::handle_call"),
    }, complete


class McpProjectionExtractor:
    extractor_id = EXTRACTOR_ID
    source_spec_ids = tuple(SOURCE_IDS.values())

    def extract(self, snapshot: SourceSnapshot, diagnostics: DiagnosticCollector) -> ExtractorResult:
        sources = {key: _source(snapshot, key) for key in SOURCE_IDS}
        missing = [key for key, source in sources.items() if source is None]
        if missing:
            for key in missing:
                _missing(
                    diagnostics,
                    code="MCP_PROJECTION_SOURCE_UNAVAILABLE",
                    token=key,
                    source=None,
                    entity=f"mcp_projection.source.{key}",
                )
            return ExtractorResult(
                extractor_id=EXTRACTOR_ID,
                schema_version=SCHEMA_VERSION,
                data={},
                semantic_complete=False,
                source_spec_ids=self.source_spec_ids,
            )

        catalog, catalog_ok = _catalog(sources["catalog"], diagnostics)  # type: ignore[arg-type]
        runtime, runtime_ok = _runtime(sources["runtime"], diagnostics)  # type: ignore[arg-type]
        identity, identity_ok = _tool_identity(sources["tools"], diagnostics)  # type: ignore[arg-type]
        exposure, exposure_ok = _exposure(
            sources["exposure"], sources["plan"], diagnostics  # type: ignore[arg-type]
        )
        execution, execution_ok = _execution(sources["handler"], diagnostics)  # type: ignore[arg-type]
        complete = catalog_ok and runtime_ok and identity_ok and exposure_ok and execution_ok
        body: dict[str, Any] = {
            "$schema": SCHEMA_ID,
            "schema_version": SCHEMA_VERSION,
            "ownership": {
                "owns": [
                    "MCP server registration resolution and environment authority",
                    "effective MCP runtime/server snapshot",
                    "raw MCP to model-visible tool identity normalization",
                    "MCP tool filter and exposure projection",
                    "MCP raw server/tool execution routing",
                ],
                "does_not_own": [
                    "plugin package discovery/loading or capability composition",
                    "Apps connector business/runtime capability semantics",
                    "permission-profile or approval-policy authority",
                    "prompt ordering or placement of model-visible tool specs",
                    "generic native/hosted/dynamic non-MCP tool definitions",
                    "network proxy transport policy",
                ],
            },
            "catalog": catalog,
            "runtime": runtime,
            "tool_identity": identity,
            "exposure": exposure,
            "execution": execution,
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
def _factory() -> McpProjectionExtractor:
    return McpProjectionExtractor()
