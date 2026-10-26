"""Synthetic boundary tests; real Medusa/Halmos acceptance is stored separately."""

from copy import deepcopy

import pytest

from seedbridge.halmos import parse_suffix_result
from seedbridge.stage5_scheduler import QueryScheduler
from seedbridge.suffix import enumerate_plans, make_plan, prefix_identity


def prefix(*, block="2", root="0x01", fixture="reservation_flawed"):
    return {"native_digest": "f" * 64, "deployer": "0x" + "03" * 20,
            "steps": [{"from": "0x" + "01" * 20, "to": "0x" + "02" * 20,
                       "calldata": "0x819b25ba", "value": "0",
                       "actual_block": block, "actual_timestamp": "2",
                       "status": "success", "observe": ["100", "0", "0", False],
                       "property_holds": True, "invariant_holds": True,
                       "state_root_before_observer": root,
                       "state_root_after_observer": root,
                       "observer_state_unchanged": True}]}


def model_result() -> dict:
    model = {}
    for index, value in ((1, 91), (0, 8)):
        name = f"p_arg{index}_uint256_deadbeef_00"
        model[name] = {"full_name": name, "variable_name": f"arg{index}",
                       "solidity_type": "uint256", "smt_type": "BitVec 256",
                       "size_bits": 256, "value": value}
    return {"exitcode": 1, "test_results": {
        "test/BridgeHarness.t.sol:BridgeHarnessTest": [{
            "name": "check_suffix(uint256,uint256)", "exitcode": 1,
            "num_models": 1, "models": [{"model": model, "is_valid": True}],
            "num_paths": [3, 2, 0], "time": [0.1, 0.1, 0.0],
            "num_bounded_loops": 0}]}}


def test_two_variable_model_uses_names_not_json_order():
    result = parse_suffix_result(model_result(), "check_suffix(uint256,uint256)")
    assert result["status"] == "candidate"
    assert result["candidates"] == [{"arg0": "8", "arg1": "91"}]


@pytest.mark.parametrize("change", ["wrong_type", "missing", "duplicate_name", "out_of_range"])
def test_two_variable_model_rejects_malformed_assignments(change):
    document = model_result()
    model = document["test_results"]["test/BridgeHarness.t.sol:BridgeHarnessTest"][0]["models"][0]["model"]
    keys = list(model)
    if change == "wrong_type":
        model[keys[0]]["solidity_type"] = "uint128"
    elif change == "missing":
        del model[keys[0]]
    elif change == "duplicate_name":
        model[keys[0]]["variable_name"] = "arg0"
    else:
        model[keys[0]]["value"] = 1 << 256
    assert parse_suffix_result(document, "check_suffix(uint256,uint256)")["status"] == "decode_error"


def test_full_prefix_context_and_scenario_are_in_query_identity():
    a = prefix()
    b = deepcopy(a)
    b["steps"][0]["actual_block"] = "3"
    c = deepcopy(a)
    c["steps"][0]["state_root_after_observer"] = "0x02"
    assert prefix_identity("reservation_flawed", a) != prefix_identity("reservation_flawed", b)
    assert prefix_identity("reservation_flawed", a) != prefix_identity("reservation_flawed", c)
    assert prefix_identity("reservation_flawed", a) != prefix_identity("reservation_repaired", a)
    assert make_plan("reservation_flawed", a, ("reserve(uint256)",)).query_id != make_plan(
        "reservation_flawed", b, ("reserve(uint256)",)).query_id


def test_planner_generates_ordered_bounded_combinations_for_both_cases():
    for fixture, first, second in (
        ("reservation_flawed", "reserve(uint256)", "settle(uint256)"),
        ("request_flawed", "request(uint256)", "confirm(uint256)"),
    ):
        plans, decisions = enumerate_plans(fixture, prefix(fixture=fixture), 2)
        assert (first, second) in [tuple(call.signature for call in plan.calls)
                                   for plan in plans]
        assert len(plans) <= 8
        assert len(decisions) == 4
        assert all(len(plan.variables) <= 2 for plan in plans)


def test_adaptive_promotes_only_on_declared_no_progress_and_keeps_native_reserve():
    source = prefix()
    one = make_plan("reservation_flawed", source, ("reserve(uint256)",))
    two = make_plan("reservation_flawed", source,
                    ("reserve(uint256)", "settle(uint256)"))
    scheduler = QueryScheduler("symbolic_adaptive", [one], [two], 1, 5)
    assert scheduler.next_query(5.9) is None
    assert scheduler.next_query(10) == one
    scheduler.record_feedback(one, "no_model_complete", actual_seconds=0.3,
                              remaining_seconds=9.7)
    assert scheduler.next_query(9.7) == two
    scheduler.record_feedback(two, "confirmed", actual_seconds=1,
                              remaining_seconds=8.7)
    assert scheduler.next_query(8.7) is None
    assert scheduler.decisions[-1]["reason"] == "confirmed_property_violation"


def test_timeout_and_tool_error_do_not_become_complete_no_model():
    source = prefix()
    one = make_plan("request_flawed", source, ("request(uint256)",))
    two = make_plan("request_flawed", source,
                    ("request(uint256)", "confirm(uint256)"))
    for status in ("timeout", "unsupported", "tool_error"):
        scheduler = QueryScheduler("symbolic_adaptive", [one], [two], 1, 5)
        assert scheduler.next_query(10) == one
        scheduler.record_feedback(one, status, actual_seconds=0.5,
                                  remaining_seconds=9.5)
        assert not scheduler.promoted
        assert scheduler.next_query(9.5) is None
        assert scheduler.decisions[-1]["reason"] == "one_call_exhausted_without_complete_no_progress"
