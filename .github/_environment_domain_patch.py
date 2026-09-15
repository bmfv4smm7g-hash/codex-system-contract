from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one marker, found {count}: {old[:110]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


def edit_profile(
    path: str,
    *,
    profile_id: str,
    old_description: str,
    new_description: str,
    extractor: str,
) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    id_marker = f'      "id": "{profile_id}",'
    if text.count(id_marker) != 1:
        raise SystemExit(f"{path}: profile id is not unique: {profile_id}")
    id_pos = text.index(id_marker)
    start = text.rfind("    {\n", 0, id_pos)
    end_marker = "\n    },"
    end = text.find(end_marker, id_pos)
    if start < 0 or end < 0:
        raise SystemExit(f"{path}: cannot isolate profile object: {profile_id}")
    end += len(end_marker)
    block = text[start:end]
    if block.count(old_description) != 1:
        raise SystemExit(f"{path}: description marker drifted for {profile_id}")
    tail = '        "extractor.plugin_runtime"\n      ]'
    if block.count(tail) != 1:
        raise SystemExit(f"{path}: extractor tail drifted for {profile_id}")
    block = block.replace(old_description, new_description, 1)
    block = block.replace(
        tail,
        '        "extractor.plugin_runtime",\n'
        f'        "{extractor}"\n'
        "      ]",
        1,
    )
    file.write_text(text[:start] + block + text[end:], encoding="utf-8")


# Normalize a migration fixture/check token to the exact upstream wording.
extractor = "toolchain/codex_wire_audit/extractors/execution_environment.py"
replace_once(
    extractor,
    '("ENV_LOCAL_RESERVED_MISSING", "environment id `local` is reserved"),',
    '("ENV_LOCAL_RESERVED_MISSING", "is reserved for EnvironmentManager"),',
)
test = "toolchain/tests/test_execution_environment_extractor.py"
replace_once(
    test,
    '    environment id `local` is reserved\n',
    '    environment id `{LOCAL_ENVIRONMENT_ID}` is reserved for EnvironmentManager\n',
)

registry = "toolchain/codex_wire_audit/source_registry.py"
generated_marker = '''    specs.append(SourceSpec(
        id="source_spec.extra.generated_config_schema",'''
environment_specs = '''    environment_specs = (
        ("source_spec.extra.environment_shell_policy", "environment_shell_policy", "codex-rs/protocol/src/config_types.rs", ("ShellEnvironmentPolicyInherit", "ShellEnvironmentPolicy", "use_profile")),
        ("source_spec.extra.environment_shell_builder", "environment_shell_builder", "codex-rs/protocol/src/shell_environment.rs", ("NON_INHERITABLE_ENV_VARS", "create_env_from_vars", "CODEX_THREAD_ID_ENV_VAR")),
        ("source_spec.extra.environment_selection", "environment_selection", "codex-rs/core/src/environment_selection.rs", ("EnvironmentConfigOrigin", "ThreadEnvironments", "default_thread_environment_selections")),
        ("source_spec.extra.environment_shell_snapshot", "environment_shell_snapshot", "codex-rs/core/src/shell_snapshot.rs", ("ShellSnapshot", "SNAPSHOT_TIMEOUT", "cleanup_stale_snapshots")),
        ("source_spec.extra.environment_manager", "environment_manager", "codex-rs/exec-server/src/environment.rs", ("EnvironmentManager", "EnvironmentObservedStatus", "default_environment_ids")),
        ("source_spec.extra.environment_turn_context", "environment_turn_context", "codex-rs/core/src/session/turn_context.rs", ("TurnEnvironment", "shell_environment_policy", "workspace_roots")),
    )
'''
replace_once(registry, generated_marker, environment_specs + generated_marker)
plugin_call = '''    _append_optional_specs(
        specs, plugin_specs, role="plugin_runtime", extractor_id="extractor.plugin_runtime"
    )
    return SourceRegistry(specs)'''
environment_call = '''    _append_optional_specs(
        specs, plugin_specs, role="plugin_runtime", extractor_id="extractor.plugin_runtime"
    )
    _append_optional_specs(
        specs,
        environment_specs,
        role="execution_environment",
        extractor_id="extractor.execution_environment",
    )
    return SourceRegistry(specs)'''
replace_once(registry, plugin_call, environment_call)

init = "toolchain/codex_wire_audit/extractors/__init__.py"
replace_once(
    init,
    "from . import plugin_runtime as _plugin_runtime  # noqa: E402,F401\n",
    "from . import plugin_runtime as _plugin_runtime  # noqa: E402,F401\nfrom . import execution_environment as _execution_environment  # noqa: E402,F401\n",
)

profiles = "toolchain/codex_wire_audit/coverage_profiles.v3.json"
edit_profile(
    profiles,
    profile_id="hybrid_v19",
    old_description="Transition profile: canonical generated config schema, config-to-surface graph, turn metadata, context management, prompt/context composition, execution authority, and plugin runtime capabilities; remaining protocol families may still use the frozen legacy adapter.",
    new_description="Transition profile: canonical generated config schema, config-to-surface graph, turn metadata, context management, prompt/context composition, execution authority, plugin runtime capabilities, and execution-environment context; remaining protocol families may still use the frozen legacy adapter.",
    extractor="extractor.execution_environment",
)
edit_profile(
    profiles,
    profile_id="codex_wire_full",
    old_description="Repository-wide canonical wire, local-storage, prompt-context, execution-policy, and plugin-runtime proof. Legacy reconstruction cannot satisfy it, and historical metadata transitions and runtime conformance are part of the proof surface.",
    new_description="Repository-wide canonical wire, local-storage, prompt-context, execution-policy, plugin-runtime, and execution-environment proof. Legacy reconstruction cannot satisfy it, and historical metadata transitions and runtime conformance are part of the proof surface.",
    extractor="extractor.execution_environment",
)
fixture_marker = '''    {
      "allow_legacy_reconstruction": true,
      "description": "Deterministic unit/integration fixture profile.",'''
environment_profile = '''    {
      "allow_legacy_reconstruction": false,
      "description": "Focused source-derived execution-environment proof without claiming permission authority, proxy routing, prompt placement, plugin/MCP semantics, or durable storage layout.",
      "id": "execution_environment_only",
      "required_dimensions": [
        "schema",
        "profile",
        "provenance"
      ],
      "required_extractors": [
        "extractor.execution_environment"
      ],
      "required_history_keys": [],
      "required_runtime_scenarios": [],
      "version": "1.0.0"
    },
'''
replace_once(profiles, fixture_marker, environment_profile + fixture_marker)

release_spec = "toolchain/codex_wire_audit/release_spec.v1.json"
canonical_marker = '''    {
      "extractor_ids": [],
      "id": "canonical_system_contract",'''
capability = '''    {
      "extractor_ids": [
        "extractor.execution_environment"
      ],
      "id": "execution_environment",
      "profile_assertions": {
        "codex_wire_full": {
          "required_extractors_contains": [
            "extractor.execution_environment"
          ]
        },
        "execution_environment_only": {
          "required_extractors_contains": [
            "extractor.execution_environment"
          ]
        },
        "hybrid_v19": {
          "required_extractors_contains": [
            "extractor.execution_environment"
          ]
        }
      },
      "required_resources": [
        "extractors/execution_environment.py",
        "proof_schema_templates/execution-environment-semantics-v1.schema.json",
        "coverage_profiles.v3.json"
      ],
      "status": "active_package"
    },
'''
replace_once(release_spec, canonical_marker, capability + canonical_marker)
replace_once(
    release_spec,
    '            "extractor.execution_policy",\n            "extractor.plugin_runtime"\n          ]',
    '            "extractor.execution_policy",\n            "extractor.plugin_runtime",\n            "extractor.execution_environment"\n          ]',
)

print("environment domain wiring: patched exact markers")
