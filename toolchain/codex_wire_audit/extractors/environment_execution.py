"""Canonical extraction for Codex execution-environment semantics.

This domain owns environment attachment/selection state, cwd/workspace roots,
shell/login policy, child-process environment construction, and shell snapshot
lifecycle. Permission authority is referenced but owned by contract/policy;
proxy/routing rules are referenced but owned by contract/routing.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ..diagnostics import DiagnosticCollector
from ..models import SourceFile, SourceSnapshot
from .registry import ExtractorResult, register_extractor

EXTRACTOR_ID = "extractor.environment_execution"
SCHEMA_VERSION = "1.0.0"
SCHEMA_ID = "https://schemas.codex-system-contract.invalid/environment/environment-execution-semantics-v1.schema.json"
SOURCE_IDS = {
    "selection": "source_spec.extra.environment_selection",
    "protocol": "source_spec.extra.environment_protocol",
    "turn": "source_spec.extra.environment_turn_context",
    "config_types": "source_spec.extra.environment_config_types",
    "shell_env": "source_spec.extra.environment_shell_environment",
    "shell_snapshot": "source_spec.extra.environment_shell_snapshot",
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
        category="environment_execution",
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
                message=f"Required environment source token is missing: {token}",
                source=source,
                entity=entity,
            )
    return complete


def _source(snapshot: SourceSnapshot, key: str) -> SourceFile | None:
    return snapshot.files.get(SOURCE_IDS[key])


def _attachment(
    selection: SourceFile,
    protocol: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[dict[str, Any], bool]:
    selection_tokens = (
        ("ENV_CONFIG_ORIGIN_MISSING", "pub(crate) enum EnvironmentConfigOrigin"),
        ("ENV_CONFIG_FROM_THREAD_MISSING", "EnvironmentConfigState::FromThread"),
        ("ENV_CONFIG_OWNER_READY_MISSING", "EnvironmentConfigState::Ready"),
        ("ENV_SELECTION_RESOLUTION_MISSING", "resolve_selection_config"),
        ("ENV_THREAD_CONFIG_REFRESH_MISSING", "refresh_thread_config"),
        ("ENV_SELECTION_UPDATE_MISSING", "pub(crate) fn update_selections"),
        ("ENV_DUPLICATE_ID_DEDUPE_MISSING", "seen_environment_ids"),
        ("ENV_SELECTION_CWD_MATCH_MISSING", "previous.cwd == selected_environment.cwd"),
        ("ENV_SELECTION_ROOTS_MATCH_MISSING", "previous.workspace_roots == selected_environment.workspace_roots"),
    )
    protocol_tokens = (
        ("ENV_CONFIG_STATE_MISSING", "pub enum EnvironmentConfigState"),
        ("ENV_CONFIG_FROM_THREAD_VARIANT_MISSING", "FromThread"),
        ("ENV_CONFIG_PENDING_VARIANT_MISSING", "Pending"),
        ("ENV_CONFIG_READY_VARIANT_MISSING", "Ready(EnvironmentConfig)"),
        ("ENV_CONFIG_FAILED_VARIANT_MISSING", "Failed(String)"),
        ("ENV_CONFIG_STRUCT_MISSING", "pub struct EnvironmentConfig"),
        ("ENV_WORKSPACE_ROOTS_MISSING", "pub workspace_roots: Vec<PathUri>"),
        ("ENV_PERMISSION_SNAPSHOT_MISSING", "pub permission_profile: PermissionProfileSnapshot"),
        ("ENV_SHELL_POLICY_MISSING", "pub shell_environment_policy: ShellEnvironmentPolicy"),
        ("ENV_SELECTED_CAPABILITY_ROOTS_MISSING", "pub selected_capability_roots: Vec<SelectedCapabilityRoot>"),
    )
    complete = _require(diagnostics, selection, selection_tokens, entity="environment_execution.attachment")
    complete &= _require(diagnostics, protocol, protocol_tokens, entity="environment_execution.attachment")
    return {
        "selection_identity": ["environment_id", "cwd", "workspace_roots"],
        "config_states": ["from_thread", "pending", "ready", "failed"],
        "config_ownership": {
            "thread": "thread-derived config follows later thread config updates",
            "owner": "owner-provided ready/pending/failed config remains owner authority",
        },
        "deduplication": "duplicate environment IDs in one selection update are ignored after the first",
        "reuse": "existing attachment is reused only when environment id, cwd, and workspace roots match and the prior attachment is neither failed nor being restarted as pending",
        "capability_roots": "thread-owned attachments may refresh legacy executor capability-root locations; owner config retains owner-selected roots",
        "evidence": {
            "selection": _evidence(selection, "EnvironmentConfigOrigin/ThreadEnvironments::update_selections"),
            "protocol": _evidence(protocol, "EnvironmentConfigState/EnvironmentConfig"),
        },
    }, complete


def _runtime_context(
    turn: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("ENV_TURN_ENV_STRUCT_MISSING", "pub(crate) struct TurnEnvironment"),
        ("ENV_CWD_ACCESSOR_MISSING", "pub(crate) fn cwd(&self) -> &PathUri"),
        ("ENV_WORKSPACE_ACCESSOR_MISSING", "pub(crate) fn workspace_roots(&self) -> &[PathUri]"),
        ("ENV_SHELL_POLICY_ACCESSOR_MISSING", "pub(crate) fn shell_environment_policy"),
        ("ENV_USER_HOME_MISSING", "user_home_dir"),
        ("ENV_TEMP_DIRS_MISSING", "temporary_directories"),
        ("ENV_SHELL_MISSING", "pub(crate) shell: Option<shell::Shell>"),
        ("ENV_PLATFORM_OS_MISSING", "executor_platform_os"),
        ("ENV_SHELL_SNAPSHOT_TASK_MISSING", "shell_snapshot: ShellSnapshotTask"),
        ("ENV_CONFIG_ORIGIN_FIELD_MISSING", "config_origin: EnvironmentConfigOrigin"),
        ("ENV_SANDBOX_CONTEXT_MISSING", "pub(crate) fn sandbox_context"),
    )
    complete = _require(diagnostics, turn, tokens, entity="environment_execution.runtime")
    return {
        "resolved_context": [
            "environment selection",
            "config origin",
            "cwd",
            "workspace roots",
            "user home",
            "temporary directories",
            "resolved shell",
            "executor platform OS",
            "shell snapshot task",
        ],
        "config_readiness": "TurnEnvironment only exposes EnvironmentConfig through Ready state",
        "shell_snapshot_binding": "snapshot is valid only for the cwd captured by the selected environment",
        "policy_boundary": "permission profile/sandbox authority is consumed here but owned by contract/policy",
        "routing_boundary": "network proxy/controller behavior is carried separately and is not interpreted here",
        "evidence": _evidence(turn, "TurnEnvironment"),
    }, complete


def _shell_policy(
    config_types: SourceFile,
    shell_env: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[dict[str, Any], bool]:
    type_tokens = (
        ("ENV_POLICY_INHERIT_ENUM_MISSING", "pub enum ShellEnvironmentPolicyInherit"),
        ("ENV_POLICY_STRUCT_MISSING", "pub struct ShellEnvironmentPolicy"),
        ("ENV_POLICY_INHERIT_FIELD_MISSING", "pub inherit: ShellEnvironmentPolicyInherit"),
        ("ENV_POLICY_DEFAULT_EXCLUDES_FIELD_MISSING", "pub ignore_default_excludes: bool"),
        ("ENV_POLICY_EXCLUDE_FIELD_MISSING", "pub exclude: Vec<EnvironmentVariablePattern>"),
        ("ENV_POLICY_SET_FIELD_MISSING", "pub r#set: HashMap<String, String>"),
        ("ENV_POLICY_INCLUDE_ONLY_FIELD_MISSING", "pub include_only: Vec<EnvironmentVariablePattern>"),
        ("ENV_POLICY_PROFILE_FIELD_MISSING", "pub use_profile: bool"),
    )
    env_tokens = (
        ("ENV_CREATE_ENV_MISSING", "pub fn create_env"),
        ("ENV_POPULATE_ENV_MISSING", "pub fn populate_env"),
        ("ENV_INHERIT_ALL_MISSING", "ShellEnvironmentPolicyInherit::All"),
        ("ENV_INHERIT_NONE_MISSING", "ShellEnvironmentPolicyInherit::None"),
        ("ENV_INHERIT_CORE_MISSING", "ShellEnvironmentPolicyInherit::Core"),
        ("ENV_DEFAULT_SECRET_FILTER_MISSING", "*SECRET*"),
        ("ENV_DEFAULT_TOKEN_FILTER_MISSING", "*TOKEN*"),
        ("ENV_DEFAULT_KEY_FILTER_MISSING", "*KEY*"),
        ("ENV_THREAD_ID_INJECTION_MISSING", "CODEX_THREAD_ID_ENV_VAR"),
        ("ENV_NON_INHERITABLE_LIST_MISSING", "NON_INHERITABLE_ENV_VARS"),
        ("ENV_NON_INHERITABLE_FINAL_FILTER_MISSING", "env_map.retain(|name, _| !is_non_inheritable_env_var(name))"),
    )
    complete = _require(diagnostics, config_types, type_tokens, entity="environment_execution.shell_policy")
    complete &= _require(diagnostics, shell_env, env_tokens, entity="environment_execution.shell_policy")
    return {
        "inherit_modes": ["all", "core", "none"],
        "construction_order": [
            "inherit starting variables",
            "apply default KEY/SECRET/TOKEN excludes unless disabled",
            "apply custom excludes",
            "apply explicit set overrides",
            "apply include_only retain filter",
            "inject CODEX_THREAD_ID when available",
            "strip non-inheritable launch-context variables",
        ],
        "non_inheritable_role": "launch/auth context variables cannot be restored through user shell-environment overrides",
        "profile_execution_flag": "use_profile controls whether shell profile startup is requested by shell-based execution",
        "evidence": {
            "types": _evidence(config_types, "ShellEnvironmentPolicy"),
            "builder": _evidence(shell_env, "create_env/populate_env"),
        },
    }, complete


def _snapshot(
    shell_snapshot: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("ENV_SNAPSHOT_STRUCT_MISSING", "pub(crate) struct ShellSnapshot"),
        ("ENV_SNAPSHOT_FILE_MISSING", "pub(crate) struct ShellSnapshotFile"),
        ("ENV_SNAPSHOT_REMOTE_SKIP_MISSING", "if environment.is_remote()"),
        ("ENV_SNAPSHOT_BUILD_MISSING", "pub(crate) async fn build"),
        ("ENV_SNAPSHOT_RETENTION_MISSING", "SNAPSHOT_RETENTION"),
        ("ENV_SNAPSHOT_DIR_MISSING", "SNAPSHOT_DIR"),
        ("ENV_SNAPSHOT_VALIDATE_MISSING", "validate_snapshot"),
        ("ENV_SNAPSHOT_LOGIN_CAPTURE_MISSING", "/*use_login_shell*/ true"),
        ("ENV_SNAPSHOT_NONLOGIN_VALIDATE_MISSING", "/*use_login_shell*/ false"),
        ("ENV_SNAPSHOT_SCRUB_MISSING", "scrub_non_inheritable_env_vars"),
        ("ENV_SNAPSHOT_DROP_DELETE_MISSING", "impl Drop for ShellSnapshotFile"),
    )
    complete = _require(diagnostics, shell_snapshot, tokens, entity="environment_execution.shell_snapshot")
    return {
        "scope": "local environments only; remote environments do not build local shell snapshots",
        "capture": "snapshot capture uses a login shell, then validates the generated snapshot with a non-login shell",
        "security_filter": "snapshot command execution scrubs non-inheritable launch-context variables",
        "lifecycle": "snapshot file is temporary session-scoped state, removed on drop and stale-cleaned against rollout/session retention",
        "retention": "three days for stale snapshot cleanup, with active session exempt",
        "evidence": _evidence(shell_snapshot, "ShellSnapshot::build/validate_snapshot"),
    }, complete


class EnvironmentExecutionExtractor:
    extractor_id = EXTRACTOR_ID
    source_spec_ids = tuple(SOURCE_IDS.values())

    def extract(self, snapshot: SourceSnapshot, diagnostics: DiagnosticCollector) -> ExtractorResult:
        sources = {key: _source(snapshot, key) for key in SOURCE_IDS}
        missing = [key for key, source in sources.items() if source is None]
        if missing:
            for key in missing:
                _missing(
                    diagnostics,
                    code="ENVIRONMENT_EXECUTION_SOURCE_UNAVAILABLE",
                    message=f"Execution-environment source is unavailable: {key}",
                    source=None,
                    entity=f"environment_execution.source.{key}",
                )
            return ExtractorResult(
                extractor_id=EXTRACTOR_ID,
                schema_version=SCHEMA_VERSION,
                data={},
                semantic_complete=False,
                source_spec_ids=self.source_spec_ids,
            )

        attachment, attachment_ok = _attachment(
            sources["selection"], sources["protocol"], diagnostics  # type: ignore[arg-type]
        )
        runtime, runtime_ok = _runtime_context(sources["turn"], diagnostics)  # type: ignore[arg-type]
        shell_policy, shell_policy_ok = _shell_policy(
            sources["config_types"], sources["shell_env"], diagnostics  # type: ignore[arg-type]
        )
        snapshot_semantics, snapshot_ok = _snapshot(sources["shell_snapshot"], diagnostics)  # type: ignore[arg-type]
        complete = attachment_ok and runtime_ok and shell_policy_ok and snapshot_ok
        body: dict[str, Any] = {
            "$schema": SCHEMA_ID,
            "schema_version": SCHEMA_VERSION,
            "ownership": {
                "owns": [
                    "environment attachment and config-origin semantics",
                    "selected environment cwd/workspace/home/temp/shell/platform context",
                    "shell environment variable construction policy",
                    "non-inheritable child-process environment filtering",
                    "local shell snapshot capture/validation/lifecycle",
                ],
                "does_not_own": [
                    "permission profile and sandbox authority semantics",
                    "network proxy/controller startup, routing, domain allowlists, or upstream proxy behavior",
                    "plugin discovery/runtime semantics",
                    "MCP tool transport/filter semantics",
                    "prompt rendering of environment context",
                ],
            },
            "attachment": attachment,
            "runtime_context": runtime,
            "shell_environment": shell_policy,
            "shell_snapshot": snapshot_semantics,
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
def _factory() -> EnvironmentExecutionExtractor:
    return EnvironmentExecutionExtractor()
