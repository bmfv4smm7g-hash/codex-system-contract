from pathlib import Path

path = Path("toolchain/codex_wire_audit/schema_templates/turn-metadata-semantics.schema.json")
text = path.read_text(encoding="utf-8")
old = '''            "timing_and_history",
            "compaction",
'''
new = '''            "timing_and_history",
            "analytics_state",
            "compaction",
'''
if text.count(old) != 1:
    raise RuntimeError("turn metadata identity-domain enum marker changed")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
