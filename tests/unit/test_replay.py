from copy import deepcopy
import json

import pytest

from seedbridge.process import CommandResult
from seedbridge.replay import concrete_replay, match_native_execution


def observed():
    step = {"from": "0x" + "11" * 20, "to": "0x" + "22" * 20,
            "calldata": "0x12345678", "value": "0", "actual_block": "1",
            "actual_timestamp": "2", "status": "success",
            "observe": ["2", "3", "0", False], "invariant_holds": True}
    return {"sequences": [{"steps": [step], "admitted": True,
                            "replayed_by_medusa": True, "is_complete_sequence": True,
                            "admission_evidence": {"kind": "medusa_v1.5.1_post_sequence_event",
                                                   "event": "FuzzerWorker.CallSequenceTested",
                                                   "full_sequence_executed": True,
                                                   "native_input_hash_matched": True,
                                                   "cancellation_before_event": False,
                                                   "shrink_requests": 0}}]}


def test_execution_requires_actual_matching_sequence():
    data = observed()
    prefix = deepcopy(data["sequences"][0]["steps"])
    assert match_native_execution(data, prefix, prefix, require_goal=False)
    data["sequences"][0]["steps"][0]["to"] = "0x" + "33" * 20
    assert match_native_execution(data, prefix, prefix, require_goal=False) is None


def test_execution_is_not_admission():
    data = observed()
    prefix = deepcopy(data["sequences"][0]["steps"])
    data["sequences"][0]["admitted"] = False
    assert match_native_execution(data, prefix, prefix, require_goal=False) is None


def test_state_or_context_drift_rejected():
    for key, value in [("observe", ["2", "4", "0", False]), ("actual_timestamp", "3")]:
        data = observed()
        prefix = deepcopy(data["sequences"][0]["steps"])
        data["sequences"][0]["steps"][0][key] = value
        assert match_native_execution(data, prefix, prefix, require_goal=False) is None


def test_last_call_context_must_match_even_outside_prefix():
    data = observed()
    expected = deepcopy(data["sequences"][0]["steps"])
    data["sequences"][0]["steps"][0]["actual_timestamp"] = "3"
    assert match_native_execution(data, expected, [], require_goal=False) is None


def forge_result(tmp_path, *, test_status="Success", returncode=0, timed_out=False):
    log = tmp_path / "forge.json"
    log.write_text(json.dumps({"test/BridgeHarness.t.sol:BridgeHarnessTest": {
        "test_results": {"test_replay()": {"status": test_status}}
    }}))
    return CommandResult(["forge"], returncode, 0.1, timed_out, str(log))


@pytest.mark.parametrize(("test_status", "returncode", "expected"), [
    ("Success", 0, "reachable_confirmed"),
    ("Failure", 1, "replay_mismatch"),
    ("Success", 1, "result_mismatch"),
])
def test_concrete_replay_classifies_forge_outcome(tmp_path, monkeypatch, test_status, returncode, expected):
    monkeypatch.setattr("seedbridge.replay.run_command", lambda *args, **kwargs: forge_result(
        tmp_path, test_status=test_status, returncode=returncode))
    assert concrete_replay(tmp_path, tmp_path / "out", 2)["status"] == expected


def test_concrete_replay_timeout_wins_over_partial_success(tmp_path, monkeypatch):
    monkeypatch.setattr("seedbridge.replay.run_command", lambda *args, **kwargs: forge_result(
        tmp_path, timed_out=True, returncode=143))
    assert concrete_replay(tmp_path, tmp_path / "out", 1)["status"] == "timeout"


def test_concrete_replay_requires_fresh_parseable_named_result(tmp_path, monkeypatch):
    log = tmp_path / "forge.json"
    log.write_text("not json")
    result = CommandResult(["forge"], 1, 0.1, False, str(log))
    monkeypatch.setattr("seedbridge.replay.run_command", lambda *args, **kwargs: result)
    assert concrete_replay(tmp_path, tmp_path / "out", 2)["status"] == "tool_error"

    log.write_text(json.dumps({}))
    assert concrete_replay(tmp_path, tmp_path / "out", 2)["status"] == "result_mismatch"
