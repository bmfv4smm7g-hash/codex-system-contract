"""The single source-derived machine representation of the audited system.

The finalized extractor model is sealed once under ``system_contract``. This
module provides no aliases, projections, mirrors, or fallback read paths. A
consumer either understands this versioned contract or rejects it.
"""

from __future__ import annotations

import copy
import hashlib
from typing import Any, Mapping, MutableMapping

from .canonical import canonical_json_bytes

FORMAT = "codex-system-contract/v1"
SCHEMA_ID = "https://schemas.codex-wire-audit.invalid/system/v1/system-contract.schema.json"
CANONICALIZATION = "codex-wire-audit-canonical-json-v2"
_FORBIDDEN_PARALLEL_KEYS = frozenset(
    {"config_schema", "config_surface_graph", "local_storage_schema"}
)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def build_system_contract(model: Mapping[str, Any]) -> dict[str, Any]:
    """Seal one finalized source-derived model without a secondary shape."""
    body = {
        "$schema": SCHEMA_ID,
        "schema": FORMAT,
        "authority": "migrated_semantic_extractors",
        "model": copy.deepcopy(dict(model)),
    }
    return {
        **body,
        "integrity": {
            "algorithm": "sha256",
            "canonicalization": CANONICALIZATION,
            "canonical_sha256": digest(body),
        },
    }


def attach_system_contract(report: MutableMapping[str, Any]) -> None:
    """Consume the construction model and expose only the versioned contract."""
    if "system_contract" in report:
        raise ValueError("system_contract is already attached")
    if "evolution_contract" not in report:
        raise ValueError("missing finalized extractor model")
    leaked = sorted(_FORBIDDEN_PARALLEL_KEYS & set(report))
    if leaked:
        raise ValueError(f"parallel machine representations are forbidden: {leaked}")
    model = report.pop("evolution_contract")
    if not isinstance(model, Mapping):
        raise ValueError("finalized extractor model must be an object")
    report["system_contract"] = build_system_contract(model)
