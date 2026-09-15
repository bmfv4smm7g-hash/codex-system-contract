from __future__ import annotations

from codex_wire_audit.diagnostics import DiagnosticCollector
from codex_wire_audit.extractors.environment_execution import EnvironmentExecutionExtractor
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
        roles=("environment_execution",),
        expected_symbols=(),
        extractor_ids=("extractor.environment_execution",),
    )
    return SourceFile.create(spec=spec, selected_path=path, raw_bytes=text.encode())


def _snapshot(*, omit: str | None = None, break_shell_env: bool = False) -> SourceSnapshot:
    selection = """
    pub(crate) enum EnvironmentConfigOrigin
    EnvironmentConfigState::FromThread EnvironmentConfigState::Ready
    resolve_selection_config refresh_thread_config pub(crate) fn update_selections
    seen_environment_ids previous.cwd == selected_environment.cwd
    previous.workspace_roots == selected_environment.workspace_roots
    """
    protocol = """
    pub enum EnvironmentConfigState FromThread Pending Ready(EnvironmentConfig) Failed(String)
    pub struct EnvironmentConfig
    pub workspace_roots: Vec<PathUri>
    pub permission_profile: PermissionProfileSnapshot
    pub shell_environment_policy: ShellEnvironmentPolicy
    pub selected_capability_roots: Vec<SelectedCapabilityRoot>
    """
    turn = """
    pub(crate) struct TurnEnvironment
    pub(crate) fn cwd(&self) -> &PathUri
    pub(crate) fn workspace_roots(&self) -> &[PathUri]
    pub(crate) fn shell_environment_policy
    user_home_dir temporary_directories
    pub(crate) shell: Option<shell::Shell>
    executor_platform_os shell_snapshot: ShellSnapshotTask
    config_origin: EnvironmentConfigOrigin
    pub(crate) fn sandbox_context
    """
    config_types = """
    pub enum ShellEnvironmentPolicyInherit
    pub struct ShellEnvironmentPolicy
    pub inherit: ShellEnvironmentPolicyInherit
    pub ignore_default_excludes: bool
    pub exclude: Vec<EnvironmentVariablePattern>
    pub r#set: HashMap<String, String>
    pub include_only: Vec<EnvironmentVariablePattern>
    pub use_profile: bool
    """
    shell_env = """
    pub fn create_env pub fn populate_env
    ShellEnvironmentPolicyInherit::All ShellEnvironmentPolicyInherit::None
    ShellEnvironmentPolicyInherit::Core
    *KEY* *SECRET* *TOKEN*
    CODEX_THREAD_ID_ENV_VAR NON_INHERITABLE_ENV_VARS
    env_map.retain(|name, _| !is_non_inheritable_env_var(name))
    """
    if break_shell_env:
        shell_env = shell_env.replace("NON_INHERITABLE_ENV_VARS", "")
    snapshot = """
    pub(crate) struct ShellSnapshot pub(crate) struct ShellSnapshotFile
    pub(crate) async fn build if environment.is_remote()
    SNAPSHOT_RETENTION SNAPSHOT_DIR validate_snapshot
    /*use_login_shell*/ true /*use_login_shell*/ false
    scrub_non_inheritable_env_vars impl Drop for ShellSnapshotFile
    """
    rows = {
        "selection": _file(
            "source_spec.extra.environment_selection", "environment_selection",
            "codex-rs/core/src/environment_selection.rs", selection,
        ),
        "protocol": _file(
            "source_spec.extra.environment_protocol", "environment_protocol",
            "codex-rs/protocol/src/environment.rs", protocol,
        ),
        "turn": _file(
            "source_spec.extra.environment_turn_context", "environment_turn_context",
            "codex-rs/core/src/session/turn_context.rs", turn,
        ),
        "config_types": _file(
            "source_spec.extra.environment_config_types", "environment_config_types",
            "codex-rs/protocol/src/config_types.rs", config_types,
        ),
        "shell_env": _file(
            "source_spec.extra.environment_shell_environment", "environment_shell_environment",
            "codex-rs/protocol/src/shell_environment.rs", shell_env,
        ),
        "shell_snapshot": _file(
            "source_spec.extra.environment_shell_snapshot", "environment_shell_snapshot",
            "codex-rs/core/src/shell_snapshot.rs", snapshot,
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


def test_default_registry_assigns_environment_sources_to_environment_domain():
    registry = build_registry(load_legacy_modules())
    expected = {
        "source_spec.extra.environment_selection",
        "source_spec.extra.environment_protocol",
        "source_spec.extra.environment_turn_context",
        "source_spec.extra.environment_config_types",
        "source_spec.extra.environment_shell_environment",
        "source_spec.extra.environment_shell_snapshot",
    }
    observed = {
        spec.id
        for spec in registry.specs
        if "extractor.environment_execution" in spec.extractor_ids
    }
    assert observed == expected
    assert all(registry.get(spec_id).roles == ("environment_execution",) for spec_id in expected)


def test_environment_execution_extracts_owned_semantics_only():
    diagnostics = DiagnosticCollector()
    result = EnvironmentExecutionExtractor().extract(_snapshot(), diagnostics)
    assert result.semantic_complete
    assert diagnostics.summary()["error"] == 0
    assert result.data["$schema"].endswith("environment-execution-semantics-v1.schema.json")
    assert result.data["attachment"]["config_states"] == ["from_thread", "pending", "ready", "failed"]
    assert result.data["shell_environment"]["inherit_modes"] == ["all", "core", "none"]
    assert result.data["shell_snapshot"]["scope"].startswith("local environments only")
    assert "network proxy/controller startup, routing, domain allowlists, or upstream proxy behavior" in result.data["ownership"]["does_not_own"]
    assert "permission profile and sandbox authority semantics" in result.data["ownership"]["does_not_own"]
    assert len(result.data["semantic_digest"]) == 64


def test_missing_environment_source_fails_closed():
    diagnostics = DiagnosticCollector()
    result = EnvironmentExecutionExtractor().extract(_snapshot(omit="protocol"), diagnostics)
    assert not result.semantic_complete
    assert result.data == {}
    assert any(item.code == "ENVIRONMENT_EXECUTION_SOURCE_UNAVAILABLE" for item in diagnostics.values())


def test_shell_environment_drift_is_error_not_fallback():
    diagnostics = DiagnosticCollector()
    result = EnvironmentExecutionExtractor().extract(_snapshot(break_shell_env=True), diagnostics)
    assert not result.semantic_complete
    assert any(item.code == "ENV_NON_INHERITABLE_LIST_MISSING" for item in diagnostics.values())


def test_environment_source_identity_is_exact():
    registry = build_registry(load_legacy_modules())
    assert registry.get("source_spec.extra.environment_selection").primary_path == "codex-rs/core/src/environment_selection.rs"
    assert registry.get("source_spec.extra.environment_protocol").primary_path == "codex-rs/protocol/src/environment.rs"
    assert registry.get("source_spec.extra.environment_shell_environment").primary_path == "codex-rs/protocol/src/shell_environment.rs"
