from __future__ import annotations

from codex_wire_audit.orchestrator import _attach_integrity


def test_sealed_report_integrity_uses_explicit_canonical_model() -> None:
    source_set_sha256 = "a" * 64
    canonical_ir_sha256 = "b" * 64
    canonical_model = {
        "source_revision": {"source_set_sha256": source_set_sha256},
        "integrity": {"canonical_ir_sha256": canonical_ir_sha256},
    }
    report = {"system_contract": {"schema": "codex-system-contract/v1"}}

    _attach_integrity(report, canonical_model)

    assert "evolution_contract" not in report
    assert report["integrity"]["source_set_sha256"] == source_set_sha256
    assert report["integrity"]["canonical_ir_sha256"] == canonical_ir_sha256
    assert len(report["integrity"]["payload_sha256"]) == 64
