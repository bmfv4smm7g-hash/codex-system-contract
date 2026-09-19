from pathlib import Path

path = Path("toolchain/tests/test_current_source_layouts.py")
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
