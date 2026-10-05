"""Stage 4 safety semantics and old-protocol isolation."""

import copy
from pathlib import Path

import pytest
from eth_hash.auto import keccak

from seedbridge.config import ROOT, get_scenario
from seedbridge.harness import generate_harness
from seedbridge.safety import accounting_state
from seedbridge.study import load_study_spec
from seedbridge.study_audit import StudyAuditError, _validate_steps
from seedbridge.trace import validate_prefix


def test_frozen_safety_matrix_is_paired_and_does_not_seed_known_counterexample():
    spec = load_study_spec(ROOT / "configs/stage4-safety-v2.json")
    assert spec.plan()["distinct_slot_count"] == 60
    assert spec.plan()["common_block_count"] == 20
    assert set(spec.fixtures) == {"accounting_flawed", "accounting_repaired"}
    assert all(slot.total_budget_seconds == 32 for slot in spec.slots())
    assert 100 not in spec.boundary_values
    assert spec.native_evidence_reserve_seconds == 9
    for fixture in spec.fixtures:
        for repeat in spec.repeats:
            assert {slot.seed for slot in spec.slots()
                    if slot.fixture_id == fixture and slot.repeat_id == repeat} == {
                spec.seed(fixture, repeat)}


def test_independent_property_rejects_marker_and_property_read_disagreement():
    assert accounting_state(["100", "0", "0", True])["violation"] is True
    assert accounting_state(["100", "100", "0", False])["property_holds"] is True
    with pytest.raises(ValueError, match="disagrees"):
        accounting_state(["100", "0", "0", False])
    step = {"signature": "spend(uint256)", "from": get_scenario("accounting_flawed").actor,
            "value": "0", "observe": ["100", "0", "0", True],
            "property_holds": True, "invariant_holds": True,
            "observer_state_unchanged": True, "state_root_before_observer": "root",
            "state_root_after_observer": "root", "coverage_markers": ["m"],
            "coverage_marker_hits": {"m": 1}, "status": "success", "success": True}
    with pytest.raises(StudyAuditError, match="property read"):
        _validate_steps("accounting_flawed", [step])


def test_safety_harness_keeps_execution_checks_and_supports_repaired_replay(tmp_path: Path):
    scenario = get_scenario("accounting_flawed")
    prefix = {"deployer": scenario.deployer, "steps": [{
        "from": scenario.actor, "to": "0x0000000000000000000000000000000000000011",
        "calldata": "0x" + keccak(b"open()")[:4].hex(),
        "value": "0", "actual_block": "1", "actual_timestamp": "1",
        "status": "success", "observe": ["100", "0", "100", False],
        "invariant_holds": True, "property_holds": True,
    }]}
    generated = generate_harness("accounting_flawed", prefix, tmp_path / "flawed", 100)
    source = Path(generated["harness_path"]).read_text()
    assert "_propertyConsistent()" in source
    assert "require(_matches(100, 0, 100, false)" in source
    assert "assert(!target.propertyHolds());" in source
    repaired = generate_harness(
        "accounting_repaired", prefix, tmp_path / "repaired", 100,
        expect_violation=False)
    assert "assert(target.propertyHolds());" in Path(repaired["harness_path"]).read_text()
    altered = copy.deepcopy(prefix)
    altered["steps"][0]["observe"][3] = True
    with pytest.raises(ValueError):
        validate_prefix({**altered, "native_path": "/dev/null", "native_digest": ""},
                        fixture_id="accounting_flawed", verify_native=False)
