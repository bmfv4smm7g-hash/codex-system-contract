from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CHECKER = r'''"""Validate current Codex directly from the canonical extractor model.

This path intentionally bypasses the frozen v10 compatibility renderer. It is
used for upstream-current drift detection, while release proof continues to use
the reviewed pinned source and full compatibility report.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from codex_wire_audit.canonical import canonical_json_bytes
from codex_wire_audit.evolution import build_evolution_contract, finalize_evolution_contract
from codex_wire_audit.legacy import load_legacy_modules
from codex_wire_audit.metadata_history import load_history_catalog, validate_history_catalog
from codex_wire_audit.orchestrator import build_registry
from codex_wire_audit.proof_profiles import evaluate_profile, resolve_profile
from codex_wire_audit.sources import load_repo_snapshot
from codex_wire_audit.system_contract import build_system_contract
from codex_wire_audit.system_contract_validation import validate_system_contract

FORMAT = "codex-current-main-static-proof/v1"


def build_current_main_static_proof(
    repo_root: Path,
    *,
    profile_id: str = "current_main_static_full",
) -> tuple[dict[str, object], bool]:
    legacy = load_legacy_modules()
    registry = build_registry(legacy)
    loaded = load_repo_snapshot(
        registry,
        str(repo_root),
        repository="openai/codex",
        requested_ref="main",
        source_commit=None,
        allow_dirty=False,
        worktree=False,
    )
    diagnostics = loaded.diagnostics
    model, _ = build_evolution_contract(
        loaded.snapshot,
        registry,
        diagnostics,
        coverage_profile=profile_id,
    )
    finalize_evolution_contract(
        model,
        diagnostics,
        schema_resolution_complete=True,
    )
    system_contract = build_system_contract(model)
    source_proof = validate_system_contract(
        system_contract,
        source_root=repo_root,
    )

    profile = resolve_profile(profile_id)
    profile_evaluation, profile_diagnostics = evaluate_profile(
        {"system_contract": system_contract},
        profile_id,
    )
    catalog = load_history_catalog()
    history_errors = validate_history_catalog(catalog)
    missing_history_keys = sorted(
        set(profile.required_history_keys) - set(catalog.get("keys", {}))
    )
    extractor_diagnostics = diagnostics.to_list()
    profile_diagnostic_values = [item.to_dict() for item in profile_diagnostics]
    all_diagnostics = [
        *extractor_diagnostics,
        *profile_diagnostic_values,
        *(
            {
                "code": "METADATA_HISTORY_CATALOG_INVALID",
                "message": message,
                "severity": "error",
                "category": "metadata_history",
                "strict_failure": True,
                "recoverable": False,
            }
            for message in history_errors
        ),
        *(
            {
                "code": "REQUIRED_HISTORY_KEY_MISSING",
                "message": f"coverage profile {profile_id} requires {key}",
                "severity": "error",
                "category": "metadata_history",
                "source_id": key,
                "strict_failure": True,
                "recoverable": False,
            }
            for key in missing_history_keys
        ),
    ]
    semantic_complete = (model.get("status") or {}).get("overall") == "complete"
    complete = (
        semantic_complete
        and bool(profile_evaluation.get("complete"))
        and not all_diagnostics
        and not missing_history_keys
    )
    proof: dict[str, object] = {
        "format": FORMAT,
        "repository": "openai/codex",
        "requested_ref": "main",
        "resolved_commit": loaded.snapshot.revision.resolved_commit,
        "source_revision": loaded.snapshot.revision.to_dict(),
        "coverage_profile": profile_id,
        "profile_evaluation": profile_evaluation,
        "metadata_history": {
            "catalog_version": catalog.get("catalog_version"),
            "current_version_ref": catalog.get("current_version_ref"),
            "required_keys": list(profile.required_history_keys),
            "missing_keys": missing_history_keys,
        },
        "source_byte_proof": source_proof,
        "diagnostics": all_diagnostics,
        "status": {
            "complete": complete,
            "semantic_model_complete": semantic_complete,
            "profile_complete": bool(profile_evaluation.get("complete")),
            "source_bytes_verified": source_proof.get("source_bytes_status") == "verified",
        },
        "system_contract": system_contract,
    }
    validate_system_contract(system_contract, report=proof)
    return proof, complete


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--profile", default="current_main_static_full")
    parser.add_argument("--output", required=True)
    parser.add_argument("--system-contract-output")
    args = parser.parse_args()

    proof, complete = build_current_main_static_proof(
        Path(args.repo_root).resolve(),
        profile_id=args.profile,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json_bytes(proof))
    if args.system_contract_output:
        contract_output = Path(args.system_contract_output)
        contract_output.parent.mkdir(parents=True, exist_ok=True)
        contract_output.write_bytes(canonical_json_bytes(proof["system_contract"]))
    print(
        json.dumps(
            {
                "complete": complete,
                "resolved_commit": proof["resolved_commit"],
                "profile": args.profile,
                "diagnostic_count": len(proof["diagnostics"]),
            },
            sort_keys=True,
        )
    )
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
'''

checker = ROOT / "toolchain/tools/check_current_main_static.py"
checker.write_text(CHECKER, encoding="utf-8")

canary = ROOT / ".github/workflows/codex-current-main-canary.yml"
text = canary.read_text(encoding="utf-8")
old = '''          codex-wire-audit --json \\
            --repo-root codex-current-main \\
            --coverage-profile current_main_static_full \\
            --fail-on incomplete \\
            --emit-system-contract "$evidence/system-contract.json" \\
            --output "$evidence/report.json"
          python toolchain/tools/check_canonical_contract.py \\
            --report "$evidence/report.json" \\
            --source-root codex-current-main \\
            --output "$evidence/source-byte-proof.json"
'''
new = '''          python toolchain/tools/check_current_main_static.py \\
            --repo-root codex-current-main \\
            --profile current_main_static_full \\
            --system-contract-output "$evidence/system-contract.json" \\
            --output "$evidence/report.json"
'''
if text.count(old) != 1:
    raise RuntimeError("current-main canary invocation marker changed")
canary.write_text(text.replace(old, new, 1), encoding="utf-8")
