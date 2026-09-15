"""Canonical extraction for model-visible prompt/context composition.

This domain owns composition and instruction-placement semantics only. Permission
policy, environment contents, plugin internals, and MCP transport remain owned by
their respective domains; this extractor records only their prompt contribution
slots and gates.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ..diagnostics import DiagnosticCollector
from ..models import SourceFile, SourceSnapshot
from .registry import ExtractorResult, register_extractor

EXTRACTOR_ID = "extractor.prompt_context"
SCHEMA_VERSION = "1.0.0"
SCHEMA_ID = "https://schemas.codex-system-contract.invalid/prompt/prompt-context-semantics-v1.schema.json"
SOURCE_IDS = {
    "world_state": "source_spec.extra.prompt_world_state",
    "session": "source_spec.extra.prompt_session_context",
    "turn": "source_spec.extra.prompt_turn",
    "debug": "source_spec.extra.prompt_debug",
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
        category="prompt_context",
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
                message=f"Required prompt-context source token is missing: {token}",
                source=source,
                entity=entity,
            )
    return complete


def _source(snapshot: SourceSnapshot, key: str) -> SourceFile | None:
    return snapshot.files.get(SOURCE_IDS[key])


def _world_state(source: SourceFile, diagnostics: DiagnosticCollector) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("PROMPT_MODEL_INSTRUCTIONS_STATE_MISSING", "ModelInstructionsState::new"),
        ("PROMPT_PERSONALITY_STATE_MISSING", "PersonalityState::new"),
        ("PROMPT_TOKEN_BUDGET_CONTEXT_MISSING", "TokenBudgetContext::new"),
        ("PROMPT_CONTEXT_WINDOW_GUIDANCE_MISSING", "ContextWindowGuidanceState::new"),
        ("PROMPT_REALTIME_STATE_MISSING", "RealtimeState::new"),
        ("PROMPT_AGENTS_MD_STATE_MISSING", "AgentsMdState::new"),
        ("PROMPT_PERMISSIONS_STATE_MISSING", "PermissionsState::new"),
        ("PROMPT_COMPACT_PERMISSIONS_STATE_MISSING", "CompactPermissionsState::new"),
        ("PROMPT_COLLABORATION_STATE_MISSING", "CollaborationModeState::from_collaboration_mode"),
        ("PROMPT_PERSISTENT_MODE_STATE_MISSING", "PersistentModeState::new"),
        ("PROMPT_ENVIRONMENT_STATE_MISSING", "EnvironmentsState::from_turn_context_with_environments"),
        ("PROMPT_ENVIRONMENT_INSTRUCTIONS_STATE_MISSING", "EnvironmentsInstructionsState::new"),
        ("PROMPT_APPS_INSTRUCTIONS_STATE_MISSING", "AppsInstructionsState::new"),
        ("PROMPT_PLUGINS_INSTRUCTIONS_STATE_MISSING", "PluginsInstructionsState::new"),
        ("PROMPT_DEFERRED_TOOLS_STATE_MISSING", "ToolsState::new"),
        ("PROMPT_EXTENSION_WORLD_STATE_MISSING", "contribute_world_state"),
        ("PROMPT_MULTI_AGENT_USAGE_STATE_MISSING", "MultiAgentUsageHintState::new"),
        ("PROMPT_MULTI_AGENT_MODE_STATE_MISSING", "MultiAgentModeState::new"),
        ("PROMPT_MANAGED_DEVELOPER_STATE_MISSING", "ManagedDeveloperInstructionsState::new"),
    )
    complete = _require(diagnostics, source, tokens, entity="prompt_context.world_state")
    order_tokens = [token for _, token in tokens]
    positions = {token: source.text.find(token) for token in order_tokens}
    # MultiAgentModeState is constructed before its usage hint but added after it;
    # construction order is therefore not final message order. Preserve a semantic
    # order instead of pretending source-expression order is wire order.
    return {
        "builder": "Session::build_world_state_for_step",
        "sections": [
            "model_instructions",
            "personality",
            "token_budget",
            "context_window_guidance",
            "realtime",
            "agents_md",
            "permissions_or_compact_permissions",
            "collaboration_mode",
            "persistent_mode",
            "environment_context",
            "environment_instructions",
            "apps_instructions",
            "plugins_instructions",
            "deferred_tools",
            "extension_sections",
            "multi_agent_usage_hint",
            "multi_agent_mode",
            "managed_developer_instructions",
        ],
        "gates": {
            "personality": "Feature::Personality",
            "token_budget": "Feature::TokenBudget + resolved context window",
            "permissions": "include_permissions_instructions; otherwise compact permissions",
            "collaboration_mode": "include_collaboration_mode_instructions",
            "environment_context": "include_environment_context",
            "environment_instructions": "include_environment_context && Feature::DeferredExecutor",
            "apps_instructions": "include_apps_instructions && apps_enabled && accessible enabled app && model flag",
            "plugins_instructions": "plugins_available && model include_plugin_usage_instructions",
            "deferred_tools": "Feature::DeferredToolWorldState",
            "managed_developer_instructions": "non-basic session source + managed requirement value",
        },
        "construction_token_offsets": positions,
        "evidence": _evidence(source, "Session::build_world_state_for_step"),
    }, complete


def _initial_context(source: SourceFile, diagnostics: DiagnosticCollector) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("PROMPT_INITIAL_CONTEXT_BUILDER_MISSING", "build_initial_context_with_world_state"),
        ("PROMPT_DEVELOPER_BUCKET_MISSING", "developer_sections"),
        ("PROMPT_CONTEXTUAL_USER_BUCKET_MISSING", "contextual_user_sections"),
        ("PROMPT_SEPARATE_DEVELOPER_BUCKET_MISSING", "separate_developer_sections"),
        ("PROMPT_WORLD_STATE_FULL_RENDER_MISSING", "world_state.render_full()"),
        ("PROMPT_MODEL_SWITCH_ISOLATION_MISSING", "ModelSwitchInstructions::type_markers"),
        ("PROMPT_MULTI_AGENT_ROLE_ISOLATION_MISSING", "MultiAgentRoleInstructions::type_markers"),
        ("PROMPT_MANAGED_DEVELOPER_ISOLATION_MISSING", "ManagedDeveloperInstructions::type_markers"),
        ("PROMPT_GUARDIAN_POLICY_MISSING", "GuardianPolicy::new"),
        ("PROMPT_WORLD_STATE_DELTA_PATH_MISSING", "update_world_state"),
    )
    complete = _require(diagnostics, source, tokens, entity="prompt_context.initial_context")
    return {
        "builder": "Session::build_initial_context_with_world_state",
        "full_context_source": "WorldState::render_full",
        "message_buckets": {
            "developer": "compatible developer fragments coalesce",
            "separate_developer": "isolation-required developer fragments remain separate messages",
            "contextual_user": "compatible contextual-user fragments coalesce",
        },
        "special_ordering": [
            "model-switch instructions are promoted within the developer bundle",
            "multi-agent role instructions remain separate",
            "active multi-agent mode follows its usage hint",
            "guardian developer policy may remain isolated",
            "managed developer instructions are emitted separately at the end",
        ],
        "later_context": "WorldState snapshot/delta update; unchanged fragments remain in history",
        "evidence": _evidence(source, "build_initial_context_with_world_state"),
    }, complete


def _base_instructions(source: SourceFile, diagnostics: DiagnosticCollector) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("PROMPT_BASE_INSTRUCTIONS_ACCESSOR_MISSING", "get_base_instructions"),
        ("PROMPT_REQUEST_BASE_INSTRUCTIONS_MISSING", "get_prompt_base_instructions"),
        ("PROMPT_MODEL_PROVENANCE_MISSING", "BaseInstructionsProvenance::Model"),
        ("PROMPT_UPDATE_PLAN_FILTER_MISSING", "without_update_plan_instructions"),
    )
    complete = _require(diagnostics, source, tokens, entity="prompt_context.base_instructions")
    return {
        "session_accessor": "get_base_instructions",
        "request_accessor": "get_prompt_base_instructions",
        "request_copy_mutates_persisted_value": False,
        "request_filter": {
            "effect": "remove update_plan guidance from model-provenance instructions",
            "when": "update_plan disabled && no model catalog && provenance is Model",
        },
        "evidence": _evidence(source, "get_prompt_base_instructions"),
    }, complete


def _sampling(source: SourceFile, diagnostics: DiagnosticCollector) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("PROMPT_BUILD_PROMPT_MISSING", "pub(crate) fn build_prompt"),
        ("PROMPT_TOOL_ROUTER_MISSING", "model_visible_specs"),
        ("PROMPT_HISTORY_FOR_PROMPT_MISSING", "for_prompt"),
        ("PROMPT_CONTEXT_UPDATE_MISSING", "record_context_updates_and_set_reference_context_item"),
        ("PROMPT_SKILL_PLUGIN_BUILD_MISSING", "build_skills_and_plugins"),
        ("PROMPT_PLUGIN_INJECTION_HOOK_MISSING", "build_plugin_injections"),
        ("PROMPT_SKILL_INVOCATION_HOOK_MISSING", "emit_explicit_skill_invocations"),
    )
    complete = _require(diagnostics, source, tokens, entity="prompt_context.sampling")
    return {
        "prompt_builder": "build_prompt",
        "input": "clone_history().for_prompt(model input modalities)",
        "base_instructions": "request-scoped BaseInstructions",
        "tools": "captured StepContext ToolRouter model_visible_specs",
        "step_consistency": "context, advertised tools, and tool calls share one captured request view",
        "injection_hooks": {
            "skills_and_plugins": "build_skills_and_plugins before sampling history is cloned",
            "plugin_internals_owned_by": "contract/plugin",
            "skill_selection_semantics_owned_by": "contract/prompt",
        },
        "evidence": _evidence(source, "build_prompt/run_turn"),
    }, complete


def _debug(source: SourceFile, diagnostics: DiagnosticCollector) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("PROMPT_DEBUG_ENTRYPOINT_MISSING", "build_prompt_input_from_session"),
        ("PROMPT_DEBUG_STEP_CAPTURE_MISSING", "capture_step_context"),
        ("PROMPT_DEBUG_CONTEXT_UPDATE_MISSING", "record_context_updates_and_set_reference_context_item"),
        ("PROMPT_DEBUG_HISTORY_PROJECTION_MISSING", "for_prompt"),
        ("PROMPT_DEBUG_PROMPT_BUILDER_MISSING", "build_prompt"),
    )
    complete = _require(diagnostics, source, tokens, entity="prompt_context.debug")
    return {
        "entrypoint": "build_prompt_input_from_session",
        "scope": "debug construction of model-visible input without entering full production run_turn",
        "production_equivalence_limit": "hooks, retries, compaction, plugin activation and other production turn behavior remain outside this helper",
        "evidence": _evidence(source, "build_prompt_input_from_session"),
    }, complete


class PromptContextExtractor:
    extractor_id = EXTRACTOR_ID
    source_spec_ids = tuple(SOURCE_IDS.values())

    def extract(self, snapshot: SourceSnapshot, diagnostics: DiagnosticCollector) -> ExtractorResult:
        sources = {key: _source(snapshot, key) for key in SOURCE_IDS}
        missing = [key for key, source in sources.items() if source is None]
        if missing:
            for key in missing:
                _missing(
                    diagnostics,
                    code="PROMPT_CONTEXT_SOURCE_UNAVAILABLE",
                    message=f"Prompt/context source is unavailable: {key}",
                    source=None,
                    entity=f"prompt_context.source.{key}",
                )
            return ExtractorResult(
                extractor_id=EXTRACTOR_ID,
                schema_version=SCHEMA_VERSION,
                data={},
                semantic_complete=False,
                source_spec_ids=self.source_spec_ids,
            )

        world, world_ok = _world_state(sources["world_state"], diagnostics)  # type: ignore[arg-type]
        initial, initial_ok = _initial_context(sources["session"], diagnostics)  # type: ignore[arg-type]
        base, base_ok = _base_instructions(sources["session"], diagnostics)  # type: ignore[arg-type]
        sampling, sampling_ok = _sampling(sources["turn"], diagnostics)  # type: ignore[arg-type]
        debug, debug_ok = _debug(sources["debug"], diagnostics)  # type: ignore[arg-type]
        complete = world_ok and initial_ok and base_ok and sampling_ok and debug_ok
        body: dict[str, Any] = {
            "$schema": SCHEMA_ID,
            "schema_version": SCHEMA_VERSION,
            "ownership": {
                "owns": [
                    "base-instruction request projection",
                    "world-state contribution ordering and prompt gates",
                    "initial full-context bucketing/isolation",
                    "world-state full-versus-delta composition",
                    "sampling prompt input/tool attachment",
                    "selected skill/plugin injection slots",
                ],
                "does_not_own": [
                    "permission policy semantics",
                    "environment contents or execution authority",
                    "plugin discovery/runtime internals",
                    "MCP transport/filter semantics",
                    "network/proxy routing",
                ],
            },
            "base_instructions": base,
            "world_state": world,
            "initial_context": initial,
            "sampling_request": sampling,
            "debug_projection": debug,
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
def _factory() -> PromptContextExtractor:
    return PromptContextExtractor()
