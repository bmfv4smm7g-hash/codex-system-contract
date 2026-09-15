from __future__ import annotations
import importlib.util
import pytest
from codex_wire_audit.system_contract import attach_system_contract, build_system_contract, digest
from codex_wire_audit.system_contract_validation import validate_system_contract
from test_codex_wire_audit_v11 import contract_for_fixture
PARALLEL = {'config_schema', 'config_surface_graph', 'evolution_contract', 'local_storage_schema'}

def model() -> dict:
    return contract_for_fixture('responses_metadata_identity_split.rs')

def reseal(contract: dict) -> None:
    body = {key: value for key, value in contract.items() if key != 'integrity'}
    contract['integrity']['canonical_sha256'] = digest(body)

def test_contract_has_one_public_machine_shape() -> None:
    contract = build_system_contract(model())
    assert set(contract) == {'$schema', 'schema', 'authority', 'model', 'integrity'}
    validate_system_contract(contract)

def test_attach_consumes_the_private_construction_model() -> None:
    report = {'evolution_contract': model(), 'diagnostics': []}
    attach_system_contract(report)
    assert set(report) == {'system_contract', 'diagnostics'}
    assert not PARALLEL & set(report)
    assert validate_system_contract(report['system_contract'], report=report)['direct_report_checked']

@pytest.mark.parametrize('key', sorted(PARALLEL - {'evolution_contract'}))
def test_parallel_machine_paths_are_rejected(key: str) -> None:
    with pytest.raises(ValueError, match='parallel machine representations'):
        attach_system_contract({'evolution_contract': model(), key: {}})

def test_removed_adapter_module_is_not_importable() -> None:
    assert importlib.util.find_spec('codex_wire_audit.compatibility_views') is None

def test_complete_status_requires_all_required_sources() -> None:
    contract = build_system_contract(model())
    candidate = contract['model']
    candidate['status']['overall'] = 'complete'
    required = [key for key, spec in candidate['source_registry']['sources'].items() if spec['required']]
    assert required
    victim = required[0]
    candidate['source_snapshot']['files'].pop(victim, None)
    unavailable = candidate['source_snapshot']['unavailable_specs']
    if victim not in unavailable:
        unavailable[victim] = 'test fixture intentionally unavailable'
    candidate['source_snapshot']['counts'] = {'available': len(candidate['source_snapshot']['files']), 'unavailable': len(unavailable)}
    reseal(contract)
    with pytest.raises(ValueError, match='missing required sources'):
        validate_system_contract(contract)
