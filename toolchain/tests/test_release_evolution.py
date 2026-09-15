from __future__ import annotations

import copy
import hashlib
import json

import pytest

from codex_wire_audit.release_evolution import (
    ReleaseEvolutionError,
    build_release_plan,
    validate_plan_against_release_spec,
    validate_release_plan,
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _report(
    commit: str,
    *,
    source_set: str,
    extractors: dict[str, dict] | None = None,
    schema_version: str = "2.0.0",
    profile: str = "hybrid_v19",
) -> dict:
    contract = {
        "schema_version": schema_version,
        "coverage_profile": profile,
        "source_revision": {
            "source_mode": "git",
            "repository": "openai/codex",
            "requested_ref": commit,
            "resolved_commit_sha": commit,
            "source_set_sha256": source_set,
            "source_revision_id": f"sha256:{source_set}",
            "dirty": False,
        },
        "source_registry": {"sources": {}},
        "extractors": extractors or {},
        "integrity": {"canonical_ir_sha256": _digest(extractors or {})},
    }
    return {"evolution_contract": contract}


def _extractor(data: dict, *, complete: bool = True) -> dict:
    return {
        "extractor_id": "extractor.example",
        "schema_version": "1.0.0",
        "semantic_complete": complete,
        "source_spec_ids": [],
        "data": data,
    }


OLD = "1" * 40
NEW = "2" * 40
OLD_SET = "a" * 64
NEW_SET = "b" * 64


def test_exact_codex_change_without_semantic_change_is_patch():
    plan = build_release_plan(
        _report(OLD, source_set=OLD_SET),
        _report(NEW, source_set=NEW_SET),
        previous_version="12.0.0",
    )
    assert plan["release"]["level"] == "patch"
    assert plan["release"]["recommended_version"] == "12.0.1"
    assert plan["evolution"]["from"]["commit"] == OLD
    assert plan["evolution"]["to"]["commit"] == NEW
    validate_release_plan(plan)


def test_same_codex_commit_cannot_create_generator_only_release():
    with pytest.raises(ReleaseEvolutionError, match="exact Codex evolution"):
        build_release_plan(
            _report(OLD, source_set=OLD_SET),
            _report(OLD, source_set=NEW_SET),
            previous_version="12.0.0",
        )


def test_new_extractor_is_minor():
    plan = build_release_plan(
        _report(OLD, source_set=OLD_SET),
        _report(
            NEW,
            source_set=NEW_SET,
            extractors={"extractor.example": _extractor({"value": 1})},
        ),
        previous_version="12.0.0",
    )
    assert plan["release"]["level"] == "minor"
    assert plan["release"]["recommended_version"] == "12.1.0"


def test_removed_extractor_is_major():
    plan = build_release_plan(
        _report(
            OLD,
            source_set=OLD_SET,
            extractors={"extractor.example": _extractor({"value": 1})},
        ),
        _report(NEW, source_set=NEW_SET),
        previous_version="12.3.4",
    )
    assert plan["release"]["level"] == "major"
    assert plan["release"]["recommended_version"] == "13.0.0"


def test_unknown_existing_extractor_semantic_change_is_major():
    plan = build_release_plan(
        _report(
            OLD,
            source_set=OLD_SET,
            extractors={"extractor.example": _extractor({"value": 1})},
        ),
        _report(
            NEW,
            source_set=NEW_SET,
            extractors={"extractor.example": _extractor({"value": 2})},
        ),
        previous_version="12.3.4",
    )
    assert plan["release"]["level"] == "major"
    assert "canonical_extractor_changed" in plan["release"]["reason_codes"]


def test_turn_metadata_uses_domain_semantic_classifier():
    before_tm = {
        "extractor_id": "extractor.turn_metadata",
        "schema_version": "2.0.0",
        "semantic_complete": True,
        "source_spec_ids": [],
        "data": {"gates": {}, "fields": {}},
    }
    after_tm = copy.deepcopy(before_tm)
    after_tm["data"]["fields"]["new_field"] = {
        "semantic_fingerprint": "x",
        "emission_fingerprint": "x",
        "gate_refs": [],
        "kind": "value_passthrough",
        "value_expression": "value",
        "identity_domain": "other",
    }
    plan = build_release_plan(
        _report(OLD, source_set=OLD_SET, extractors={"extractor.turn_metadata": before_tm}),
        _report(NEW, source_set=NEW_SET, extractors={"extractor.turn_metadata": after_tm}),
        previous_version="12.0.0",
    )
    assert plan["release"]["level"] == "minor"
    assert plan["evolution"]["semantic_diff"]["summary"]["attention"] == 1


def test_contract_schema_or_profile_change_is_major():
    assert build_release_plan(
        _report(OLD, source_set=OLD_SET, schema_version="1.0.0"),
        _report(NEW, source_set=NEW_SET, schema_version="2.0.0"),
        previous_version="4.5.6",
    )["release"]["level"] == "major"

    assert build_release_plan(
        _report(OLD, source_set=OLD_SET),
        _report(NEW, source_set=NEW_SET, profile="codex_wire_full"),
        previous_version="4.5.6",
    )["release"]["level"] == "major"


def test_plan_integrity_detects_mutation():
    plan = build_release_plan(
        _report(OLD, source_set=OLD_SET),
        _report(NEW, source_set=NEW_SET),
        previous_version="12.0.0",
    )
    plan["release"]["recommended_version"] = "99.0.0"
    with pytest.raises(ReleaseEvolutionError):
        validate_release_plan(plan)


def test_release_spec_must_match_exact_target_and_version():
    plan = build_release_plan(
        _report(OLD, source_set=OLD_SET),
        _report(NEW, source_set=NEW_SET),
        previous_version="12.0.0",
    )
    spec = {
        "release": {
            "reviewed_codex_commit": NEW,
            "package_version": "12.0.1",
            "generator_version": "12.0.1",
        }
    }
    validate_plan_against_release_spec(plan, spec)
    spec["release"]["reviewed_codex_commit"] = OLD
    with pytest.raises(ReleaseEvolutionError, match="reviewed_codex_commit"):
        validate_plan_against_release_spec(plan, spec)


def test_invalid_repository_and_dirty_source_fail_closed():
    before = _report(OLD, source_set=OLD_SET)
    after = _report(NEW, source_set=NEW_SET)
    before["evolution_contract"]["source_revision"]["repository"] = "fork/codex"
    with pytest.raises(ReleaseEvolutionError, match="openai/codex"):
        build_release_plan(before, after, previous_version="12.0.0")

    before = _report(OLD, source_set=OLD_SET)
    before["evolution_contract"]["source_revision"]["dirty"] = True
    with pytest.raises(ReleaseEvolutionError, match="dirty"):
        build_release_plan(before, after, previous_version="12.0.0")
