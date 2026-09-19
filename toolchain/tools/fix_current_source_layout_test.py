from pathlib import Path


def main() -> None:
    toolchain = Path(__file__).resolve().parents[1]

    path = toolchain / "tests/test_current_source_layouts.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "from codex_wire_audit.source_registry import default_registry\n",
        "from codex_wire_audit.legacy import load_legacy_modules\n"
        "from codex_wire_audit.orchestrator import build_registry\n",
    )
    text = text.replace(
        '    compact = default_registry().get("source_spec.base.compact")\n',
        '    compact = build_registry(load_legacy_modules()).get("source_spec.base.compact")\n',
    )
    path.write_text(text, encoding="utf-8")

    schema = toolchain / "codex_wire_audit/schema_templates/turn-metadata-semantics.schema.json"
    schema_text = schema.read_text(encoding="utf-8")
    old = '''            "timing_and_history",
            "compaction",
'''
    new = '''            "timing_and_history",
            "analytics_state",
            "compaction",
'''
    if schema_text.count(old) != 1:
        raise RuntimeError("turn metadata identity-domain enum marker changed")
    schema.write_text(schema_text.replace(old, new, 1), encoding="utf-8")

    mutation = toolchain / "codex_wire_audit/extractors/app_server_history_mutation.py"
    mutation_text = mutation.read_text(encoding="utf-8")
    build_marker = '''def build_history_mutation(
'''
    helper = '''def _fork_has_fresh_id(thread_manager: SourceFile) -> bool:
    legacy = _has(
        thread_manager,
        "The new thread will have",
        "a fresh id.",
        "pub async fn fork_prepared_thread",
    )
    current = _has(
        thread_manager,
        "The new thread has a fresh id.",
        "pub async fn fork_thread",
        "pub async fn fork_prepared_thread",
    )
    return legacy or current


'''
    if mutation_text.count(build_marker) != 1:
        raise RuntimeError("app-server history builder marker changed")
    mutation_text = mutation_text.replace(build_marker, helper + build_marker, 1)
    old_fresh = '''    fork_fresh_id = _has(
        thread_manager,
        "The new thread will have",
        "a fresh id.",
        "pub async fn fork_prepared_thread",
    )
'''
    new_fresh = '''    fork_fresh_id = _fork_has_fresh_id(thread_manager)
'''
    if mutation_text.count(old_fresh) != 1:
        raise RuntimeError("app-server fresh-fork predicate marker changed")
    mutation.write_text(mutation_text.replace(old_fresh, new_fresh, 1), encoding="utf-8")

    makefile = toolchain / "Makefile"
    makefile_text = makefile.read_text(encoding="utf-8")
    old_targets = '''assets: legacy-assets history-assets metrics

check-assets: check-legacy-assets check-history-assets check-metrics schemas
'''
    new_targets = '''assets: legacy-assets history-assets metrics
	$(PYTHON) tools/check_canonical_contract.py --write-assets

check-assets: check-legacy-assets check-history-assets check-metrics schemas
	$(PYTHON) tools/check_canonical_contract.py
'''
    if makefile_text.count(old_targets) != 1:
        raise RuntimeError("Makefile asset target marker changed")
    makefile.write_text(makefile_text.replace(old_targets, new_targets, 1), encoding="utf-8")


if __name__ == "__main__":
    main()
