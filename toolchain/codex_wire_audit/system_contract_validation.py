"""Strict offline validation for the direct system contract."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .proof_schema_validation import load_schemas
from .system_contract import SCHEMA_ID, digest
from .system_contract_evidence import revalidate_source_bytes, relative_source_path, scan_secrets
from .validation import validate_evolution_contract

_FORBIDDEN_PARALLEL_KEYS = frozenset(
    {"config_schema", "config_surface_graph", "evolution_contract", "local_storage_schema"}
)


@lru_cache(maxsize=1)
def _schema_resources() -> tuple[dict[str, Any], Registry]:
    by_id, _ = load_schemas()
    registry = Registry().with_resources(
        (uri, Resource.from_contents(schema)) for uri, schema in by_id.items()
    )
    return by_id, registry


def _validator(identifier: str = SCHEMA_ID) -> Draft202012Validator:
    by_id, registry = _schema_resources()
    if identifier not in by_id:
        raise ValueError("fragment schema is not in the offline package bundle")
    return Draft202012Validator(by_id[identifier], registry=registry)


def _graph_references(graph: Mapping[str, Any]) -> None:
    nodes = graph["nodes"]
    if any(key != node["id"] for key, node in nodes.items()):
        raise ValueError("surface graph node key/id mismatch")
    edge_ids: set[str] = set()
    for edge in graph["edges"]:
        if edge["id"] in edge_ids:
            raise ValueError("duplicate surface graph edge id")
        edge_ids.add(edge["id"])
        if edge["source"] not in nodes or edge["target"] not in nodes:
            raise ValueError("unresolved surface graph edge")


def _references(model: Mapping[str, Any]) -> None:
    specs = model["source_registry"]["sources"]
    snapshot = model["source_snapshot"]
    files = snapshot["files"]
    unavailable = snapshot["unavailable_specs"]
    if snapshot["revision"] != model["source_revision"]:
        raise ValueError("source snapshot/revision disagreement")
    declared = set(specs)
    accounted = set(files) | set(unavailable)
    if set(files) & set(unavailable) or accounted - declared:
        raise ValueError("unresolved or contradictory source inventory")
    if snapshot["counts"] != {"available": len(files), "unavailable": len(unavailable)}:
        raise ValueError("source inventory count mismatch")
    for key, spec in specs.items():
        if key != spec["id"]:
            raise ValueError("source registry key/id mismatch")
    for key, record in files.items():
        path = record["path"]
        relative_source_path(path)
        if key != record["spec_id"]:
            raise ValueError("source manifest key/spec identity collision")
        candidates = specs[key]["path_candidates"]
        index = record["path_candidate_index"]
        if index >= len(candidates) or candidates[index] != path:
            raise ValueError("source path is not the selected registry candidate")

    extractors = model["extractors"]
    canonical_ids = model["migration"]["canonical_ir_extractors"]
    if sorted(extractors) != sorted(canonical_ids):
        raise ValueError("canonical extractor coverage mismatch")
    for key, entry in extractors.items():
        if key != entry["extractor_id"]:
            raise ValueError("extractor key/id mismatch")
        if set(entry["source_spec_ids"]) - declared:
            raise ValueError("extractor references undeclared source specs")
        data = entry["data"]
        if data.get("$schema"):
            errors = list(_validator(data["$schema"]).iter_errors(data))
            if not entry["semantic_complete"]:
                errors = [error for error in errors if error.validator != "required"]
            if errors:
                raise ValueError("extractor fragment schema violation: " + key)
        if "semantic_complete" in data and data["semantic_complete"] != entry["semantic_complete"]:
            raise ValueError("extractor completeness disagreement")
        if "source_revision" in data and data["source_revision"] != model["source_revision"]:
            raise ValueError("extractor source revision disagreement")
        if key == "extractor.local_storage":
            for evidence in data.get("evidence", {}).get("sources", []):
                source = files.get(evidence["source_spec_id"])
                fields = ("path", "sha256", "git_blob_sha")
                if not source or any(evidence[name] != source[name] for name in fields):
                    raise ValueError("local-storage evidence/manifest disagreement")
        graph = data.get("surface_graph")
        if graph is not None:
            _graph_references(graph)

    if model["status"]["overall"] == "complete":
        required = {key for key, spec in specs.items() if spec["required"]}
        missing = sorted(required - set(files))
        unavailable_required = sorted(required & set(unavailable))
        if not required:
            raise ValueError("complete status requires a declared required-source inventory")
        if missing or unavailable_required:
            raise ValueError(
                "complete status has missing required sources: "
                f"missing={missing}, unavailable={unavailable_required}"
            )
        if not extractors or not all(entry["semantic_complete"] for entry in extractors.values()):
            raise ValueError("complete status contradicts extractor coverage")


def validate_system_contract(
    value: Mapping[str, Any],
    *,
    report: Mapping[str, Any] | None = None,
    source_root: Path | None = None,
) -> dict[str, Any]:
    """Raise ``ValueError`` when a direct-contract invariant is false."""
    scan_secrets(value)
    errors = list(_validator().iter_errors(value))
    if errors:
        path = "/".join(map(str, errors[0].absolute_path))
        raise ValueError("canonical schema violation at " + path)
    model = value["model"]
    _references(model)
    failures = validate_evolution_contract(model)
    if failures:
        raise ValueError(failures[0]["code"])
    body = {key: child for key, child in value.items() if key != "integrity"}
    if value["integrity"]["canonical_sha256"] != digest(body):
        raise ValueError("canonical content digest mismatch")
    if report is not None:
        leaked = sorted(_FORBIDDEN_PARALLEL_KEYS & set(report))
        if leaked:
            raise ValueError(f"parallel machine representations are forbidden: {leaked}")
        if report.get("system_contract") != value:
            raise ValueError("report does not contain the validated system contract")
    checked = revalidate_source_bytes(model, source_root) if source_root is not None else None
    return {
        "schema": value["schema"],
        "authority": value["authority"],
        "canonical_sha256": value["integrity"]["canonical_sha256"],
        "extractors": sorted(model["extractors"]),
        "direct_report_checked": report is not None,
        "source_files_revalidated": checked,
        "source_bytes_status": "verified" if checked is not None else "not_checked",
    }
