from __future__ import annotations

import ast
from pathlib import Path

PATH = Path("toolchain/codex_wire_audit/orchestrator.py")

REPLACEMENT = '''
def _attach_integrity(
    report: MutableMapping[str, Any],
    canonical_model: Mapping[str, Any],
) -> None:
    payload = canonical_report_payload(report)
    payload_sha256 = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    integrity = report.get("integrity")
    if not isinstance(integrity, MutableMapping):
        integrity = {}
        report["integrity"] = integrity
    source_revision = canonical_model.get("source_revision") or {}
    model_integrity = canonical_model.get("integrity") or {}
    integrity.update(
        {
            "algorithm": "sha256",
            "canonicalization": "codex-wire-audit-canonical-json-v2",
            "payload_excludes": ["generated_at", "integrity", "status.validated_at"],
            "payload_sha256": payload_sha256,
            "source_set_sha256": source_revision.get("source_set_sha256"),
            "canonical_ir_sha256": model_integrity.get("canonical_ir_sha256"),
        }
    )
'''


class Repair(ast.NodeTransformer):
    def __init__(self) -> None:
        self.functions = 0
        self.calls = 0

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if node.name != "_attach_integrity":
            return self.generic_visit(node)
        self.functions += 1
        replacement = ast.parse(REPLACEMENT).body[0]
        if not isinstance(replacement, ast.FunctionDef):
            raise TypeError("replacement is not a function")
        return ast.copy_location(replacement, node)

    def visit_Call(self, node: ast.Call):
        node = self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == "_attach_integrity":
            if len(node.args) != 1 or node.keywords:
                raise SystemExit("unexpected _attach_integrity call shape")
            node.args.append(ast.Name(id="evolution_contract", ctx=ast.Load()))
            self.calls += 1
        return node

    def visit_If(self, node: ast.If):
        node = self.generic_visit(node)
        if (
            isinstance(node.test, ast.Name)
            and node.test.id in {"config_result", "local_storage_result"}
            and len(node.body) == 1
            and isinstance(node.body[0], ast.Pass)
            and not node.orelse
        ):
            return None
        return node


def main() -> None:
    tree = ast.parse(PATH.read_text(encoding="utf-8"), filename=str(PATH))
    repair = Repair()
    tree = repair.visit(tree)
    if repair.functions != 1:
        raise SystemExit(f"expected one _attach_integrity function, found {repair.functions}")
    if repair.calls != 2:
        raise SystemExit(f"expected two _attach_integrity calls, found {repair.calls}")
    ast.fix_missing_locations(tree)
    compile(tree, str(PATH), "exec")
    PATH.write_text(ast.unparse(tree).rstrip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
