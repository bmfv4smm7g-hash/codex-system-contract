from __future__ import annotations

from dataclasses import replace

from codex_wire_audit.diagnostics import DiagnosticCollector
from codex_wire_audit.extractors.prompt_context import PromptContextExtractor
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
        roles=("prompt_context",),
        expected_symbols=(),
        extractor_ids=("extractor.prompt_context",),
    )
    return SourceFile.create(spec=spec, selected_path=path, raw_bytes=text.encode())


def _snapshot(*, omit: str | None = None, break_world: bool = False) -> SourceSnapshot:
    world = """
    build_world_state_for_step
    ModelInstructionsState::new PersonalityState::new TokenBudgetContext::new
    ContextWindowGuidanceState::new RealtimeState::new AgentsMdState::new
    PermissionsState::new CompactPermissionsState::new
    CollaborationModeState::from_collaboration_mode PersistentModeState::new
    EnvironmentsState::from_turn_context_with_environments EnvironmentsInstructionsState::new
    AppsInstructionsState::new PluginsInstructionsState::new ToolsState::new
    contribute_world_state MultiAgentUsageHintState::new MultiAgentModeState::new
    ManagedDeveloperInstructionsState::new
    """
    if break_world:
        world = world.replace("AgentsMdState::new", "")
    session = """
    get_base_instructions get_prompt_base_instructions BaseInstructionsProvenance::Model
    without_update_plan_instructions build_initial_context_with_world_state
    developer_sections contextual_user_sections separate_developer_sections
    world_state.render_full() ModelSwitchInstructions::type_markers
    MultiAgentRoleInstructions::type_markers ManagedDeveloperInstructions::type_markers
    GuardianPolicy::new update_world_state
    """
    turn = """
    pub(crate) fn build_prompt model_visible_specs for_prompt
    record_context_updates_and_set_reference_context_item build_skills_and_plugins
    build_plugin_injections emit_explicit_skill_invocations
    """
    debug = """
    build_prompt_input_from_session capture_step_context
    record_context_updates_and_set_reference_context_item for_prompt build_prompt
    """
    rows = {
        "world_state": _file(
            "source_spec.extra.prompt_world_state", "prompt_world_state",
            "codex-rs/core/src/session/world_state.rs", world,
        ),
        "session": _file(
            "source_spec.extra.prompt_session_context", "prompt_session_context",
            "codex-rs/core/src/session/mod.rs", session,
        ),
        "turn": _file(
            "source_spec.extra.prompt_turn", "prompt_turn",
            "codex-rs/core/src/session/turn.rs", turn,
        ),
        "debug": _file(
            "source_spec.extra.prompt_debug", "prompt_debug",
            "codex-rs/core/src/prompt_debug.rs", debug,
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


def test_default_registry_assigns_prompt_sources_to_prompt_domain():
    registry = build_registry(load_legacy_modules())
    expected = {
        "source_spec.extra.prompt_world_state",
        "source_spec.extra.prompt_session_context",
        "source_spec.extra.prompt_turn",
        "source_spec.extra.prompt_debug",
    }
    observed = {
        spec.id
        for spec in registry.specs
        if "extractor.prompt_context" in spec.extractor_ids
    }
    assert observed == expected
    assert all(registry.get(spec_id).roles == ("prompt_context",) for spec_id in expected)


def test_prompt_context_extracts_composition_without_claiming_other_domains():
    diagnostics = DiagnosticCollector()
    result = PromptContextExtractor().extract(_snapshot(), diagnostics)
    assert result.semantic_complete
    assert diagnostics.summary()["error"] == 0
    assert result.data["$schema"].endswith("prompt-context-semantics-v1.schema.json")
    assert result.data["world_state"]["sections"][5] == "agents_md"
    assert result.data["world_state"]["gates"]["environment_context"] == "include_environment_context"
    assert result.data["initial_context"]["message_buckets"]["separate_developer"].startswith("isolation-required")
    assert result.data["sampling_request"]["tools"].startswith("captured StepContext ToolRouter")
    assert "permission policy semantics" in result.data["ownership"]["does_not_own"]
    assert "network/proxy routing" in result.data["ownership"]["does_not_own"]
    assert len(result.data["semantic_digest"]) == 64


def test_missing_source_fails_closed():
    diagnostics = DiagnosticCollector()
    result = PromptContextExtractor().extract(_snapshot(omit="debug"), diagnostics)
    assert not result.semantic_complete
    assert result.data == {}
    assert any(item.code == "PROMPT_CONTEXT_SOURCE_UNAVAILABLE" for item in diagnostics.values())


def test_source_drift_is_error_not_silent_fallback():
    diagnostics = DiagnosticCollector()
    result = PromptContextExtractor().extract(_snapshot(break_world=True), diagnostics)
    assert not result.semantic_complete
    assert any(item.code == "PROMPT_AGENTS_MD_STATE_MISSING" for item in diagnostics.values())


def test_prompt_source_identity_cannot_be_repurposed_by_overlay():
    registry = build_registry(load_legacy_modules())
    spec = registry.get("source_spec.extra.prompt_world_state")
    assert spec.primary_path == "codex-rs/core/src/session/world_state.rs"
    assert spec.legacy_key == "prompt_world_state"
    assert spec.group is SourceGroup.EXTRA
