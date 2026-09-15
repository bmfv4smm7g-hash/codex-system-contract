from __future__ import annotations

from pathlib import Path

PATH = Path("toolchain/codex_wire_audit/source_registry.py")


def replace_once(old: str, new: str) -> None:
    text = PATH.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"source_registry.py: expected one marker, found {count}: {old[:120]!r}")
    PATH.write_text(text.replace(old, new, 1), encoding="utf-8")


function_marker = '''def from_legacy_maps(
    base_files: Mapping[str, str],'''
helper = '''def _append_optional_specs(
    specs: list[SourceSpec],
    rows: Iterable[tuple[str, str, str, tuple[str, ...]]],
    *,
    role: str,
    extractor_id: str,
) -> None:
    existing_ids = {spec.id for spec in specs}
    for spec_id, legacy_key, path, symbols in rows:
        if spec_id in existing_ids:
            continue
        specs.append(SourceSpec(
            id=spec_id,
            legacy_key=legacy_key,
            group=SourceGroup.EXTRA,
            path_candidates=(path,),
            required=False,
            roles=(role,),
            expected_symbols=tuple(symbols),
            extractor_ids=(extractor_id,),
        ))
        existing_ids.add(spec_id)


def from_legacy_maps(
    base_files: Mapping[str, str],'''
replace_once(function_marker, helper)


def loop(role: str, extractor: str, rows: str) -> str:
    return f'''    existing_ids = {{spec.id for spec in specs}}
    for spec_id, legacy_key, path, symbols in {rows}:
        if spec_id in existing_ids:
            continue
        specs.append(SourceSpec(
            id=spec_id,
            legacy_key=legacy_key,
            group=SourceGroup.EXTRA,
            path_candidates=(path,),
            required=False,
            roles=("{role}",),
            expected_symbols=tuple(symbols),
            extractor_ids=("{extractor}",),
        ))
'''


def call(role: str, extractor: str, rows: str) -> str:
    return f'''    _append_optional_specs(
        specs, {rows}, role="{role}", extractor_id="{extractor}"
    )
'''

for role, extractor, rows in (
    ("context_management", "extractor.context_management", "context_specs"),
    ("local_storage", "extractor.local_storage", "local_storage_specs"),
    ("prompt_context", "extractor.prompt_context", "prompt_specs"),
    ("execution_policy", "extractor.execution_policy", "policy_specs"),
    ("plugin_runtime", "extractor.plugin_runtime", "plugin_specs"),
):
    replace_once(loop(role, extractor, rows), call(role, extractor, rows))

print("source registry: deduplicated optional domain registration")
