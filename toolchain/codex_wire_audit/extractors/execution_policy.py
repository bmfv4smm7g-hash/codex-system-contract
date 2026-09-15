"""Canonical extraction for Codex execution authority and approval policy.

This domain owns permission-profile selection, managed constraints, sandbox
execution authority, approval policy, and exec-policy decision semantics. It
does not own shell/environment contents, proxy transport/routing, prompt
rendering, plugin runtime, or MCP transport.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from ..diagnostics import DiagnosticCollector
from ..models import SourceFile, SourceSnapshot
from .registry import ExtractorResult, register_extractor

EXTRACTOR_ID = "extractor.execution_policy"
SCHEMA_VERSION = "1.0.0"
SCHEMA_ID = "https://schemas.codex-system-contract.invalid/policy/execution-policy-semantics-v1.schema.json"
SOURCE_IDS = {
    "protocol": "source_spec.extra.policy_protocol",
    "permissions": "source_spec.extra.policy_permissions",
    "requirements": "source_spec.extra.policy_requirements",
    "config": "source_spec.extra.policy_config_resolution",
    "profile_state": "source_spec.extra.policy_profile_state",
    "turn": "source_spec.extra.policy_turn_context",
    "exec_policy": "source_spec.extra.policy_exec_policy",
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
        category="execution_policy",
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
                message=f"Required execution-policy source token is missing: {token}",
                source=source,
                entity=entity,
            )
    return complete


def _source(snapshot: SourceSnapshot, key: str) -> SourceFile | None:
    return snapshot.files.get(SOURCE_IDS[key])


def _builtin_id(source: SourceFile, constant: str, fallback: str) -> str:
    match = re.search(rf'{constant}:\s*&str\s*=\s*"([^"]+)"', source.text)
    return match.group(1) if match else fallback


def _permission_model(
    source: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("POLICY_SANDBOX_ENFORCEMENT_MISSING", "pub enum SandboxEnforcement"),
        ("POLICY_PERMISSION_PROFILE_MISSING", "pub enum PermissionProfile"),
        ("POLICY_ACTIVE_PROFILE_MISSING", "pub struct ActivePermissionProfile"),
        ("POLICY_ADDITIONAL_PROFILE_MISSING", "pub struct AdditionalPermissionProfile"),
        ("POLICY_BUILTIN_READ_ONLY_MISSING", "BUILT_IN_PERMISSION_PROFILE_READ_ONLY"),
        ("POLICY_BUILTIN_WORKSPACE_MISSING", "BUILT_IN_PERMISSION_PROFILE_WORKSPACE"),
        ("POLICY_BUILTIN_FULL_ACCESS_MISSING", "BUILT_IN_PERMISSION_PROFILE_DANGER_FULL_ACCESS"),
        ("POLICY_MANAGED_ENFORCEMENT_VARIANT_MISSING", "Managed"),
        ("POLICY_DISABLED_ENFORCEMENT_VARIANT_MISSING", "Disabled"),
        ("POLICY_EXTERNAL_ENFORCEMENT_VARIANT_MISSING", "External"),
    )
    complete = _require(diagnostics, source, tokens, entity="execution_policy.permission_model")
    return {
        "runtime_authority": "PermissionProfile",
        "sandbox_enforcement": {
            "managed": "Codex owns sandbox construction",
            "disabled": "no outer filesystem sandbox",
            "external": "filesystem isolation is enforced by an external caller",
        },
        "builtin_profiles": {
            "read_only": _builtin_id(source, "BUILT_IN_PERMISSION_PROFILE_READ_ONLY", ":read-only"),
            "workspace": _builtin_id(source, "BUILT_IN_PERMISSION_PROFILE_WORKSPACE", ":workspace"),
            "danger_full_access": _builtin_id(
                source,
                "BUILT_IN_PERMISSION_PROFILE_DANGER_FULL_ACCESS",
                ":danger-full-access",
            ),
        },
        "identity_sidecar": "ActivePermissionProfile identifies the named/implicit profile that produced runtime permissions",
        "per_command_overlay": "AdditionalPermissionProfile carries temporary filesystem/network permission widening",
        "evidence": _evidence(source, "PermissionProfile/SandboxEnforcement"),
    }, complete


def _selection(
    permissions: SourceFile,
    config: SourceFile,
    profile_state: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[dict[str, Any], bool]:
    permission_tokens = (
        ("POLICY_DEFAULT_BUILTIN_SELECTOR_MISSING", "default_builtin_permission_profile_name"),
        ("POLICY_PROJECT_TRUST_GATE_MISSING", "active_project.is_trusted() || active_project.is_untrusted()"),
        ("POLICY_BUILTIN_PROFILE_COMPILER_MISSING", "compile_permission_profile_selection"),
        ("POLICY_NAMED_PROFILE_RESOLVER_MISSING", "resolve_permission_profile"),
        ("POLICY_RESERVED_PROFILE_PREFIX_MISSING", "profile_name.starts_with(':')"),
    )
    config_tokens = (
        ("POLICY_EFFECTIVE_SELECTION_MISSING", "resolve_effective_permission_selection"),
        ("POLICY_DEFAULT_SELECTION_MISSING", "resolve_default_permissions"),
        ("POLICY_REQUIREMENTS_ALLOWLIST_MISSING", "allowed_permission_profiles"),
        ("POLICY_REQUIREMENTS_FORCE_SELECTION_MISSING", "requirements_force_profile_selection"),
        ("POLICY_DISALLOWED_PROFILE_FALLBACK_MISSING", "falling back from `{selected_permissions}` to required value `{fallback_permissions}`"),
    )
    state_tokens = (
        ("POLICY_PROFILE_STATE_MISSING", "struct PermissionProfileState"),
        ("POLICY_PROFILE_CONSTRAINT_WRAPPER_MISSING", "Constrained::new"),
        ("POLICY_PROFILE_ACTIVE_SNAPSHOT_MISSING", "active_permission_profile"),
        ("POLICY_PROFILE_WORKSPACE_ROOTS_MISSING", "profile_workspace_roots"),
        ("POLICY_PROFILE_MUTATION_CONSTRAINT_MISSING", "can_set_legacy_permission_profile"),
    )
    complete = _require(
        diagnostics, permissions, permission_tokens, entity="execution_policy.selection.permissions"
    )
    complete &= _require(
        diagnostics, config, config_tokens, entity="execution_policy.selection.config"
    )
    complete &= _require(
        diagnostics, profile_state, state_tokens, entity="execution_policy.selection.state"
    )
    return {
        "selection_order": [
            "explicit/default override or valid persisted profile",
            "configured default_permissions",
            "managed allowed_permission_profiles/default_permissions constraint",
            "implicit built-in profile when no explicit profile remains",
        ],
        "managed_constraint_behavior": "disallowed configured profile falls back to the requirements-selected profile; missing required fallback is an error",
        "implicit_builtin_rule": {
            "workspace": "active project reports trusted or untrusted AND Windows sandbox is not disabled",
            "read_only": "otherwise",
        },
        "named_profile_compilation": "configured profile inheritance compiles to filesystem/network sandbox policy",
        "runtime_snapshot": "PermissionProfileState constrains later mutation and preserves active profile identity/workspace roots",
        "evidence": {
            "permissions": _evidence(permissions, "default_builtin_permission_profile_name/compile_permission_profile_selection"),
            "config": _evidence(config, "resolve_effective_permission_selection/resolve_default_permissions"),
            "profile_state": _evidence(profile_state, "PermissionProfileState"),
        },
    }, complete


def _managed_requirements(
    source: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("POLICY_REQUIREMENT_SOURCE_MISSING", "pub enum RequirementSource"),
        ("POLICY_CONSTRAINED_SOURCE_MISSING", "pub struct ConstrainedWithSource"),
        ("POLICY_REQUIREMENT_APPROVAL_MISSING", "pub approval_policy: ConstrainedWithSource<AskForApproval>"),
        ("POLICY_REQUIREMENT_REVIEWER_MISSING", "pub approvals_reviewer: ConstrainedWithSource<ApprovalsReviewer>"),
        ("POLICY_REQUIREMENT_PROFILE_MISSING", "pub permission_profile: ConstrainedWithSource<PermissionProfile>"),
        ("POLICY_REQUIREMENT_WINDOWS_SANDBOX_MISSING", "pub windows_sandbox_mode: ConstrainedWithSource<Option<WindowsSandboxModeToml>>"),
        ("POLICY_REQUIREMENT_EXEC_RULES_MISSING", "pub exec_policy: Option<Sourced<RequirementsExecPolicy>>"),
        ("POLICY_REQUIREMENT_FILESYSTEM_MISSING", "pub filesystem: Option<Sourced<FilesystemConstraints>>"),
        ("POLICY_REQUIREMENT_AUTO_REVIEW_MISSING", "pub auto_review_required_models"),
        ("POLICY_REQUIREMENT_ENTERPRISE_SOURCE_MISSING", "EnterpriseManaged"),
        ("POLICY_REQUIREMENT_SYSTEM_SOURCE_MISSING", "SystemRequirementsToml"),
        ("POLICY_REQUIREMENT_MDM_SOURCE_MISSING", "MdmManagedPreferences"),
    )
    complete = _require(diagnostics, source, tokens, entity="execution_policy.managed_requirements")
    return {
        "authority_sources": [
            "MDM managed preferences",
            "enterprise-managed requirements",
            "system requirements.toml",
            "legacy managed configuration",
            "composite of multiple requirement layers",
        ],
        "constrained_fields": [
            "approval_policy",
            "approvals_reviewer",
            "permission_profile",
            "windows_sandbox_mode",
            "filesystem constraints",
            "exec_policy",
            "auto-review-required models",
        ],
        "excluded_managed_fields": {
            "network/proxy constraints": "contract/routing",
            "additional developer instructions": "contract/prompt",
            "plugin/MCP requirements": "contract/plugin and contract/mcp",
            "shell environment policy": "contract/environment",
        },
        "evidence": _evidence(source, "ConfigRequirements/RequirementSource"),
    }, complete


def _runtime_resolution(
    source: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("POLICY_TURN_APPROVAL_ACCESSOR_MISSING", "pub(crate) fn approval_policy"),
        ("POLICY_TURN_PROFILE_ACCESSOR_MISSING", "pub(crate) fn permission_profile"),
        ("POLICY_ENV_PROFILE_FALLBACK_MISSING", "permission_profile_or_else"),
        ("POLICY_FILESYSTEM_POLICY_ACCESSOR_MISSING", "pub(crate) fn file_system_sandbox_policy"),
        ("POLICY_NETWORK_POLICY_ACCESSOR_MISSING", "pub(crate) fn network_sandbox_policy"),
        ("POLICY_COMPAT_SANDBOX_ACCESSOR_MISSING", "pub(crate) fn sandbox_policy"),
        ("POLICY_PREFIX_RULE_GATE_MISSING", "pub(crate) fn allow_prefix_rules"),
        ("POLICY_ADDITIONAL_PERMISSION_MERGE_MISSING", "effective_permission_profile"),
        ("POLICY_ENV_SANDBOX_CONTEXT_MISSING", "sandbox_context"),
    )
    complete = _require(diagnostics, source, tokens, entity="execution_policy.runtime")
    return {
        "approval_policy": "turn config permissions approval policy; step-scoped consumers use captured settings",
        "permission_profile": "selected environment profile when ready, otherwise thread config effective profile",
        "derived_policies": ["filesystem sandbox policy", "network sandbox allow/restrict bit", "legacy compatibility SandboxPolicy"],
        "additional_permissions": "per-command/session grants may widen the selected profile inside the environment sandbox context",
        "prefix_rule_gate": "cyber-specialty or managed auto-review ignore_rules may disable reusable prefix-rule behavior",
        "boundary": "environment identity/cwd/backend and proxy routing remain outside this domain",
        "evidence": _evidence(source, "TurnContext permission/approval accessors"),
    }, complete


def _exec_policy(
    source: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[dict[str, Any], bool]:
    tokens = (
        ("POLICY_EXEC_REQUEST_MISSING", "pub(crate) struct ExecApprovalRequest"),
        ("POLICY_PROMPT_REJECTION_MISSING", "prompt_is_rejected_by_policy"),
        ("POLICY_APPROVAL_NEVER_MISSING", "AskForApproval::Never"),
        ("POLICY_APPROVAL_ON_REQUEST_MISSING", "AskForApproval::OnRequest"),
        ("POLICY_APPROVAL_UNLESS_TRUSTED_MISSING", "AskForApproval::UnlessTrusted"),
        ("POLICY_APPROVAL_GRANULAR_MISSING", "AskForApproval::Granular"),
        ("POLICY_DECISION_FORBIDDEN_MISSING", "Decision::Forbidden"),
        ("POLICY_DECISION_PROMPT_MISSING", "Decision::Prompt"),
        ("POLICY_DECISION_ALLOW_MISSING", "Decision::Allow"),
        ("POLICY_REQUIREMENT_FORBIDDEN_MISSING", "ExecApprovalRequirement::Forbidden"),
        ("POLICY_REQUIREMENT_APPROVAL_MISSING", "ExecApprovalRequirement::NeedsApproval"),
        ("POLICY_REQUIREMENT_SKIP_MISSING", "ExecApprovalRequirement::Skip"),
        ("POLICY_ENV_RULE_OVERLAY_MISSING", "current_for_environment"),
        ("POLICY_REUSABLE_APPROVAL_GATE_MISSING", "auto_amendment_allowed = allow_prefix_rules == AllowPrefixRules::Honor"),
    )
    complete = _require(diagnostics, source, tokens, entity="execution_policy.exec_policy")
    return {
        "decision_space": ["allow", "prompt", "forbidden"],
        "inputs": [
            "command segments",
            "approval policy",
            "effective permission profile",
            "environment requirements exec policy",
            "sandbox override request",
            "prefix-rule eligibility",
        ],
        "approval_intersection": {
            "never": "policy-generated prompts are rejected; unmatched commands may still run under sandbox enforcement",
            "unless_trusted": "unmatched commands prompt unless an explicit rule allows them",
            "on_request": "unmatched non-dangerous commands can run under the active sandbox; override requests may prompt",
            "granular": "rule prompts and sandbox-approval prompts are independently gateable",
        },
        "explicit_allow_rule": "sandbox bypass is allowed only when every parsed command segment is explicitly allowed by exec policy",
        "reusable_amendments": "only proposed/applied when prefix rules are honored for the model/turn",
        "evidence": _evidence(source, "ExecPolicyManager/ExecApprovalRequest"),
    }, complete


class ExecutionPolicyExtractor:
    extractor_id = EXTRACTOR_ID
    source_spec_ids = tuple(SOURCE_IDS.values())

    def extract(self, snapshot: SourceSnapshot, diagnostics: DiagnosticCollector) -> ExtractorResult:
        sources = {key: _source(snapshot, key) for key in SOURCE_IDS}
        missing = [key for key, source in sources.items() if source is None]
        if missing:
            for key in missing:
                _missing(
                    diagnostics,
                    code="EXECUTION_POLICY_SOURCE_UNAVAILABLE",
                    message=f"Execution-policy source is unavailable: {key}",
                    source=None,
                    entity=f"execution_policy.source.{key}",
                )
            return ExtractorResult(
                extractor_id=EXTRACTOR_ID,
                schema_version=SCHEMA_VERSION,
                data={},
                semantic_complete=False,
                source_spec_ids=self.source_spec_ids,
            )

        permission_model, model_ok = _permission_model(sources["protocol"], diagnostics)  # type: ignore[arg-type]
        selection, selection_ok = _selection(
            sources["permissions"],  # type: ignore[arg-type]
            sources["config"],  # type: ignore[arg-type]
            sources["profile_state"],  # type: ignore[arg-type]
            diagnostics,
        )
        requirements, requirements_ok = _managed_requirements(
            sources["requirements"], diagnostics  # type: ignore[arg-type]
        )
        runtime, runtime_ok = _runtime_resolution(
            sources["turn"], diagnostics  # type: ignore[arg-type]
        )
        exec_policy, exec_ok = _exec_policy(
            sources["exec_policy"], diagnostics  # type: ignore[arg-type]
        )
        complete = model_ok and selection_ok and requirements_ok and runtime_ok and exec_ok
        body: dict[str, Any] = {
            "$schema": SCHEMA_ID,
            "schema_version": SCHEMA_VERSION,
            "ownership": {
                "owns": [
                    "permission profile identity and selection",
                    "managed permission/approval constraints",
                    "filesystem and network sandbox authority bits",
                    "approval policy and reviewer authority",
                    "exec-policy allow/prompt/forbid decisions",
                    "per-command permission widening and reusable rule gates",
                ],
                "does_not_own": [
                    "shell environment contents or PATH construction",
                    "environment discovery, cwd, or executor lifecycle",
                    "network proxy transport/routing/domain policy",
                    "prompt rendering of permission instructions",
                    "plugin or MCP runtime semantics",
                ],
            },
            "permission_model": permission_model,
            "selection": selection,
            "managed_requirements": requirements,
            "runtime_resolution": runtime,
            "exec_policy": exec_policy,
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
def _factory() -> ExecutionPolicyExtractor:
    return ExecutionPolicyExtractor()
