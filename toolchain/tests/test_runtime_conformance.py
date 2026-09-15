from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from codex_wire_audit.proof_profiles import resolve_profile
from codex_wire_audit.runtime_conformance import (
    RuntimeEvidenceError,
    assemble_runtime_evidence,
    load_json_strict,
    normalize_scenario,
    validate_runtime_evidence,
)


REPORT_SHA = "a" * 40
HASH = "b" * 64
ARTIFACT_HASH = "c" * 64


def _report() -> dict[str, object]:
    return {
        "coverage_profile": "codex_wire_full",
        "source_revision": {
            "repository": "openai/codex",
            "resolved_commit_sha": REPORT_SHA,
        },
        "extractors": {},
    }


def _scope() -> dict[str, object]:
    return {
        "source_repository": "openai/codex",
        "source_commit": REPORT_SHA,
        "build_kind": "binary",
        "build_sha256": HASH,
        "platform": {"os": "linux", "arch": "x86_64"},
        "account_class": "none",
        "network_class": "local_fixture",
    }


def _observer() -> dict[str, str]:
    return {
        "harness": "codex-runtime-probe",
        "version": "1.0.0",
        "sha256": HASH,
        "run_id": "gha-123",
    }


def _scenario(scenario_id: str, *, status: str = "passed") -> dict[str, object]:
    assertion_status = status
    return {
        "id": scenario_id,
        "status": status,
        "observation_kind": "local_fixture",
        "assertions": [
            {
                "id": f"{scenario_id}.observed",
                "status": assertion_status,
                "evidence_code": "runtime-observation",
            }
        ],
        "artifacts": [
            {
                "role": "trace",
                "media_type": "application/json",
                "sha256": ARTIFACT_HASH,
            }
        ],
    }


def _all_scenarios() -> list[dict[str, object]]:
    profile = resolve_profile("codex_wire_full")
    return [_scenario(scenario_id) for scenario_id in reversed(profile.required_runtime_scenarios)]


def test_assembly_is_deterministic_and_profile_bound() -> None:
    report = _report()
    first = assemble_runtime_evidence(
        report,
        profile_id="codex_wire_full",
        scope=_scope(),
        observer=_observer(),
        observations=_all_scenarios(),
    )
    second = assemble_runtime_evidence(
        report,
        profile_id="codex_wire_full",
        scope=_scope(),
        observer=_observer(),
        observations=reversed(_all_scenarios()),
    )
    assert first == second
    assert first["status"] == "complete"
    assert [item["id"] for item in first["scenarios"]] == sorted(first["required_scenarios"])


def test_complete_evidence_is_report_and_source_bound() -> None:
    report = _report()
    evidence = assemble_runtime_evidence(
        report,
        profile_id="codex_wire_full",
        scope=_scope(),
        observer=_observer(),
        observations=_all_scenarios(),
    )
    profile = resolve_profile("codex_wire_full")
    result = validate_runtime_evidence(
        evidence,
        report,
        profile_id="codex_wire_full",
        required_scenarios=profile.required_runtime_scenarios,
    )
    assert result.complete
    assert result.report_bound
    assert result.source_bound
    assert not result.missing_scenarios
    assert not result.diagnostics


def test_source_revision_mismatch_fails_closed() -> None:
    report = _report()
    scope = _scope()
    scope["source_commit"] = "d" * 40
    evidence = assemble_runtime_evidence(
        report,
        profile_id="codex_wire_full",
        scope=scope,
        observer=_observer(),
        observations=_all_scenarios(),
    )
    profile = resolve_profile("codex_wire_full")
    result = validate_runtime_evidence(
        evidence,
        report,
        profile_id="codex_wire_full",
        required_scenarios=profile.required_runtime_scenarios,
    )
    assert not result.complete
    assert not result.source_bound
    assert {item.code for item in result.diagnostics} >= {"RUNTIME_EVIDENCE_SOURCE_MISMATCH"}


def test_report_digest_mismatch_fails_closed() -> None:
    report = _report()
    evidence = assemble_runtime_evidence(
        report,
        profile_id="codex_wire_full",
        scope=_scope(),
        observer=_observer(),
        observations=_all_scenarios(),
    )
    evidence["report_sha256"] = "0" * 64
    profile = resolve_profile("codex_wire_full")
    result = validate_runtime_evidence(
        evidence,
        report,
        profile_id="codex_wire_full",
        required_scenarios=profile.required_runtime_scenarios,
    )
    assert not result.complete
    assert not result.report_bound
    assert {item.code for item in result.diagnostics} >= {"RUNTIME_EVIDENCE_REPORT_MISMATCH"}


def test_missing_or_failed_required_scenario_is_partial() -> None:
    report = _report()
    scenarios = _all_scenarios()
    failed_id = scenarios[0]["id"]
    scenarios[0] = _scenario(str(failed_id), status="failed")
    evidence = assemble_runtime_evidence(
        report,
        profile_id="codex_wire_full",
        scope=_scope(),
        observer=_observer(),
        observations=scenarios,
    )
    assert evidence["status"] == "partial"
    profile = resolve_profile("codex_wire_full")
    result = validate_runtime_evidence(
        evidence,
        report,
        profile_id="codex_wire_full",
        required_scenarios=profile.required_runtime_scenarios,
    )
    assert not result.complete
    assert failed_id in result.missing_scenarios
    assert any(item.code == "RUNTIME_SCENARIO_MISSING" for item in result.diagnostics)


def test_passed_scenario_requires_all_assertions_to_pass() -> None:
    scenario = _scenario("responses_http_request")
    scenario["assertions"][0]["status"] = "failed"  # type: ignore[index]
    with pytest.raises(RuntimeEvidenceError, match="cannot pass"):
        normalize_scenario(scenario)


def test_scenario_requires_hashed_artifact() -> None:
    scenario = _scenario("responses_http_request")
    scenario["artifacts"] = []
    with pytest.raises(RuntimeEvidenceError, match="hashed artifacts"):
        normalize_scenario(scenario)


def test_duplicate_scenario_ids_are_rejected() -> None:
    report = _report()
    scenario = _scenario("responses_http_request")
    with pytest.raises(RuntimeEvidenceError, match="duplicate scenario"):
        assemble_runtime_evidence(
            report,
            profile_id="codex_wire_full",
            scope=_scope(),
            observer=_observer(),
            observations=[scenario, copy.deepcopy(scenario)],
        )


def test_unknown_scope_fields_are_rejected() -> None:
    report = _report()
    scope = _scope()
    scope["account_id"] = "must-not-be-recorded"
    with pytest.raises(RuntimeEvidenceError, match="unknown keys"):
        assemble_runtime_evidence(
            report,
            profile_id="codex_wire_full",
            scope=scope,
            observer=_observer(),
            observations=_all_scenarios(),
        )


def test_strict_loader_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"status":"complete","status":"partial"}', encoding="utf-8")
    with pytest.raises(RuntimeEvidenceError, match="duplicate JSON key"):
        load_json_strict(path)


def test_old_minimal_runtime_evidence_no_longer_satisfies_full_profile() -> None:
    report = _report()
    profile = resolve_profile("codex_wire_full")
    evidence = {
        "status": "complete",
        "report_sha256": "0" * 64,
        "scenarios": [{"id": scenario_id, "status": "passed"} for scenario_id in profile.required_runtime_scenarios],
    }
    result = validate_runtime_evidence(
        evidence,
        report,
        profile_id="codex_wire_full",
        required_scenarios=profile.required_runtime_scenarios,
    )
    codes = {item.code for item in result.diagnostics}
    assert not result.complete
    assert "RUNTIME_EVIDENCE_INVALID" in codes
    assert "RUNTIME_EVIDENCE_REPORT_MISMATCH" in codes
