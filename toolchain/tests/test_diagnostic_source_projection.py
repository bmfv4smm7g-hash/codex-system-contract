from __future__ import annotations

from codex_wire_audit.diagnostics import DiagnosticCollector
from codex_wire_audit.orchestrator import _merge_structured_diagnostics


def test_structured_diagnostic_source_refs_project_to_legacy_manifest_ids() -> None:
    rollout_path = "codex-rs/rollout/src/rollout_file_name.rs"
    endpoint_path = "codex-rs/codex-api/src/endpoint/mod.rs"
    report = {
        "source_manifest": {
            "files": {
                "source.rollout": {"id": "source.rollout"},
                "source.endpoint": {"id": "source.endpoint"},
            },
            "path_index": {
                rollout_path: "source.rollout",
                endpoint_path: "source.endpoint",
            },
            "locations": {
                "location.endpoint.9": {
                    "source_ref": "source.endpoint",
                    "start_line": 9,
                    "end_line": 9,
                }
            },
            "exact_snapshot": {
                "files": {
                    "source_spec.extra.local_storage_rollout_filename": {
                        "path": rollout_path
                    }
                }
            },
        },
        "diagnostics": [],
    }
    diagnostics = DiagnosticCollector()
    canonical_refs = (
        f"source_spec.extra.local_storage_rollout_filename:{rollout_path}",
        endpoint_path,
        f"{endpoint_path}:9",
    )
    diagnostic = diagnostics.emit(
        code="SOURCE_PROJECTION_FIXTURE",
        severity="warning",
        category="test",
        message="fixture",
        source_refs=canonical_refs,
    )

    _merge_structured_diagnostics(report, diagnostics)

    [projected] = report["diagnostics"]
    assert projected["id"] == diagnostic.id
    assert projected["source_refs"] == [
        "source.rollout",
        "source.endpoint",
        "location.endpoint.9",
    ]
    assert projected["details"]["canonical_source_refs"] == list(canonical_refs)


def test_unmapped_structured_diagnostic_source_ref_remains_fail_visible() -> None:
    report = {
        "source_manifest": {"files": {}, "path_index": {}, "locations": {}},
        "diagnostics": [],
    }
    diagnostics = DiagnosticCollector()
    diagnostics.emit(
        code="SOURCE_PROJECTION_MISSING_FIXTURE",
        severity="warning",
        category="test",
        message="fixture",
        source_refs=("codex-rs/missing.rs",),
    )

    _merge_structured_diagnostics(report, diagnostics)

    assert report["diagnostics"][0]["source_refs"] == ["codex-rs/missing.rs"]
