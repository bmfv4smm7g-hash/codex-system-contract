from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path.cwd()
PACKAGE = ROOT / "toolchain" / "codex_wire_audit"
TESTS = ROOT / "toolchain" / "tests"


def write_text(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def order_reference_validation() -> None:
    path = PACKAGE / "system_contract_validation.py"
    text = path.read_text(encoding="utf-8")
    old = '''    model = value["model"]
    failures = validate_evolution_contract(model)
    if failures:
        raise ValueError(failures[0]["code"])
    _references(model)
'''
    new = '''    model = value["model"]
    _references(model)
    failures = validate_evolution_contract(model)
    if failures:
        raise ValueError(failures[0]["code"])
'''
    if text.count(old) != 1:
        raise SystemExit("expected one system-contract validation ordering block")
    write_text(path, text.replace(old, new, 1))


def replacement_function(source: str) -> ast.FunctionDef:
    node = ast.parse(source).body[0]
    if not isinstance(node, ast.FunctionDef):
        raise TypeError("replacement must be a function")
    return node


def repair_generated_direct_test() -> None:
    """Keep the generated direct-contract tests inside the release closure."""
    path = TESTS / "test_direct_system_contract.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    model_function = replacement_function('''
def model() -> dict:
    return contract_for_fixture("responses_metadata_identity_split.rs")
''')

    saw_model = False
    body: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            node.names = [alias for alias in node.names if alias.name != "json"]
            if not node.names:
                continue
        elif isinstance(node, ast.ImportFrom) and node.module == "pathlib":
            node.names = [alias for alias in node.names if alias.name != "Path"]
            if not node.names:
                continue
        elif isinstance(node, ast.Assign):
            names = {
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            if names & {"ROOT", "FIXTURE"}:
                continue
        elif isinstance(node, ast.FunctionDef) and node.name == "model":
            body.append(ast.copy_location(model_function, node))
            saw_model = True
            continue
        body.append(node)

    if not saw_model:
        raise SystemExit("generated direct-contract model helper was not found")
    if any(
        isinstance(node, ast.ImportFrom)
        and node.module == "test_codex_wire_audit_v11"
        and any(alias.name == "contract_for_fixture" for alias in node.names)
        for node in body
    ):
        raise SystemExit("generated direct-contract fixture import already exists")

    import_node = ast.ImportFrom(
        module="test_codex_wire_audit_v11",
        names=[ast.alias(name="contract_for_fixture")],
        level=0,
    )
    insertion = 0
    while insertion < len(body) and isinstance(body[insertion], (ast.Import, ast.ImportFrom)):
        insertion += 1
    body.insert(insertion, import_node)
    tree.body = body
    ast.fix_missing_locations(tree)
    compile(tree, str(path), "exec")
    write_text(path, ast.unparse(tree))


def repair_direct_contract_tests() -> None:
    path = TESTS / "test_system_contract.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    canonical = replacement_function('''
def test_canonical_contract_is_real_source_ir_not_a_narrative_catalog():
    contract = fixture_contract()
    result = validate_system_contract(contract)
    assert result["authority"] == "migrated_semantic_extractors"
    assert result["direct_report_checked"] is False
    assert result["source_bytes_status"] == "not_checked"
    assert contract["model"]["extractors"]["extractor.turn_metadata"]["data"]["fields"]
    assert contract["model"]["source_revision"]["source_mode"] == "fixture"
    assert contract["model"]["status"]["runtime_observation"] == "not_run"
''')
    tampering = replacement_function('''
@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda contract: contract.update(schema="codex-system-contract/v2"), "schema violation"),
        (lambda contract: contract.update(extra="unexpected"), "schema violation"),
        (
            lambda contract: contract["integrity"].update(canonical_sha256="0" * 64),
            "content digest mismatch",
        ),
    ],
)
def test_tampering_is_rejected(mutation, match):
    contract = fixture_contract()
    mutation(contract)
    with pytest.raises(ValueError, match=match):
        validate_system_contract(contract)
''')

    replacements = {
        canonical.name: canonical,
        tampering.name: tampering,
    }
    seen: set[str] = set()
    body: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "codex_wire_audit.system_contract":
            node.names = [alias for alias in node.names if alias.name != "compatibility_views"]
            if not node.names:
                continue
        if isinstance(node, ast.FunctionDef) and node.name in replacements:
            body.append(ast.copy_location(replacements[node.name], node))
            seen.add(node.name)
        else:
            body.append(node)
    if seen != set(replacements):
        raise SystemExit(f"missing stale direct-contract tests: {sorted(set(replacements) - seen)}")
    tree.body = body
    ast.fix_missing_locations(tree)
    compile(tree, str(path), "exec")
    write_text(path, ast.unparse(tree))


def restore_canonical_capability_claim() -> None:
    path = PACKAGE / "release_spec.v1.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    claims = value.get("capability_claims")
    if not isinstance(claims, list):
        raise SystemExit("release spec capability_claims must be a list")
    claims[:] = [
        claim
        for claim in claims
        if not isinstance(claim, dict) or claim.get("id") != "canonical_system_contract"
    ]
    claims.append(
        {
            "extractor_ids": [],
            "id": "canonical_system_contract",
            "profile_assertions": {
                "hybrid_v19": {
                    "required_extractors_contains": [
                        "extractor.turn_metadata",
                        "extractor.context_management",
                        "extractor.config_effects",
                    ]
                }
            },
            "required_resources": [
                "system_contract.py",
                "system_contract_validation.py",
                "system_contract_evidence.py",
                "schema_templates/system-contract.schema.json",
            ],
            "status": "active_package",
        }
    )
    write_text(path, json.dumps(value, indent=2, sort_keys=True))


def main() -> None:
    order_reference_validation()
    repair_generated_direct_test()
    repair_direct_contract_tests()
    restore_canonical_capability_claim()
    print(json.dumps({"status": "direct-contract-postprocess-complete"}, sort_keys=True))


if __name__ == "__main__":
    main()
