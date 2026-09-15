"""Canonical extraction for Codex execution-environment context.

This domain owns environment identity/selection/readiness, cwd/workspace roots,
executor-observed context, child-process environment construction, and shell
snapshot runtime behavior. Permission/approval authority, proxy routing,
prompt rendering, and plugin/MCP semantics remain separate domains.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ..diagnostics import DiagnosticCollector
from ..models import SourceFile, SourceSnapshot
from .registry import ExtractorResult, register_extractor

EXTRACTOR_ID = "extractor.execution_environment"
SCHEMA_VERSION = "1.0.0"
SCHEMA_ID = "https://schemas.codex-system-contract.invalid/environment/execution-environment-semantics-v1.schema.json"
SOURCE_IDS = {
    "shell_policy": "source_spec.extra.environment_shell_policy",
    "shell_builder": "source_spec.extra.environment_shell_builder",
    "selection": "source_spec.extra.environment_selection",
    "snapshot": "source_spec.extra.environment_shell_snapshot",
    "manager": "source_spec.extra.environment_manager",
    "turn": "source_spec.extra.environment_turn_context",
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
        category="execution_environment",
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
                message=f"Required execution-environment source token is missing: {token}",
                source=source,
                entity=entity,
            )
    return complete


def _source(snapshot: SourceSnapshot, key: str) -> SourceFile | None:
    return snapshot.files.get(SOURCE_IDS[key])


def _shell_environment(
    policy: SourceFile,
    builder: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[dict[str, Any], bool]:
    policy_tokens = (
        ("ENV_SHELL_INHERIT_ENUM_MISSING", "pub enum ShellEnvironmentPolicyInherit"),
        ("ENV_SHELL_POLICY_MISSING", "pub struct ShellEnvironmentPolicy"),
        ("ENV_SHELL_INHERIT_FIELD_MISSING", "pub inherit: ShellEnvironmentPolicyInherit"),
        ("ENV_SHELL_DEFAULT_EXCLUDE_FIELD_MISSING", "pub ignore_default_excludes: bool"),
        ("ENV_SHELL_EXCLUDE_FIELD_MISSING", "pub exclude: Vec<EnvironmentVariablePattern>"),
        ("ENV_SHELL_SET_FIELD_MISSING", "pub r#set: HashMap<String, String>"),
        ("ENV_SHELL_INCLUDE_ONLY_FIELD_MISSING", "pub include_only: Vec<EnvironmentVariablePattern>"),
        ("ENV_SHELL_PROFILE_FIELD_MISSING", "pub use_profile: bool"),
    )
    builder_tokens = (
        ("ENV_NON_INHERITABLE_LIST_MISSING", "pub const NON_INHERITABLE_ENV_VARS"),
        ("ENV_SCRUB_FUNCTION_MISSING", "pub fn scrub_non_inheritable_env_vars"),
        ("ENV_CREATE_ENV_MISSING", "pub fn create_env("),
        ("ENV_POPULATE_ENV_MISSING", "pub fn populate_env"),
        ("ENV_INHERIT_ALL_MISSING", "ShellEnvironmentPolicyInherit::All"),
        ("ENV_INHERIT_NONE_MISSING", "ShellEnvironmentPolicyInherit::None"),
        ("ENV_INHERIT_CORE_MISSING", "ShellEnvironmentPolicyInherit::Core"),
        ("ENV_DEFAULT_KEY_EXCLUDE_MISSING", '"*KEY*"'),
        ("ENV_DEFAULT_SECRET_EXCLUDE_MISSING", '"*SECRET*"'),
        ("ENV_DEFAULT_TOKEN_EXCLUDE_MISSING", '"*TOKEN*"'),
        ("ENV_THREAD_ID_INJECTION_MISSING", "CODEX_THREAD_ID_ENV_VAR"),
        ("ENV_FINAL_RESTRICTED_SCRUB_MISSING", "is_non_inheritable_env_var"),
    )
    complete = _require(diagnostics, policy, policy_tokens, entity="execution_environment.shell_policy")
    complete &= _require(diagnostics, builder, builder_tokens, entity="execution_environment.shell_builder")
    return {
        "policy": {
            "inherit_modes": ["all", "core", "none"],
            "default_inherit": "all",
            "fields": ["inherit", "ignore_default_excludes", "exclude", "set", "include_only", "use_profile"],
            "default_ignore_default_excludes": True,
        },
        "construction_order": [
            "select inherited parent variables from all/core/none",
            "unless ignore_default_excludes, remove names matching *KEY*, *SECRET*, or *TOKEN*",
            "apply custom excludes",
            "apply explicit set overrides",
            "when include_only is non-empty, retain only matching names",
            "inject CODEX_THREAD_ID when a thread id is supplied",
            "remove non-inheritable launch-context variables even if an override attempted to restore them",
        ],
        "restricted_launch_context": [
            "exec-server noise auth token",
            "Node REPL auth token",
            "federation rule id",
            "identity token file",
            "workload identity context",
        ],
        "platform_core_environment": {
            "unix_examples": ["PATH", "SHELL", "HOME", "TMPDIR", "LANG", "USER"],
            "windows_examples": ["PATH", "PATHEXT", "COMSPEC", "SYSTEMROOT", "USERPROFILE", "APPDATA", "TEMP"],
            "windows_pathext_fallback": ".COM;.EXE;.BAT;.CMD",
        },
        "evidence": {
            "policy": _evidence(policy, "ShellEnvironmentPolicy/ShellEnvironmentPolicyInherit"),
            "builder": _evidence(builder, "create_env/populate_env/NON_INHERITABLE_ENV_VARS"),
        },
    }, complete


def _selection(
    source: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("ENV_CONFIG_ORIGIN_MISSING", "pub(crate) enum EnvironmentConfigOrigin"),
        ("ENV_CONFIG_ORIGIN_THREAD_MISSING", "Self::Thread"),
        ("ENV_CONFIG_ORIGIN_OWNER_MISSING", "Self::Owner"),
        ("ENV_DEFAULT_SELECTION_MISSING", "default_thread_environment_selections"),
        ("ENV_SELECTION_CONFIG_RESOLUTION_MISSING", "resolve_selection_config"),
        ("ENV_THREAD_ENVIRONMENTS_MISSING", "pub(crate) struct ThreadEnvironments"),
        ("ENV_SELECTION_UPDATE_MISSING", "pub(crate) fn update_selections"),
        ("ENV_SELECTION_DEDUP_MISSING", "seen_environment_ids"),
        ("ENV_OWNER_CONFIG_PUBLICATION_MISSING", "Publish owner configuration before waking turns"),
        ("ENV_THREAD_CONFIG_REFRESH_MISSING", "pub(crate) fn update_thread_config"),
        ("ENV_PRIMARY_ROOTS_MISSING", "pub(crate) fn primary_workspace_roots"),
        ("ENV_SNAPSHOT_V2_CAPABILITY_MISSING", "shell_snapshot_v2_supported"),
    )
    complete = _require(diagnostics, source, tokens, entity="execution_environment.selection")
    return {
        "config_ownership": {
            "thread": "selection follows later thread environment-config updates and projects back as FromThread",
            "owner": "explicit attachment configuration remains owner-controlled",
        },
        "default_selection": "environment-manager default IDs plus thread cwd/workspace roots, with config inherited from thread",
        "selection_identity": "environment_id + cwd + workspace roots identify a reusable selected environment view",
        "deduplication": "duplicate environment IDs in one selection update are ignored after the first occurrence",
        "unknown_environment": "skipped rather than synthesized",
        "child_inheritance": "ready environments are inherited; thread-owned config is re-inferred while owner config is preserved",
        "configuration_wakeup": "owner configuration is published before turns waiting on the attachment are released",
        "capability_roots": "thread-owned live roots may refresh persisted locations; owner roots retain explicit selection ownership",
        "evidence": _evidence(source, "ThreadEnvironments/EnvironmentConfigOrigin"),
    }, complete


def _manager(
    source: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("ENV_MANAGER_MISSING", "pub struct EnvironmentManager"),
        ("ENV_LOCAL_ID_MISSING", 'pub const LOCAL_ENVIRONMENT_ID: &str = "local"'),
        ("ENV_REMOTE_ID_MISSING", 'pub const REMOTE_ENVIRONMENT_ID: &str = "remote"'),
        ("ENV_CONNECTION_STATE_MISSING", "pub enum EnvironmentConnectionState"),
        ("ENV_OBSERVED_STATUS_MISSING", "pub enum EnvironmentObservedStatus"),
        ("ENV_READY_INFO_MISSING", "pub struct EnvironmentReadyInfo"),
        ("ENV_HOME_DISCOVERY_MISSING", "pub async fn prepare_from_codex_home"),
        ("ENV_ENV_DISCOVERY_MISSING", "pub async fn prepare_from_env"),
        ("ENV_DEFAULT_IDS_MISSING", "pub fn default_environment_ids"),
        ("ENV_LOCAL_RESERVED_MISSING", "is reserved for EnvironmentManager"),
        ("ENV_DUPLICATE_ID_REJECTION_MISSING", "is duplicated"),
        ("ENV_INVALID_DEFAULT_REJECTION_MISSING", "default environment `{environment_id}` is not configured"),
        ("ENV_DISABLE_SENTINEL_MISSING", "CODEX_EXEC_SERVER_URL=none"),
    )
    complete = _require(diagnostics, source, tokens, entity="execution_environment.manager")
    return {
        "registry": "EnvironmentManager owns concrete local/remote execution and filesystem environments",
        "well_known_ids": {"local": "local", "legacy_remote": "remote"},
        "default_behavior": "no default environment means model-facing environment access is unavailable",
        "discovery": ["CODEX_HOME environment configuration", "environment variables", "special provisioned/noise environment input"],
        "validation": ["empty IDs rejected", "local ID reserved", "duplicates rejected", "default must reference a configured environment"],
        "connection_semantics": "ordinary remote environments may begin connecting when registered; provisioned environments can remain pending until selected",
        "observed_status": ["ready", "pending", "disconnected with reason"],
        "transport_boundary": "HTTP client/proxy policy is injected into the manager but its routing semantics belong to contract/routing",
        "evidence": _evidence(source, "EnvironmentManager/EnvironmentObservedStatus"),
    }, complete


def _snapshot(
    source: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("ENV_SHELL_SNAPSHOT_MISSING", "pub(crate) struct ShellSnapshot"),
        ("ENV_REMOTE_SNAPSHOT_SKIP_MISSING", "if environment.is_remote()"),
        ("ENV_SNAPSHOT_TIMEOUT_MISSING", "SNAPSHOT_TIMEOUT"),
        ("ENV_SNAPSHOT_RETENTION_MISSING", "SNAPSHOT_RETENTION"),
        ("ENV_SNAPSHOT_DIR_MISSING", 'const SNAPSHOT_DIR: &str = "shell_snapshots"'),
        ("ENV_SNAPSHOT_CAPTURE_MISSING", "capture_snapshot"),
        ("ENV_SNAPSHOT_VALIDATE_MISSING", "validate_snapshot"),
        ("ENV_SNAPSHOT_SCRUB_MISSING", "scrub_non_inheritable_env_vars"),
        ("ENV_SNAPSHOT_CLEANUP_MISSING", "cleanup_stale_snapshots"),
        ("ENV_SNAPSHOT_DROP_CLEANUP_MISSING", "impl Drop for ShellSnapshotFile"),
    )
    complete = _require(diagnostics, source, tokens, entity="execution_environment.snapshot")
    return {
        "availability": "v1 shell snapshots are local-environment only and require a supported resolved shell/cwd",
        "capture": "run a shell-specific snapshot script using a login shell after scrubbing restricted launch-context variables",
        "validation": "source the temporary snapshot without login-shell behavior before atomic temp-to-final rename",
        "timeout_seconds": 10,
        "retention_days": 3,
        "lifecycle": "snapshot file is removed on drop; stale files are also cleaned when the rollout is absent or old, with the active session exempt",
        "storage_boundary": "contract/local-storage owns the durable path/layout claim; this domain owns runtime capture/use/cleanup behavior",
        "evidence": _evidence(source, "ShellSnapshot/ShellSnapshotFile"),
    }, complete


def _turn_projection(
    source: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("ENV_TURN_ENVIRONMENT_MISSING", "pub(crate) struct TurnEnvironment"),
        ("ENV_TURN_SELECTION_MISSING", "pub(crate) selection: TurnEnvironmentSelection"),
        ("ENV_TURN_CONFIG_ORIGIN_MISSING", "pub(crate) config_origin: EnvironmentConfigOrigin"),
        ("ENV_TURN_HOME_MISSING", "pub(crate) user_home_dir: Option<PathUri>"),
        ("ENV_TURN_TEMP_DIRS_MISSING", "pub(crate) temporary_directories: Option<Vec<PathUri>>"),
        ("ENV_TURN_SHELL_MISSING", "pub(crate) shell: Option<shell::Shell>"),
        ("ENV_TURN_PLATFORM_MISSING", "pub(crate) executor_platform_os: Option<String>"),
        ("ENV_TURN_SNAPSHOT_MISSING", "pub(crate) shell_snapshot: ShellSnapshotTask"),
        ("ENV_TURN_POLICY_ACCESSOR_MISSING", "pub(crate) fn shell_environment_policy"),
        ("ENV_TURN_CWD_ACCESSOR_MISSING", "pub(crate) fn cwd(&self) -> &PathUri"),
        ("ENV_TURN_ROOTS_ACCESSOR_MISSING", "pub(crate) fn workspace_roots(&self) -> &[PathUri]"),
        ("ENV_TURN_SELECTION_PROJECTION_MISSING", "pub(crate) fn selection(&self) -> TurnEnvironmentSelection"),
        ("ENV_LEGACY_CWD_DEPRECATION_MISSING", 'deprecated(note = "use the selected turn environment cwd instead")'),
    )
    complete = _require(diagnostics, source, tokens, entity="execution_environment.turn")
    return {
        "turn_environment": [
            "selection and config ownership",
            "environment instance",
            "cwd and workspace roots",
            "resolved shell",
            "executor-reported user home",
            "executor-reported temporary directories",
            "executor platform OS",
            "shell snapshot task and v2 capability",
        ],
        "cwd_authority": "selected turn environment cwd is canonical for environment-aware execution; thread cwd remains a deprecated fallback",
        "shell_policy": "read from the ready selected environment configuration",
        "selection_projection": "restores FromThread for thread-owned config rather than leaking resolved config as owner state",
        "policy_boundary": "permission profile accessors coexist on TurnEnvironment but their authority is owned by contract/policy",
        "routing_boundary": "TurnContext network/proxy state is not execution-environment authority",
        "evidence": _evidence(source, "TurnEnvironment/TurnContext environment fields"),
    }, complete


class ExecutionEnvironmentExtractor:
    extractor_id = EXTRACTOR_ID
    source_spec_ids = tuple(SOURCE_IDS.values())

    def extract(self, snapshot: SourceSnapshot, diagnostics: DiagnosticCollector) -> ExtractorResult:
        sources = {key: _source(snapshot, key) for key in SOURCE_IDS}
        missing = [key for key, source in sources.items() if source is None]
        if missing:
            for key in missing:
                _missing(
                    diagnostics,
                    code="EXECUTION_ENVIRONMENT_SOURCE_UNAVAILABLE",
                    message=f"Execution-environment source is unavailable: {key}",
                    source=None,
                    entity=f"execution_environment.source.{key}",
                )
            return ExtractorResult(
                extractor_id=EXTRACTOR_ID,
                schema_version=SCHEMA_VERSION,
                data={},
                semantic_complete=False,
                source_spec_ids=self.source_spec_ids,
            )

        shell_env, shell_ok = _shell_environment(
            sources["shell_policy"], sources["shell_builder"], diagnostics  # type: ignore[arg-type]
        )
        selection, selection_ok = _selection(sources["selection"], diagnostics)  # type: ignore[arg-type]
        manager, manager_ok = _manager(sources["manager"], diagnostics)  # type: ignore[arg-type]
        shell_snapshot, snapshot_ok = _snapshot(sources["snapshot"], diagnostics)  # type: ignore[arg-type]
        turn, turn_ok = _turn_projection(sources["turn"], diagnostics)  # type: ignore[arg-type]
        complete = shell_ok and selection_ok and manager_ok and snapshot_ok and turn_ok
        body: dict[str, Any] = {
            "$schema": SCHEMA_ID,
            "schema_version": SCHEMA_VERSION,
            "ownership": {
                "owns": [
                    "environment identity/default selection/readiness",
                    "selected cwd and workspace roots",
                    "thread-owned versus owner-owned environment configuration",
                    "executor-observed shell/home/temp/platform context",
                    "child-process environment inheritance/filter/set/include rules",
                    "restricted launch-context environment scrubbing",
                    "shell snapshot runtime capture/use/cleanup behavior",
                ],
                "does_not_own": [
                    "permission profiles, approvals, or sandbox authorization",
                    "proxy selection, network routes, or domain network policy",
                    "prompt rendering of environment context",
                    "plugin or MCP runtime semantics",
                    "durable shell-snapshot storage layout",
                ],
            },
            "shell_environment": shell_env,
            "selection": selection,
            "manager": manager,
            "shell_snapshot": shell_snapshot,
            "turn_projection": turn,
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
def _factory() -> ExecutionEnvironmentExtractor:
    return ExecutionEnvironmentExtractor()
