import json
from pathlib import Path

import pytest

from seedbridge.config import UINT256_MAX
from seedbridge.halmos import parse_result, run_halmos
from seedbridge.process import CommandResult


def document(expected="check_goal(uint256)", code=1, value=67):
    name = "p_arg0_uint256_a1b2c3_00"
    models = [{"is_valid": True, "model": {name: {
        "full_name": name, "variable_name": "arg0", "solidity_type": "uint256",
        "smt_type": "BitVec 256", "size_bits": 256, "value": value,
    }}}] if code == 1 else []
    return {"exitcode": 0 if code == 0 else 1, "test_results": {
        "test/BridgeHarness.t.sol:BridgeHarnessTest": [{
            "name": expected, "exitcode": code, "num_models": len(models),
            "models": models, "num_paths": [2, 1, 0], "time": [0.2, 0.1, 0.1],
            "num_bounded_loops": 0,
        }],
    }}


def only_test(data):
    return next(iter(data["test_results"].values()))[0]


def test_goal_failure_is_candidate_not_confirmed_reachability():
    result = parse_result(document(), "check_goal(uint256)")
    assert result["status"] == "candidate"
    assert result["candidates"] == ["67"]
    assert "replay" in result["reason"]


@pytest.mark.parametrize("code,status", [
    (0, "no_witness_within_bounds"), (2, "timeout"), (3, "stuck"),
    (4, "all_paths_reverted"), (5, "tool_error"),
])
def test_nonwitness_outcomes_are_not_counterexamples(code, status):
    result = parse_result(document(code=code), "check_goal(uint256)")
    assert result["status"] == status
    assert result["candidates"] == []


def test_prefix_success_and_mismatch_are_separate_from_goal():
    assert parse_result(document("check_prefix()", 0), "check_prefix()")["status"] == "prefix_confirmed"
    assert parse_result(document("check_prefix()", 1), "check_prefix()")["status"] == "prefix_mismatch"
    bounded = document("check_prefix()", 0)
    only_test(bounded)["num_bounded_loops"] = 1
    assert parse_result(bounded, "check_prefix()")["status"] == "prefix_incomplete"


@pytest.mark.parametrize("change", ["wrong_name", "empty_tests", "extra_contract", "minimal", "exit_mismatch"])
def test_rejects_stale_or_incomplete_result_identity(change):
    data = document()
    if change == "wrong_name":
        only_test(data)["name"] = "check_other(uint256)"
    elif change == "empty_tests":
        data["test_results"] = {"test/BridgeHarness.t.sol:BridgeHarnessTest": []}
    elif change == "extra_contract":
        data["test_results"]["other.sol:OtherTest"] = []
    elif change == "minimal":
        only_test(data)["models"] = None
    else:
        data["exitcode"] = 0
    assert parse_result(data, "check_goal(uint256)")["status"] == "result_mismatch"


@pytest.mark.parametrize("field,value", [
    ("value", -1), ("value", UINT256_MAX + 1), ("value", True), ("value", "67"),
    ("variable_name", "other"), ("solidity_type", "uint8"), ("size_bits", 8),
    ("smt_type", "BitVec 8"), ("full_name", "different"),
])
def test_rejects_ambiguous_or_nonuint_model(field, value):
    data = document()
    variable = next(iter(only_test(data)["models"][0]["model"].values()))
    variable[field] = value
    result = parse_result(data, "check_goal(uint256)")
    assert result["status"] == "decode_error"
    assert result["candidates"] == []


def test_invalid_and_empty_models_never_become_default_arguments():
    invalid = document()
    only_test(invalid)["models"][0]["is_valid"] = False
    assert parse_result(invalid, "check_goal(uint256)")["status"] == "invalid_model"
    empty = document()
    only_test(empty)["models"][0]["model"] = {}
    assert parse_result(empty, "check_goal(uint256)")["status"] == "decode_error"


def test_uint256_precision_is_preserved_in_public_result():
    parsed = parse_result(document(value=UINT256_MAX), "check_goal(uint256)")
    assert parsed["candidates"] == [str(UINT256_MAX)]


def test_fresh_output_does_not_reuse_previous_json(tmp_path, monkeypatch):
    previous = tmp_path / "outputs" / "result.json"
    previous.parent.mkdir()
    previous.write_text(json.dumps(document()))

    def missing(command, *, cwd, log_path, timeout, env):
        log_path.write_text("compilation failed")
        return CommandResult(command, 1, 0.1, False, str(log_path))

    monkeypatch.setattr("seedbridge.halmos.run_command", missing)
    result = run_halmos(tmp_path, "check_goal(uint256)", previous.parent, 2, "/bin/false")
    assert result["status"] == "tool_error"
    assert Path(result["output_path"]) != previous


def test_external_timeout_wins_over_partial_json(tmp_path, monkeypatch):
    def timeout_run(command, *, cwd, log_path, timeout, env):
        Path(command[command.index("--json-output") + 1]).write_text(json.dumps(document()))
        log_path.write_text("partial candidate")
        return CommandResult(command, 143, 1.0, True, str(log_path))

    monkeypatch.setattr("seedbridge.halmos.run_command", timeout_run)
    result = run_halmos(tmp_path, "check_goal(uint256)", tmp_path / "outputs", 1, "/bin/false")
    assert result["status"] == "timeout"
    assert result["candidates"] == []


def test_process_code_cannot_override_model_interpretation(tmp_path, monkeypatch):
    def mismatched(command, *, cwd, log_path, timeout, env):
        Path(command[command.index("--json-output") + 1]).write_text(json.dumps(document()))
        log_path.write_text("inconsistent output")
        return CommandResult(command, 0, 0.1, False, str(log_path))

    monkeypatch.setattr("seedbridge.halmos.run_command", mismatched)
    result = run_halmos(tmp_path, "check_goal(uint256)", tmp_path / "outputs", 2, "/bin/false")
    assert result["status"] == "result_mismatch"


def test_actual_halmos_033_goal_sample():
    sample = Path(__file__).parents[1] / "data" / "halmos033-goal.json"
    result = parse_result(json.loads(sample.read_text()), "check_goal(uint256)")
    assert result["status"] == "candidate"
    assert result["candidates"] == ["67"]


def test_actual_halmos_033_prefix_sample():
    sample = Path(__file__).parents[1] / "data" / "halmos033-prefix.json"
    result = parse_result(json.loads(sample.read_text()), "check_prefix()")
    assert result["status"] == "prefix_confirmed"
    assert result["candidates"] == []
