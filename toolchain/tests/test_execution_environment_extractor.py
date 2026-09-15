from __future__ import annotations

from codex_wire_audit.diagnostics import DiagnosticCollector
from codex_wire_audit.extractors.execution_environment import ExecutionEnvironmentExtractor
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
        roles=("execution_environment",),
        expected_symbols=(),
        extractor_ids=("extractor.execution_environment",),
    )
    return SourceFile.create(spec=spec, selected_path=path, raw_bytes=text.encode())


def _snapshot(*, omit: str | None = None, break_scrub: bool = False) -> SourceSnapshot:
    shell_policy = '''
    pub enum ShellEnvironmentPolicyInherit { Core, All, None }
    pub struct ShellEnvironmentPolicy {
      pub inherit: ShellEnvironmentPolicyInherit,
      pub ignore_default_excludes: bool,
      pub exclude: Vec<EnvironmentVariablePattern>,
      pub r#set: HashMap<String, String>,
      pub include_only: Vec<EnvironmentVariablePattern>,
      pub use_profile: bool,
    }
    '''
    shell_builder = '''
    pub const CODEX_THREAD_ID_ENV_VAR: &str = "CODEX_THREAD_ID";
    pub const NON_INHERITABLE_ENV_VARS: &[&str] = &[];
    pub fn scrub_non_inheritable_env_vars() {}
    pub fn create_env() {}
    pub fn create_env_from_vars() {}
    pub fn populate_env() {
      ShellEnvironmentPolicyInherit::All;
      ShellEnvironmentPolicyInherit::None;
      ShellEnvironmentPolicyInherit::Core;
      "*KEY*"; "*SECRET*"; "*TOKEN*";
      CODEX_THREAD_ID_ENV_VAR;
      is_non_inheritable_env_var;
    }
    '''
    if break_scrub:
        shell_builder = shell_builder.replace("is_non_inheritable_env_var", "")
    selection = '''
    pub(crate) enum EnvironmentConfigOrigin { Thread, Owner }
    Self::Thread; Self::Owner;
    default_thread_environment_selections
    resolve_selection_config
    pub(crate) struct ThreadEnvironments
    pub(crate) fn update_selections
    seen_environment_ids
    // Publish owner configuration before waking turns waiting on this attachment.
    pub(crate) fn update_thread_config
    pub(crate) fn primary_workspace_roots
    shell_snapshot_v2_supported
    '''
    snapshot = '''
    pub(crate) struct ShellSnapshot
    if environment.is_remote()
    SNAPSHOT_TIMEOUT SNAPSHOT_RETENTION
    const SNAPSHOT_DIR: &str = "shell_snapshots";
    capture_snapshot validate_snapshot scrub_non_inheritable_env_vars cleanup_stale_snapshots
    impl Drop for ShellSnapshotFile
    '''
    manager = '''
    pub struct EnvironmentManager
    pub const LOCAL_ENVIRONMENT_ID: &str = "local";
    pub const REMOTE_ENVIRONMENT_ID: &str = "remote";
    pub enum EnvironmentConnectionState
    pub enum EnvironmentObservedStatus
    pub struct EnvironmentReadyInfo
    pub async fn prepare_from_codex_home
    pub async fn prepare_from_env
    pub fn default_environment_ids
    environment id `{LOCAL_ENVIRONMENT_ID}` is reserved for EnvironmentManager
    is duplicated
    default environment `{environment_id}` is not configured
    CODEX_EXEC_SERVER_URL=none
    '''
    turn = '''
    pub(crate) struct TurnEnvironment
    pub(crate) selection: TurnEnvironmentSelection
    pub(crate) config_origin: EnvironmentConfigOrigin
    pub(crate) user_home_dir: Option<PathUri>
    pub(crate) temporary_directories: Option<Vec<PathUri>>
    pub(crate) shell: Option<shell::Shell>
    pub(crate) executor_platform_os: Option<String>
    pub(crate) shell_snapshot: ShellSnapshotTask
    pub(crate) fn shell_environment_policy
    pub(crate) fn cwd(&self) -> &PathUri
    pub(crate) fn workspace_roots(&self) -> &[PathUri]
    pub(crate) fn selection(&self) -> TurnEnvironmentSelection
    deprecated(note = "use the selected turn environment cwd instead")
    '''
    rows = {
        "shell_policy": _file("source_spec.extra.environment_shell_policy", "environment_shell_policy", "codex-rs/protocol/src/config_types.rs", shell_policy),
        "shell_builder": _file("source_spec.extra.environment_shell_builder", "environment_shell_builder", "codex-rs/protocol/src/shell_environment.rs", shell_builder),
        "selection": _file("source_spec.extra.environment_selection", "environment_selection", "codex-rs/core/src/environment_selection.rs", selection),
        "snapshot": _file("source_spec.extra.environment_shell_snapshot", "environment_shell_snapshot", "codex-rs/core/src/shell_snapshot.rs", snapshot),
        "manager": _file("source_spec.extra.environment_manager", "environment_manager", "codex-rs/exec-server/src/environment.rs", manager),
        "turn": _file("source_spec.extra.environment_turn_context", "environment_turn_context", "codex-rs/core/src/session/turn_context.rs", turn),
    }
    if omit:
        rows.pop(omit)
    files = {value.spec_id: value for value in rows.values()}
    revision = SourceRevision(
        "fixture", "openai/codex", "fixture", "3" * 40,
        SourceSnapshot.digest_files(files), False,
    )
    return SourceSnapshot(revision, files)


def test_default_registry_assigns_environment_sources_to_environment_domain():
    registry = build_registry(load_legacy_modules())
    expected = {
        "source_spec.extra.environment_shell_policy",
        "source_spec.extra.environment_shell_builder",
        "source_spec.extra.environment_selection",
        "source_spec.extra.environment_shell_snapshot",
        "source_spec.extra.environment_manager",
        "source_spec.extra.environment_turn_context",
    }
    observed = {
        spec.id
        for spec in registry.specs
        if "extractor.execution_environment" in spec.extractor_ids
    }
    assert observed == expected
    assert all(registry.get(spec_id).roles == ("execution_environment",) for spec_id in expected)


def test_execution_environment_extracts_context_without_claiming_policy_or_routing():
    diagnostics = DiagnosticCollector()
    result = ExecutionEnvironmentExtractor().extract(_snapshot(), diagnostics)
    assert result.semantic_complete
    assert diagnostics.summary()["error"] == 0
    assert result.data["shell_environment"]["policy"]["default_inherit"] == "all"
    assert result.data["shell_environment"]["policy"]["default_ignore_default_excludes"] is True
    assert result.data["shell_snapshot"]["timeout_seconds"] == 10
    assert result.data["shell_snapshot"]["retention_days"] == 3
    assert "permission profiles, approvals, or sandbox authorization" in result.data["ownership"]["does_not_own"]
    assert "proxy selection, network routes, or domain network policy" in result.data["ownership"]["does_not_own"]
    assert len(result.data["semantic_digest"]) == 64


def test_missing_environment_source_fails_closed():
    diagnostics = DiagnosticCollector()
    result = ExecutionEnvironmentExtractor().extract(_snapshot(omit="manager"), diagnostics)
    assert not result.semantic_complete
    assert result.data == {}
    assert any(item.code == "EXECUTION_ENVIRONMENT_SOURCE_UNAVAILABLE" for item in diagnostics.values())


def test_restricted_environment_scrub_drift_is_error():
    diagnostics = DiagnosticCollector()
    result = ExecutionEnvironmentExtractor().extract(_snapshot(break_scrub=True), diagnostics)
    assert not result.semantic_complete
    assert any(item.code == "ENV_FINAL_RESTRICTED_SCRUB_MISSING" for item in diagnostics.values())


def test_environment_source_identity_is_domain_owned():
    registry = build_registry(load_legacy_modules())
    spec = registry.get("source_spec.extra.environment_shell_builder")
    assert spec.primary_path == "codex-rs/protocol/src/shell_environment.rs"
    assert spec.legacy_key == "environment_shell_builder"
    assert spec.group is SourceGroup.EXTRA
