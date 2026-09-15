from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one marker, found {count}: {old[:100]!r}")
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
    tail = '        "extractor.execution_policy"\n      ]'
    if block.count(tail) != 1:
        raise SystemExit(f"{path}: extractor tail drifted for {profile_id}")
    block = block.replace(old_description, new_description, 1)
    block = block.replace(
        tail,
        '        "extractor.execution_policy",\n'
        f'        "{extractor}"\n'
        "      ]",
        1,
    )
    file.write_text(text[:start] + block + text[end:], encoding="utf-8")


registry = "toolchain/codex_wire_audit/source_registry.py"
generated_marker = '''    specs.append(SourceSpec(
        id="source_spec.extra.generated_config_schema",'''
plugin_specs = '''    plugin_specs = (
        ("source_spec.extra.plugin_model", "plugin_model", "codex-rs/plugin/src/lib.rs", ("PluginCapabilitySummary", "AppDeclaration", "PluginTelemetryMetadata")),
        ("source_spec.extra.plugin_load_outcome", "plugin_load_outcome", "codex-rs/plugin/src/load_outcome.rs", ("LoadedPlugin", "PluginLoadOutcome", "effective_plugin_skill_roots")),
        ("source_spec.extra.plugin_manifest", "plugin_manifest", "codex-rs/core-plugins/src/manifest.rs", ("PluginManifestFormat", "RawPluginManifest", "load_plugin_manifest_with_format")),
        ("source_spec.extra.plugin_loader", "plugin_loader", "codex-rs/core-plugins/src/loader.rs", ("load_plugins_from_layer_stack", "PluginLoadScope", "load_plugin_skill_inventory")),
        ("source_spec.extra.plugin_manager", "plugin_manager", "codex-rs/core-plugins/src/manager.rs", ("PluginsConfigInput", "plugins_for_config", "plugin_skill_snapshots_for_config")),
        ("source_spec.extra.plugin_mentions", "plugin_mentions", "codex-rs/core/src/plugins/mentions.rs", ("collect_explicit_plugin_mentions", "collect_explicit_plugin_ids", "PLUGIN_TEXT_MENTION_SIGIL")),
        ("source_spec.extra.plugin_injection", "plugin_injection", "codex-rs/core/src/plugins/injection.rs", ("build_plugin_injections", "PluginInstructions::new", "CODEX_APPS_MCP_SERVER_NAME")),
        ("source_spec.extra.plugin_render", "plugin_render", "codex-rs/core/src/plugins/render.rs", ("render_explicit_plugin_instructions", "MAX_EXPLICIT_PLUGIN_INSTRUCTIONS_BYTES")),
    )
'''
replace_once(registry, generated_marker, plugin_specs + generated_marker)

policy_tail = '''    existing_ids = {spec.id for spec in specs}
    for spec_id, legacy_key, path, symbols in policy_specs:
        if spec_id in existing_ids:
            continue
        specs.append(SourceSpec(
            id=spec_id,
            legacy_key=legacy_key,
            group=SourceGroup.EXTRA,
            path_candidates=(path,),
            required=False,
            roles=("execution_policy",),
            expected_symbols=tuple(symbols),
            extractor_ids=("extractor.execution_policy",),
        ))
    return SourceRegistry(specs)'''
plugin_tail = '''    existing_ids = {spec.id for spec in specs}
    for spec_id, legacy_key, path, symbols in policy_specs:
        if spec_id in existing_ids:
            continue
        specs.append(SourceSpec(
            id=spec_id,
            legacy_key=legacy_key,
            group=SourceGroup.EXTRA,
            path_candidates=(path,),
            required=False,
            roles=("execution_policy",),
            expected_symbols=tuple(symbols),
            extractor_ids=("extractor.execution_policy",),
        ))
    existing_ids = {spec.id for spec in specs}
    for spec_id, legacy_key, path, symbols in plugin_specs:
        if spec_id in existing_ids:
            continue
        specs.append(SourceSpec(
            id=spec_id,
            legacy_key=legacy_key,
            group=SourceGroup.EXTRA,
            path_candidates=(path,),
            required=False,
            roles=("plugin_runtime",),
            expected_symbols=tuple(symbols),
            extractor_ids=("extractor.plugin_runtime",),
        ))
    return SourceRegistry(specs)'''
replace_once(registry, policy_tail, plugin_tail)

init = "toolchain/codex_wire_audit/extractors/__init__.py"
replace_once(
    init,
    "from . import execution_policy as _execution_policy  # noqa: E402,F401\n",
    "from . import execution_policy as _execution_policy  # noqa: E402,F401\nfrom . import plugin_runtime as _plugin_runtime  # noqa: E402,F401\n",
)

profiles = "toolchain/codex_wire_audit/coverage_profiles.v3.json"
edit_profile(
    profiles,
    profile_id="hybrid_v19",
    old_description="Transition profile: canonical generated config schema, config-to-surface graph, turn metadata, context management, prompt/context composition, and execution authority; remaining protocol families may still use the frozen legacy adapter.",
    new_description="Transition profile: canonical generated config schema, config-to-surface graph, turn metadata, context management, prompt/context composition, execution authority, and plugin runtime capabilities; remaining protocol families may still use the frozen legacy adapter.",
    extractor="extractor.plugin_runtime",
)
edit_profile(
    profiles,
    profile_id="codex_wire_full",
    old_description="Repository-wide canonical wire, local-storage, prompt-context, and execution-policy proof. Legacy reconstruction cannot satisfy it, and historical metadata transitions and runtime conformance are part of the proof surface.",
    new_description="Repository-wide canonical wire, local-storage, prompt-context, execution-policy, and plugin-runtime proof. Legacy reconstruction cannot satisfy it, and historical metadata transitions and runtime conformance are part of the proof surface.",
    extractor="extractor.plugin_runtime",
)
fixture_marker = '''    {
      "allow_legacy_reconstruction": true,
      "description": "Deterministic unit/integration fixture profile.",'''
plugin_profile = '''    {
      "allow_legacy_reconstruction": false,
      "description": "Focused source-derived plugin package/load/capability proof without claiming MCP transport, app execution, skill semantics, prompt placement, or remote HTTP routing.",
      "id": "plugin_runtime_only",
      "required_dimensions": [
        "schema",
        "profile",
        "provenance"
      ],
      "required_extractors": [
        "extractor.plugin_runtime"
      ],
      "required_history_keys": [],
      "required_runtime_scenarios": [],
      "version": "1.0.0"
    },
'''
replace_once(profiles, fixture_marker, plugin_profile + fixture_marker)

release_spec = "toolchain/codex_wire_audit/release_spec.v1.json"
canonical_marker = '''    {
      "extractor_ids": [],
      "id": "canonical_system_contract",'''
capability = '''    {
      "extractor_ids": [
        "extractor.plugin_runtime"
      ],
      "id": "plugin_runtime",
      "profile_assertions": {
        "codex_wire_full": {
          "required_extractors_contains": [
            "extractor.plugin_runtime"
          ]
        },
        "hybrid_v19": {
          "required_extractors_contains": [
            "extractor.plugin_runtime"
          ]
        },
        "plugin_runtime_only": {
          "required_extractors_contains": [
            "extractor.plugin_runtime"
          ]
        }
      },
      "required_resources": [
        "extractors/plugin_runtime.py",
        "proof_schema_templates/plugin-runtime-semantics-v1.schema.json",
        "coverage_profiles.v3.json"
      ],
      "status": "active_package"
    },
'''
replace_once(release_spec, canonical_marker, capability + canonical_marker)
replace_once(
    release_spec,
    '            "extractor.prompt_context",\n            "extractor.execution_policy"\n          ]',
    '            "extractor.prompt_context",\n            "extractor.execution_policy",\n            "extractor.plugin_runtime"\n          ]',
)

print("plugin domain wiring: patched exact markers")
