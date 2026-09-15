from __future__ import annotations

from codex_wire_audit.diagnostics import DiagnosticCollector
from codex_wire_audit.extractors.execution_policy import ExecutionPolicyExtractor
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
        roles=("execution_policy",),
        expected_symbols=(),
        extractor_ids=("extractor.execution_policy",),
    )
    return SourceFile.create(spec=spec, selected_path=path, raw_bytes=text.encode())


def _snapshot(*, omit: str | None = None, break_exec: bool = False) -> SourceSnapshot:
    protocol = '''
    pub enum SandboxEnforcement { Managed, Disabled, External }
    pub const BUILT_IN_PERMISSION_PROFILE_READ_ONLY: &str = ":read-only";
    pub const BUILT_IN_PERMISSION_PROFILE_WORKSPACE: &str = ":workspace";
    pub const BUILT_IN_PERMISSION_PROFILE_DANGER_FULL_ACCESS: &str = ":danger-full-access";
    pub enum PermissionProfile { Managed, Disabled, External }
    pub struct ActivePermissionProfile
    pub struct AdditionalPermissionProfile
    '''
    permissions = '''
    default_builtin_permission_profile_name
    active_project.is_trusted() || active_project.is_untrusted()
    compile_permission_profile_selection resolve_permission_profile
    profile_name.starts_with(':')
    BUILT_IN_WORKSPACE_PROFILE BUILT_IN_READ_ONLY_PROFILE
    '''
    requirements = '''
    pub enum RequirementSource { MdmManagedPreferences, EnterpriseManaged, SystemRequirementsToml }
    pub struct ConstrainedWithSource<T>
    pub approval_policy: ConstrainedWithSource<AskForApproval>
    pub approvals_reviewer: ConstrainedWithSource<ApprovalsReviewer>
    pub permission_profile: ConstrainedWithSource<PermissionProfile>
    pub windows_sandbox_mode: ConstrainedWithSource<Option<WindowsSandboxModeToml>>
    pub exec_policy: Option<Sourced<RequirementsExecPolicy>>
    pub filesystem: Option<Sourced<FilesystemConstraints>>
    pub auto_review_required_models: Option<Sourced<BTreeSet<String>>>
    '''
    config = '''
    resolve_effective_permission_selection resolve_default_permissions
    allowed_permission_profiles requirements_force_profile_selection
    falling back from `{selected_permissions}` to required value `{fallback_permissions}`
    '''
    profile_state = '''
    struct PermissionProfileState
    Constrained::new active_permission_profile profile_workspace_roots
    can_set_legacy_permission_profile
    '''
    turn = '''
    pub(crate) fn approval_policy pub(crate) fn permission_profile
    permission_profile_or_else pub(crate) fn file_system_sandbox_policy
    pub(crate) fn network_sandbox_policy pub(crate) fn sandbox_policy
    pub(crate) fn allow_prefix_rules effective_permission_profile sandbox_context
    '''
    exec_policy = '''
    pub(crate) struct ExecApprovalRequest
    prompt_is_rejected_by_policy
    AskForApproval::Never AskForApproval::OnRequest AskForApproval::UnlessTrusted AskForApproval::Granular
    Decision::Forbidden Decision::Prompt Decision::Allow
    ExecApprovalRequirement::Forbidden ExecApprovalRequirement::NeedsApproval ExecApprovalRequirement::Skip
    current_for_environment
    auto_amendment_allowed = allow_prefix_rules == AllowPrefixRules::Honor
    '''
    if break_exec:
        exec_policy = exec_policy.replace("Decision::Forbidden", "")
    rows = {
        "protocol": _file("source_spec.extra.policy_protocol", "policy_protocol", "codex-rs/protocol/src/models.rs", protocol),
        "permissions": _file("source_spec.extra.policy_permissions", "policy_permissions", "codex-rs/core/src/config/permissions.rs", permissions),
        "requirements": _file("source_spec.extra.policy_requirements", "policy_requirements", "codex-rs/config/src/config_requirements.rs", requirements),
        "config": _file("source_spec.extra.policy_config_resolution", "policy_config_resolution", "codex-rs/core/src/config/mod.rs", config),
        "profile_state": _file("source_spec.extra.policy_profile_state", "policy_profile_state", "codex-rs/core/src/config/resolved_permission_profile.rs", profile_state),
        "turn": _file("source_spec.extra.policy_turn_context", "policy_turn_context", "codex-rs/core/src/session/turn_context.rs", turn),
        "exec_policy": _file("source_spec.extra.policy_exec_policy", "policy_exec_policy", "codex-rs/core/src/exec_policy.rs", exec_policy),
    }
    if omit:
        rows.pop(omit)
    files = {value.spec_id: value for value in rows.values()}
    revision = SourceRevision(
        "fixture", "openai/codex", "fixture", "1" * 40,
        SourceSnapshot.digest_files(files), False,
    )
    return SourceSnapshot(revision, files)


def test_default_registry_assigns_policy_sources_to_policy_domain():
    registry = build_registry(load_legacy_modules())
    expected = {
        "source_spec.extra.policy_protocol",
        "source_spec.extra.policy_permissions",
        "source_spec.extra.policy_requirements",
        "source_spec.extra.policy_config_resolution",
        "source_spec.extra.policy_profile_state",
        "source_spec.extra.policy_turn_context",
        "source_spec.extra.policy_exec_policy",
    }
    observed = {
        spec.id
        for spec in registry.specs
        if "extractor.execution_policy" in spec.extractor_ids
    }
    assert observed == expected
    assert all(registry.get(spec_id).roles == ("execution_policy",) for spec_id in expected)


def test_execution_policy_extracts_authority_without_claiming_neighbor_domains():
    diagnostics = DiagnosticCollector()
    result = ExecutionPolicyExtractor().extract(_snapshot(), diagnostics)
    assert result.semantic_complete
    assert diagnostics.summary()["error"] == 0
    assert result.data["$schema"].endswith("execution-policy-semantics-v1.schema.json")
    assert result.data["permission_model"]["builtin_profiles"]["workspace"] == ":workspace"
    assert result.data["selection"]["selection_order"][0].startswith("explicit/default")
    assert result.data["exec_policy"]["decision_space"] == ["allow", "prompt", "forbidden"]
    assert "network proxy transport/routing/domain policy" in result.data["ownership"]["does_not_own"]
    assert "shell environment contents or PATH construction" in result.data["ownership"]["does_not_own"]
    assert len(result.data["semantic_digest"]) == 64


def test_missing_policy_source_fails_closed():
    diagnostics = DiagnosticCollector()
    result = ExecutionPolicyExtractor().extract(_snapshot(omit="requirements"), diagnostics)
    assert not result.semantic_complete
    assert result.data == {}
    assert any(item.code == "EXECUTION_POLICY_SOURCE_UNAVAILABLE" for item in diagnostics.values())


def test_exec_policy_drift_is_error_not_silent_fallback():
    diagnostics = DiagnosticCollector()
    result = ExecutionPolicyExtractor().extract(_snapshot(break_exec=True), diagnostics)
    assert not result.semantic_complete
    assert any(item.code == "POLICY_DECISION_FORBIDDEN_MISSING" for item in diagnostics.values())


def test_policy_source_identity_cannot_be_repurposed_by_overlay():
    registry = build_registry(load_legacy_modules())
    spec = registry.get("source_spec.extra.policy_exec_policy")
    assert spec.primary_path == "codex-rs/core/src/exec_policy.rs"
    assert spec.legacy_key == "policy_exec_policy"
    assert spec.group is SourceGroup.EXTRA
