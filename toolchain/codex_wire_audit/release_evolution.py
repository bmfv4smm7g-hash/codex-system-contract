"""Deterministic release planning from exact Codex commit-to-commit evolution."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Mapping

from .semantic_diff import compare as semantic_compare

PLAN_FORMAT = "codex-system-release-plan/v1"
POLICY_ID = "exact-codex-semver/v1"
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_SEMVER = re.compile(
    r"(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)\Z"
)


class ReleaseEvolutionError(ValueError):
    """The supplied evidence cannot authorize a release."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _contract(report: Mapping[str, Any]) -> Mapping[str, Any]:
    value = report.get("evolution_contract")
    if isinstance(value, Mapping):
        return value
    if "extractors" in report and "source_revision" in report:
        return report
    raise ReleaseEvolutionError("report does not contain an evolution_contract")


def _revision(contract: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    value = contract.get("source_revision")
    if not isinstance(value, Mapping):
        raise ReleaseEvolutionError(f"{label} contract has no source_revision")
    repository = value.get("repository")
    commit = value.get("resolved_commit_sha")
    source_set = value.get("source_set_sha256")
    revision_id = value.get("source_revision_id")
    dirty = value.get("dirty")
    if repository != "openai/codex":
        raise ReleaseEvolutionError(f"{label} repository must be openai/codex")
    if not isinstance(commit, str) or _SHA.fullmatch(commit) is None:
        raise ReleaseEvolutionError(f"{label} resolved_commit_sha must be a full lowercase commit SHA")
    if not isinstance(source_set, str) or re.fullmatch(r"[0-9a-f]{64}", source_set) is None:
        raise ReleaseEvolutionError(f"{label} source_set_sha256 is invalid")
    expected_revision_id = f"sha256:{source_set}"
    if revision_id != expected_revision_id:
        raise ReleaseEvolutionError(f"{label} source_revision_id does not match source_set_sha256")
    if dirty not in {False, None}:
        raise ReleaseEvolutionError(f"{label} source evidence is dirty")
    return {
        "repository": repository,
        "commit": commit,
        "source_set_sha256": source_set,
        "source_revision_id": revision_id,
        "source_mode": value.get("source_mode"),
    }


def _extractors(contract: Mapping[str, Any]) -> Mapping[str, Any]:
    value = contract.get("extractors")
    return value if isinstance(value, Mapping) else {}


def _extractor_digest(value: Mapping[str, Any]) -> str:
    payload = {
        "schema_version": value.get("schema_version"),
        "semantic_complete": value.get("semantic_complete"),
        "data": value.get("data"),
    }
    return _sha256(payload)


def _extractor_evolution(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    classified_extractors: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    old = _extractors(before)
    new = _extractors(after)
    changes: list[dict[str, Any]] = []
    for extractor_id in sorted(set(old) | set(new)):
        left = old.get(extractor_id)
        right = new.get(extractor_id)
        if left is None:
            changes.append(
                {
                    "kind": "extractor_added",
                    "extractor_id": extractor_id,
                    "severity": "minor",
                }
            )
            continue
        if right is None:
            changes.append(
                {
                    "kind": "extractor_removed",
                    "extractor_id": extractor_id,
                    "severity": "major",
                }
            )
            continue
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            raise ReleaseEvolutionError(f"extractor record is malformed: {extractor_id}")
        old_complete = bool(left.get("semantic_complete"))
        new_complete = bool(right.get("semantic_complete"))
        if old_complete and not new_complete:
            changes.append(
                {
                    "kind": "extractor_completeness_regressed",
                    "extractor_id": extractor_id,
                    "severity": "major",
                }
            )
        elif not old_complete and new_complete:
            changes.append(
                {
                    "kind": "extractor_completeness_completed",
                    "extractor_id": extractor_id,
                    "severity": "minor",
                }
            )
        old_digest = _extractor_digest(left)
        new_digest = _extractor_digest(right)
        if old_digest != new_digest and extractor_id not in classified_extractors:
            changes.append(
                {
                    "kind": "extractor_semantics_changed",
                    "extractor_id": extractor_id,
                    "severity": "major",
                    "before_sha256": old_digest,
                    "after_sha256": new_digest,
                }
            )
    return changes


def _parse_version(value: str) -> tuple[int, int, int]:
    match = _SEMVER.fullmatch(value)
    if match is None:
        raise ReleaseEvolutionError("previous_version must be a stable X.Y.Z SemVer")
    return tuple(int(match.group(name)) for name in ("major", "minor", "patch"))


def _bump(previous_version: str, level: str) -> str:
    major, minor, patch = _parse_version(previous_version)
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    if level == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ReleaseEvolutionError(f"unsupported release level: {level}")


def _contract_identity(contract: Mapping[str, Any]) -> dict[str, Any]:
    integrity = contract.get("integrity")
    canonical = integrity.get("canonical_ir_sha256") if isinstance(integrity, Mapping) else None
    if canonical is not None and (
        not isinstance(canonical, str) or re.fullmatch(r"[0-9a-f]{64}", canonical) is None
    ):
        raise ReleaseEvolutionError("canonical_ir_sha256 is invalid")
    return {
        "schema_version": contract.get("schema_version"),
        "coverage_profile": contract.get("coverage_profile"),
        "canonical_ir_sha256": canonical,
    }


def build_release_plan(
    before_report: Mapping[str, Any],
    after_report: Mapping[str, Any],
    *,
    previous_version: str,
) -> dict[str, Any]:
    """Build a fail-closed release plan from two exact Codex reports.

    The plan refuses generator-only releases: the exact Codex commit must move.
    Existing extractor changes without a domain-specific compatibility classifier
    are conservatively major.
    """
    _parse_version(previous_version)
    before = _contract(before_report)
    after = _contract(after_report)
    old_revision = _revision(before, label="before")
    new_revision = _revision(after, label="after")
    if old_revision["commit"] == new_revision["commit"]:
        raise ReleaseEvolutionError(
            "release requires exact Codex evolution; before and after commits are identical"
        )

    semantic_diff = semantic_compare(before_report, after_report)
    summary = semantic_diff.get("summary")
    if not isinstance(summary, Mapping):
        raise ReleaseEvolutionError("semantic diff has no summary")
    extractor_changes = _extractor_evolution(
        before,
        after,
        classified_extractors=frozenset({"extractor.turn_metadata"}),
    )

    reasons: list[str] = []
    level = "patch"
    if int(summary.get("breaking", 0)) > 0:
        level = "major"
        reasons.append("semantic_diff_breaking")
    elif int(summary.get("attention", 0)) > 0:
        level = "minor"
        reasons.append("semantic_diff_attention")
    elif int(summary.get("info", 0)) > 0:
        reasons.append("semantic_diff_info")
    else:
        reasons.append("exact_codex_source_changed")

    old_identity = _contract_identity(before)
    new_identity = _contract_identity(after)
    if old_identity["schema_version"] != new_identity["schema_version"]:
        level = "major"
        reasons.append("contract_schema_changed")
    if old_identity["coverage_profile"] != new_identity["coverage_profile"]:
        level = "major"
        reasons.append("coverage_profile_changed")

    if any(item["severity"] == "major" for item in extractor_changes):
        level = "major"
        reasons.append("canonical_extractor_changed")
    elif level != "major" and any(item["severity"] == "minor" for item in extractor_changes):
        level = "minor"
        reasons.append("canonical_extractor_added_or_completed")

    recommended_version = _bump(previous_version, level)
    plan: dict[str, Any] = {
        "format": PLAN_FORMAT,
        "policy": POLICY_ID,
        "status": "releasable",
        "repository": "openai/codex",
        "evolution": {
            "from": {**old_revision, **old_identity},
            "to": {**new_revision, **new_identity},
            "semantic_diff": copy.deepcopy(semantic_diff),
            "extractor_changes": extractor_changes,
        },
        "release": {
            "previous_version": previous_version,
            "level": level,
            "recommended_version": recommended_version,
            "reason_codes": sorted(set(reasons)),
        },
    }
    payload = copy.deepcopy(plan)
    plan["integrity"] = {
        "algorithm": "sha256",
        "canonicalization": "json-sort-keys-utf8-v1",
        "canonical_sha256": _sha256(payload),
    }
    return plan


def validate_release_plan(plan: Mapping[str, Any]) -> None:
    if plan.get("format") != PLAN_FORMAT or plan.get("policy") != POLICY_ID:
        raise ReleaseEvolutionError("unsupported release plan format or policy")
    if plan.get("status") != "releasable" or plan.get("repository") != "openai/codex":
        raise ReleaseEvolutionError("release plan is not releasable for openai/codex")
    evolution = plan.get("evolution")
    release = plan.get("release")
    integrity = plan.get("integrity")
    if not isinstance(evolution, Mapping) or not isinstance(release, Mapping):
        raise ReleaseEvolutionError("release plan is missing evolution/release sections")
    if not isinstance(integrity, Mapping):
        raise ReleaseEvolutionError("release plan has no integrity record")
    for key in ("from", "to"):
        revision = evolution.get(key)
        if not isinstance(revision, Mapping) or not isinstance(revision.get("commit"), str):
            raise ReleaseEvolutionError(f"release plan evolution.{key} is invalid")
        if _SHA.fullmatch(str(revision["commit"])) is None:
            raise ReleaseEvolutionError(f"release plan evolution.{key}.commit is invalid")
    previous = release.get("previous_version")
    level = release.get("level")
    recommended = release.get("recommended_version")
    if not isinstance(previous, str) or not isinstance(level, str) or not isinstance(recommended, str):
        raise ReleaseEvolutionError("release version fields are invalid")
    if _bump(previous, level) != recommended:
        raise ReleaseEvolutionError("recommended_version does not match the declared bump")
    payload = {key: copy.deepcopy(value) for key, value in plan.items() if key != "integrity"}
    if integrity.get("algorithm") != "sha256" or integrity.get("canonical_sha256") != _sha256(payload):
        raise ReleaseEvolutionError("release plan integrity mismatch")


def validate_plan_against_release_spec(
    plan: Mapping[str, Any], spec: Mapping[str, Any]
) -> None:
    """Bind an evolution plan to the package release spec before publication."""
    validate_release_plan(plan)
    release = spec.get("release")
    if not isinstance(release, Mapping):
        raise ReleaseEvolutionError("release spec has no release section")
    evolution = plan["evolution"]
    target = evolution["to"]
    plan_release = plan["release"]
    if release.get("reviewed_codex_commit") != target.get("commit"):
        raise ReleaseEvolutionError(
            "release spec reviewed_codex_commit does not match the evolution target"
        )
    if release.get("package_version") != plan_release.get("recommended_version"):
        raise ReleaseEvolutionError(
            "release spec package_version does not match the evolution-derived version"
        )
    if release.get("generator_version") != release.get("package_version"):
        raise ReleaseEvolutionError("release spec generator/package versions are not aligned")
