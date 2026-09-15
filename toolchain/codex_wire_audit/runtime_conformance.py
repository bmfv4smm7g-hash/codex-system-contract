"""Strict runtime-conformance evidence for bounded observed Codex behavior.

Runtime evidence is deliberately separate from source-derived contract facts. This
module validates and assembles observation envelopes that are bound to one exact
static report, source revision, build identity, platform class, account class,
and network class. It never executes Codex or upgrades an observation into a
universal source claim.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Iterable, Mapping

from .proof_profiles import resolve_profile
from .proof_schema_validation import report_sha256

FORMAT = "codex-runtime-conformance/v1"
SCHEMA_ID = "https://schemas.codex-system-contract.invalid/runtime/runtime-conformance-evidence-v1.schema.json"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40_OR_64 = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/+:-]{0,127}$")
ACCOUNT_CLASSES = {"none", "consumer", "workspace", "api", "unknown"}
NETWORK_CLASSES = {"offline", "local_fixture", "external", "unknown"}
BUILD_KINDS = {"source", "binary", "package"}
OBSERVATION_KINDS = {"local_fixture", "integration", "live"}
SCENARIO_STATUSES = {"passed", "failed", "blocked"}
ASSERTION_STATUSES = {"passed", "failed", "blocked"}


@dataclass(frozen=True, slots=True)
class RuntimeDiagnostic:
    code: str
    message: str
    source_id: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeEvidenceValidation:
    complete: bool
    report_bound: bool
    source_bound: bool
    required_scenarios: tuple[str, ...]
    passed_scenarios: tuple[str, ...]
    missing_scenarios: tuple[str, ...]
    diagnostics: tuple[RuntimeDiagnostic, ...]
    evidence_sha256: str

    def proof_summary(self) -> dict[str, Any]:
        return {
            "status": "complete" if self.complete else "incomplete",
            "complete": self.complete,
            "report_bound": self.report_bound,
            "source_bound": self.source_bound,
            "required_scenarios": list(self.required_scenarios),
            "passed_scenarios": list(self.passed_scenarios),
            "missing_scenarios": list(self.missing_scenarios),
            "evidence_sha256": self.evidence_sha256,
        }


class RuntimeEvidenceError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise RuntimeEvidenceError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load_json_strict(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicates)
    except OSError as error:
        raise RuntimeEvidenceError(f"cannot read JSON {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise RuntimeEvidenceError(f"invalid JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise RuntimeEvidenceError(f"JSON root must be an object: {path}")
    return value


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    with tempfile.NamedTemporaryFile(mode="w", encoding="ascii", dir=path.parent, delete=False) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _closed_keys(value: Mapping[str, Any], *, required: set[str], optional: set[str], where: str) -> None:
    missing = sorted(required - set(value))
    extra = sorted(set(value) - required - optional)
    if missing:
        raise RuntimeEvidenceError(f"{where} missing keys: {', '.join(missing)}")
    if extra:
        raise RuntimeEvidenceError(f"{where} has unknown keys: {', '.join(extra)}")


def _string(value: Any, *, where: str, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeEvidenceError(f"{where} must be a nonempty string")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise RuntimeEvidenceError(f"{where} has invalid syntax")
    return value


def _string_list(value: Any, *, where: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise RuntimeEvidenceError(f"{where} must be a nonempty array")
    result = [_string(item, where=f"{where}[]", pattern=SAFE_TOKEN) for item in value]
    if len(set(result)) != len(result):
        raise RuntimeEvidenceError(f"{where} contains duplicates")
    return result


def _report_source(report: Mapping[str, Any]) -> tuple[str | None, str | None]:
    revision = report.get("source_revision")
    if not isinstance(revision, Mapping):
        return None, None
    repository = revision.get("repository")
    commit = revision.get("resolved_commit_sha")
    return (
        repository if isinstance(repository, str) else None,
        commit if isinstance(commit, str) else None,
    )


def _validate_scope(scope: Any) -> dict[str, Any]:
    if not isinstance(scope, Mapping):
        raise RuntimeEvidenceError("scope must be an object")
    _closed_keys(
        scope,
        required={"source_repository", "source_commit", "build_kind", "build_sha256", "platform", "account_class", "network_class"},
        optional=set(),
        where="scope",
    )
    repository = _string(scope["source_repository"], where="scope.source_repository", pattern=SAFE_TOKEN)
    commit = _string(scope["source_commit"], where="scope.source_commit", pattern=HEX40_OR_64)
    build_kind = _string(scope["build_kind"], where="scope.build_kind")
    if build_kind not in BUILD_KINDS:
        raise RuntimeEvidenceError("scope.build_kind is unsupported")
    build_sha = _string(scope["build_sha256"], where="scope.build_sha256", pattern=HEX64)
    platform = scope["platform"]
    if not isinstance(platform, Mapping):
        raise RuntimeEvidenceError("scope.platform must be an object")
    _closed_keys(platform, required={"os", "arch"}, optional=set(), where="scope.platform")
    os_name = _string(platform["os"], where="scope.platform.os", pattern=SAFE_TOKEN)
    arch = _string(platform["arch"], where="scope.platform.arch", pattern=SAFE_TOKEN)
    account = _string(scope["account_class"], where="scope.account_class")
    network = _string(scope["network_class"], where="scope.network_class")
    if account not in ACCOUNT_CLASSES:
        raise RuntimeEvidenceError("scope.account_class is unsupported")
    if network not in NETWORK_CLASSES:
        raise RuntimeEvidenceError("scope.network_class is unsupported")
    return {
        "source_repository": repository,
        "source_commit": commit,
        "build_kind": build_kind,
        "build_sha256": build_sha,
        "platform": {"os": os_name, "arch": arch},
        "account_class": account,
        "network_class": network,
    }


def _validate_observer(observer: Any) -> dict[str, Any]:
    if not isinstance(observer, Mapping):
        raise RuntimeEvidenceError("observer must be an object")
    _closed_keys(observer, required={"harness", "version", "sha256", "run_id"}, optional=set(), where="observer")
    return {
        "harness": _string(observer["harness"], where="observer.harness", pattern=SAFE_TOKEN),
        "version": _string(observer["version"], where="observer.version", pattern=SAFE_TOKEN),
        "sha256": _string(observer["sha256"], where="observer.sha256", pattern=HEX64),
        "run_id": _string(observer["run_id"], where="observer.run_id", pattern=SAFE_TOKEN),
    }


def _validate_assertion(value: Any, *, scenario_id: str, index: int) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise RuntimeEvidenceError(f"scenario {scenario_id} assertion {index} must be an object")
    _closed_keys(value, required={"id", "status", "evidence_code"}, optional=set(), where=f"scenario {scenario_id} assertion {index}")
    assertion_id = _string(value["id"], where="assertion.id", pattern=SAFE_TOKEN)
    status = _string(value["status"], where="assertion.status")
    if status not in ASSERTION_STATUSES:
        raise RuntimeEvidenceError(f"scenario {scenario_id} assertion has unsupported status")
    return {
        "id": assertion_id,
        "status": status,
        "evidence_code": _string(value["evidence_code"], where="assertion.evidence_code", pattern=SAFE_TOKEN),
    }


def _validate_artifact(value: Any, *, scenario_id: str, index: int) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise RuntimeEvidenceError(f"scenario {scenario_id} artifact {index} must be an object")
    _closed_keys(value, required={"role", "media_type", "sha256"}, optional=set(), where=f"scenario {scenario_id} artifact {index}")
    media_type = _string(value["media_type"], where="artifact.media_type")
    if "/" not in media_type or len(media_type) > 128:
        raise RuntimeEvidenceError(f"scenario {scenario_id} artifact media_type is invalid")
    return {
        "role": _string(value["role"], where="artifact.role", pattern=SAFE_TOKEN),
        "media_type": media_type,
        "sha256": _string(value["sha256"], where="artifact.sha256", pattern=HEX64),
    }


def normalize_scenario(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeEvidenceError("scenario observation must be an object")
    _closed_keys(value, required={"id", "status", "observation_kind", "assertions", "artifacts"}, optional=set(), where="scenario")
    scenario_id = _string(value["id"], where="scenario.id", pattern=SAFE_TOKEN)
    status = _string(value["status"], where=f"scenario {scenario_id}.status")
    kind = _string(value["observation_kind"], where=f"scenario {scenario_id}.observation_kind")
    if status not in SCENARIO_STATUSES:
        raise RuntimeEvidenceError(f"scenario {scenario_id} has unsupported status")
    if kind not in OBSERVATION_KINDS:
        raise RuntimeEvidenceError(f"scenario {scenario_id} has unsupported observation_kind")
    raw_assertions = value["assertions"]
    raw_artifacts = value["artifacts"]
    if not isinstance(raw_assertions, list) or not raw_assertions:
        raise RuntimeEvidenceError(f"scenario {scenario_id} must contain assertions")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise RuntimeEvidenceError(f"scenario {scenario_id} must contain hashed artifacts")
    assertions = [_validate_assertion(item, scenario_id=scenario_id, index=index) for index, item in enumerate(raw_assertions)]
    artifacts = [_validate_artifact(item, scenario_id=scenario_id, index=index) for index, item in enumerate(raw_artifacts)]
    assertion_ids = [item["id"] for item in assertions]
    artifact_keys = [(item["role"], item["sha256"]) for item in artifacts]
    if len(set(assertion_ids)) != len(assertion_ids):
        raise RuntimeEvidenceError(f"scenario {scenario_id} contains duplicate assertion ids")
    if len(set(artifact_keys)) != len(artifact_keys):
        raise RuntimeEvidenceError(f"scenario {scenario_id} contains duplicate artifacts")
    assertion_statuses = {item["status"] for item in assertions}
    if status == "passed" and assertion_statuses != {"passed"}:
        raise RuntimeEvidenceError(f"scenario {scenario_id} cannot pass with non-passing assertions")
    if status == "failed" and "failed" not in assertion_statuses:
        raise RuntimeEvidenceError(f"scenario {scenario_id} failed without a failed assertion")
    if status == "blocked" and "blocked" not in assertion_statuses:
        raise RuntimeEvidenceError(f"scenario {scenario_id} blocked without a blocked assertion")
    return {
        "id": scenario_id,
        "status": status,
        "observation_kind": kind,
        "assertions": sorted(assertions, key=lambda item: item["id"]),
        "artifacts": sorted(artifacts, key=lambda item: (item["role"], item["sha256"])),
    }


def assemble_runtime_evidence(
    report: Mapping[str, Any],
    *,
    profile_id: str,
    scope: Mapping[str, Any],
    observer: Mapping[str, Any],
    observations: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    profile = resolve_profile(profile_id)
    required = tuple(sorted(set(profile.required_runtime_scenarios)))
    normalized_scope = _validate_scope(scope)
    normalized_observer = _validate_observer(observer)
    scenarios = [normalize_scenario(value) for value in observations]
    ids = [item["id"] for item in scenarios]
    if len(set(ids)) != len(ids):
        raise RuntimeEvidenceError("runtime evidence contains duplicate scenario ids")
    scenarios.sort(key=lambda item: item["id"])
    passed = {item["id"] for item in scenarios if item["status"] == "passed"}
    status = (
        "complete"
        if not (set(required) - passed) and all(item["status"] == "passed" for item in scenarios)
        else "partial"
    )
    return {
        "$schema": SCHEMA_ID,
        "format": FORMAT,
        "profile_id": profile_id,
        "report_sha256": report_sha256(dict(report)),
        "required_scenarios": list(required),
        "scope": normalized_scope,
        "observer": normalized_observer,
        "scenarios": scenarios,
        "status": status,
    }


def validate_runtime_evidence(
    evidence: Mapping[str, Any],
    report: Mapping[str, Any],
    *,
    profile_id: str,
    required_scenarios: Iterable[str],
) -> RuntimeEvidenceValidation:
    diagnostics: list[RuntimeDiagnostic] = []
    required = tuple(sorted(set(required_scenarios)))
    evidence_sha = hashlib.sha256(_canonical(evidence)).hexdigest()
    report_digest = report_sha256(dict(report))
    report_bound = evidence.get("report_sha256") == report_digest
    if not report_bound:
        diagnostics.append(RuntimeDiagnostic("RUNTIME_EVIDENCE_REPORT_MISMATCH", "runtime evidence is not bound to this report digest"))

    source_bound = False
    passed: set[str] = set()
    try:
        _closed_keys(
            evidence,
            required={"$schema", "format", "profile_id", "report_sha256", "required_scenarios", "scope", "observer", "scenarios", "status"},
            optional=set(),
            where="runtime evidence",
        )
        if evidence["$schema"] != SCHEMA_ID or evidence["format"] != FORMAT:
            raise RuntimeEvidenceError("runtime evidence schema/format version is unsupported")
        if evidence["profile_id"] != profile_id:
            raise RuntimeEvidenceError("runtime evidence profile_id does not match selected proof profile")
        declared_required = tuple(sorted(_string_list(evidence["required_scenarios"], where="required_scenarios")))
        if declared_required != required:
            raise RuntimeEvidenceError("runtime evidence required_scenarios do not match selected proof profile")
        scope = _validate_scope(evidence["scope"])
        _validate_observer(evidence["observer"])
        report_repository, report_commit = _report_source(report)
        source_bound = (
            report_repository is not None
            and report_commit is not None
            and scope["source_repository"] == report_repository
            and scope["source_commit"] == report_commit
        )
        if not source_bound:
            diagnostics.append(RuntimeDiagnostic("RUNTIME_EVIDENCE_SOURCE_MISMATCH", "runtime observation scope does not match the report source revision"))
        raw_scenarios = evidence["scenarios"]
        if not isinstance(raw_scenarios, list):
            raise RuntimeEvidenceError("runtime evidence scenarios must be an array")
        scenarios = [normalize_scenario(item) for item in raw_scenarios]
        ids = [item["id"] for item in scenarios]
        if len(set(ids)) != len(ids):
            raise RuntimeEvidenceError("runtime evidence contains duplicate scenario ids")
        passed = {item["id"] for item in scenarios if item["status"] == "passed"}
        if evidence["status"] not in {"complete", "partial"}:
            raise RuntimeEvidenceError("runtime evidence status is invalid")
        calculated_status = (
            "complete"
            if not (set(required) - passed) and all(item["status"] == "passed" for item in scenarios)
            else "partial"
        )
        if evidence["status"] != calculated_status:
            raise RuntimeEvidenceError("runtime evidence status disagrees with scenario outcomes")
    except RuntimeEvidenceError as error:
        diagnostics.append(RuntimeDiagnostic("RUNTIME_EVIDENCE_INVALID", str(error)))

    missing = tuple(sorted(set(required) - passed))
    for scenario_id in missing:
        diagnostics.append(RuntimeDiagnostic("RUNTIME_SCENARIO_MISSING", f"required runtime scenario did not pass: {scenario_id}", scenario_id))
    complete = report_bound and source_bound and not diagnostics and not missing and evidence.get("status") == "complete"
    return RuntimeEvidenceValidation(
        complete=complete,
        report_bound=report_bound,
        source_bound=source_bound,
        required_scenarios=required,
        passed_scenarios=tuple(sorted(passed)),
        missing_scenarios=missing,
        diagnostics=tuple(diagnostics),
        evidence_sha256=evidence_sha,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Assemble or verify bounded Codex runtime-conformance evidence.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    assemble = subparsers.add_parser("assemble")
    assemble.add_argument("--report", type=Path, required=True)
    assemble.add_argument("--profile", required=True)
    assemble.add_argument("--scope", type=Path, required=True)
    assemble.add_argument("--observer", type=Path, required=True)
    assemble.add_argument("--observation", type=Path, action="append", required=True)
    assemble.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--report", type=Path, required=True)
    verify.add_argument("--profile", required=True)
    verify.add_argument("--evidence", type=Path, required=True)
    verify.add_argument("--output", type=Path)
    return parser


def _main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = load_json_strict(args.report)
    if args.command == "assemble":
        scope = load_json_strict(args.scope)
        observer = load_json_strict(args.observer)
        observations = [load_json_strict(path) for path in args.observation]
        evidence = assemble_runtime_evidence(report, profile_id=args.profile, scope=scope, observer=observer, observations=observations)
        _atomic_json(args.output, evidence)
        profile = resolve_profile(args.profile)
        validation = validate_runtime_evidence(evidence, report, profile_id=args.profile, required_scenarios=profile.required_runtime_scenarios)
        return 0 if validation.complete else 3
    evidence = load_json_strict(args.evidence)
    profile = resolve_profile(args.profile)
    validation = validate_runtime_evidence(evidence, report, profile_id=args.profile, required_scenarios=profile.required_runtime_scenarios)
    if args.output is not None:
        _atomic_json(args.output, validation.proof_summary())
    return 0 if validation.complete else 3


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except (OSError, RuntimeEvidenceError, ValueError, json.JSONDecodeError) as error:
        print(f"codex-wire-audit-runtime: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
