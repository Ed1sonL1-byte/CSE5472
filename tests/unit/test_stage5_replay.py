"""Synthetic fail-closed replay checks, distinct from real integration evidence."""

from copy import deepcopy

import pytest

from seedbridge.process import EvidenceMismatchError
from seedbridge.stage5_replay import expected_calldata, validate_native_suffix
from seedbridge.suffix import make_plan


def case(*, early=False):
    actor = "0x" + "01" * 20
    target = "0x" + "02" * 20
    def step(signature, argument, observe, index):
        return {"from": actor, "to": target, "value": "0",
                "actual_block": "2", "actual_timestamp": "2",
                "calldata": expected_calldata(signature, argument),
                "signature": signature, "status": "success", "success": True,
                "observe": observe, "property_holds": not observe[-1],
                "invariant_holds": True, "observer_state_unchanged": True,
                "state_root_before_observer": f"0x{index:064x}",
                "state_root_after_observer": f"0x{index:064x}"}
    prefix = {"native_digest": "f" * 64, "deployer": "0x" + "03" * 20,
              "steps": [step("start()", None, ["100", "0", "0", False], 1)]}
    plan = make_plan("reservation_flawed", prefix,
                     ("reserve(uint256)", "settle(uint256)"))
    assignments = {"arg0": "36", "arg1": "36"}
    middle = (["64", "36", "36", True] if early else
              ["64", "36", "0", False])
    suffix = [step("reserve(uint256)", "36", middle, 2),
              step("settle(uint256)", "36", ["64", "36", "36", True], 3)]
    full = prefix["steps"] + suffix
    summary = {"medusa_hash": "0x" + "a" * 64, "steps": full}
    observed = {"sequences": [{"medusa_hash": summary["medusa_hash"],
                               "is_complete_sequence": True,
                               "admitted_for_mutation": True,
                               "replayed_by_medusa": True,
                               "admission_evidence": {
                                   "kind": "medusa_v1.5.1_post_sequence_event",
                                   "event": "FuzzerWorker.CallSequenceTested",
                                   "native_input_hash_matched": True,
                                   "full_sequence_executed": True,
                                   "cancellation_before_event": False,
                                   "shrink_requests": 0},
                               "steps": full}]}
    foundry = [{"success": item["success"], "observe": item["observe"],
                "property_holds": item["property_holds"]} for item in suffix]
    return observed, summary, prefix, plan, assignments, foundry


def confirm(data):
    return validate_native_suffix("reservation_flawed", *data)


def test_native_replay_classifies_first_and_second_suffix_violations():
    later = confirm(case())
    assert later["two_step_only"] is True
    assert later["first_violation_call_index"] == 2
    earlier = confirm(case(early=True))
    assert earlier["two_step_only"] is False
    assert earlier["classification"] == "single_step_counterexample"
    assert earlier["first_violation_call_index"] == 1


def test_repaired_native_property_failure_is_a_regression_error():
    with pytest.raises(EvidenceMismatchError) as failure:
        validate_native_suffix("reservation_repaired", *case(), repaired=True)
    assert failure.value.status == "repaired_regression_failure"


@pytest.mark.parametrize("fault", ["intermediate_revert", "intermediate_state",
                                   "observer_changed", "context_changed"])
def test_native_replay_rejects_intermediate_inconsistency(fault):
    data = list(case())
    data = deepcopy(data)
    middle = data[0]["sequences"][0]["steps"][1]
    if fault == "intermediate_revert":
        middle["success"] = False
        middle["status"] = "revert"
    elif fault == "intermediate_state":
        middle["observe"] = ["63", "37", "0", False]
    elif fault == "observer_changed":
        middle["observer_state_unchanged"] = False
    else:
        middle["actual_timestamp"] = "3"
    with pytest.raises(ValueError):
        confirm(data)
