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


if __name__ == "__main__":
    main()
