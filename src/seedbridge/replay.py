"""Acceptance checks on concrete executions, independent of symbolic models."""

from pathlib import Path
from eth_hash.auto import keccak

from .doctor import tool_environment
from .io import read_json
from .process import run_command
from .safety import checked_state


BRIDGE_STEP_EVENT = "BridgeStep(uint256,bool,uint256,uint256,uint256,bool,bool,uint256,uint256)"


def _decode_bridge_steps(logs: object, fixture_id: str, expected_calls: list[dict]) -> list[dict]:
    if not isinstance(logs, list) or len(logs) != len(expected_calls):
        raise ValueError("Foundry replay has a missing or extra per-call event")
    topic = "0x" + keccak(BRIDGE_STEP_EVENT.encode()).hex()
    records = []
    for position, (event, call) in enumerate(zip(logs, expected_calls)):
        if (not isinstance(event, dict) or event.get("topics") != [topic]
                or not isinstance(event.get("data"), str)
                or not event["data"].startswith("0x")
                or len(event["data"]) != 2 + 9 * 64):
            raise ValueError("Foundry per-call event has an unexpected topic or layout")
        try:
            words = [int(event["data"][2 + offset * 64:2 + (offset + 1) * 64], 16)
                     for offset in range(9)]
        except ValueError as error:
            raise ValueError("Foundry per-call event is not hexadecimal") from error
        index, success, p, q, r, violation, property_holds, block, timestamp = words
        if (index != position or success not in (0, 1) or violation not in (0, 1)
                or property_holds not in (0, 1)
                or block != int(call["actual_block"])
                or timestamp != int(call["actual_timestamp"])):
            raise ValueError("Foundry per-call index, boolean, or context differs")
        state = checked_state(fixture_id, [str(p), str(q), str(r), bool(violation)])
        if state is None or state["property_holds"] is not bool(property_holds):
            raise ValueError("Foundry property read differs from independent arithmetic")
        records.append({"suffix_index": index, "success": bool(success),
                        "signature": call["signature"], "selector": call["selector"],
                        "argument": call.get("argument"), "actor": call["actor"],
                        "value": call["value"], "actual_block": str(block),
                        "actual_timestamp": str(timestamp),
                        "observe": [str(p), str(q), str(r), bool(violation)],
                        "property_holds": bool(property_holds),
                        "independent_state": state})
    return records


def concrete_replay_suffix(project: Path, output_dir: Path, timeout: float) -> dict:
    """Fresh Foundry deployment with independently decoded intermediate states."""
    manifest = read_json(Path(project) / "manifest.json")
    if (manifest.get("schema_version") != 2 or manifest.get("mode") != "safety"
            or not isinstance(manifest.get("assignments"), dict)):
        raise ValueError("concrete suffix replay needs a generated safety harness")
    result = run_command(["forge", "test", "--match-contract", "^BridgeHarnessTest$",
                          "--match-test", r"^test_replay\(\)$", "-vv", "--json"],
                         cwd=project, log_path=output_dir / "forge-replay.json",
                         timeout=timeout, env=tool_environment(),
                         stderr_path=output_dir / "forge-replay.stderr.log")
    metadata = {"command_result": result.to_dict()}
    if result.timed_out:
        return {"status": "timeout", "reason": "fresh Foundry replay timed out", **metadata}
    import json
    try:
        document = json.loads(Path(result.log_path).read_text())
        tests = [test for key, contract in document.items()
                 if key.endswith(":BridgeHarnessTest") and isinstance(contract, dict)
                 for name, test in contract.get("test_results", {}).items()
                 if name == "test_replay()"]
    except (OSError, ValueError, TypeError, AttributeError) as error:
        return {"status": "tool_error", "reason": f"Foundry JSON is unreadable: {error}", **metadata}
    if len(tests) != 1 or not isinstance(tests[0], dict):
        return {"status": "result_mismatch", "reason": "exactly one replay test is required", **metadata}
    if tests[0].get("status") == "Failure" and result.returncode != 0:
        return {"status": "replay_mismatch", "reason": "fresh replay assertions failed", **metadata}
    if tests[0].get("status") != "Success" or result.returncode != 0:
        return {"status": "result_mismatch", "reason": "Foundry process and test disagree", **metadata}
    try:
        steps = _decode_bridge_steps(tests[0].get("logs"), manifest["fixture_id"],
                                     manifest["suffix_calls"])
    except (ValueError, KeyError, TypeError) as error:
        return {"status": "result_mismatch", "reason": str(error), **metadata}
    first = next((step["suffix_index"] for step in steps
                  if not step["property_holds"]), None)
    expected = manifest["expected_violation"]
    if (type(expected) is not bool
            or expected != (first is not None)
            or expected and first != len(steps) - 1
            or expected and any(not step["success"] for step in steps)
            or any(not step["success"] for step in steps[:-1])):
        return {"status": "replay_mismatch",
                "reason": "per-call outcomes disagree with the declared replay claim",
                "steps": steps, **metadata}
    status = "violation_confirmed" if expected else "property_preserved"
    return {"status": status, "reason": "fresh replay and independent per-call arithmetic agree",
            "steps": steps, "first_violation_suffix_index": first,
            "first_violation_call_index": (None if first is None else
                                           len(read_json(Path(project) / "prefix.json")["steps"]) + first),
            "two_step_only": expected and len(steps) == 2 and first == 1,
            **metadata}


def concrete_replay(project: Path, output_dir: Path, timeout: float) -> dict:
    manifest = read_json(project / "manifest.json") if (project / "manifest.json").exists() else {}
    safety_mode = manifest.get("mode") == "safety"
    expected_violation = manifest.get("expected_violation", True)
    result = run_command(["forge", "test", "--match-contract", "^BridgeHarnessTest$",
                          "--match-test", r"^test_replay\(\)$", "--json"],
                         cwd=project, log_path=output_dir / "forge-replay.json",
                         timeout=timeout, env=tool_environment(),
                         stderr_path=output_dir / "forge-replay.stderr.log")
    metadata = {"command_result": result.to_dict()}
    if result.timed_out:
        return {"status": "timeout", "reason": "Forge concrete replay deadline reached", **metadata}

    # Forge can exit zero when the filter matches no tests. Require the actual test record.
    import json
    try:
        data = json.loads(Path(result.log_path).read_text())
        tests = [test for key, contract in data.items() if key.endswith(":BridgeHarnessTest") and isinstance(contract, dict)
                 for name, test in contract.get("test_results", {}).items()
                 if name == "test_replay()"]
    except (OSError, ValueError, AttributeError, TypeError) as error:
        return {"status": "tool_error", "reason": f"Forge produced unreadable JSON: {error}", **metadata}
    if len(tests) != 1 or not isinstance(tests[0], dict):
        return {"status": "result_mismatch", "reason": "expected exactly one concrete replay test", **metadata}
    test_status = tests[0].get("status")
    if test_status == "Success" and result.returncode == 0:
        if safety_mode:
            status = "violation_confirmed" if expected_violation else "property_preserved"
            return {"status": status, "reason": "fresh deployment checked the independent accounting property", **metadata}
        return {"status": "reachable_confirmed", "reason": "fresh deployment reached the goal", **metadata}
    if test_status == "Failure" and result.returncode != 0:
        return {"status": "replay_mismatch", "reason": "concrete replay did not satisfy its assertions", **metadata}
    return {"status": "result_mismatch", "reason": "Forge process and test outcomes disagree", **metadata}


def match_native_execution(observation: dict, expected: list[dict],
                           prefix: list[dict], *, require_goal: bool,
                           fixture_id: str | None = None) -> dict | None:
    fixture_id = fixture_id or observation.get("fixture")
    for sequence in observation.get("sequences", []):
        steps = sequence.get("steps", [])
        if len(steps) != len(expected):
            continue
        if any(any(str(actual.get(key, "")).lower() != str(wanted.get(key, "")).lower()
                   for key in ("from", "to", "calldata", "value"))
               for actual, wanted in zip(steps, expected)):
            continue
        if any(any(str(actual.get(key)) != str(wanted[key])
                   for key in ("actual_block", "actual_timestamp") if key in wanted)
               for actual, wanted in zip(steps, expected)):
            continue
        if any(step.get("status") != "success" or step.get("invariant_holds") is not True for step in steps):
            continue
        try:
            property_states = ([checked_state(fixture_id, step.get("observe")) for step in steps]
                               if fixture_id is not None else [None] * len(steps))
        except (ValueError, TypeError):
            continue
        if any(state is not None and step.get("property_holds") is not state["property_holds"]
               for step, state in zip(steps, property_states)):
            continue
        if any(any(actual.get(key) != wanted.get(key) for key in
                   ("observe", "actual_block", "actual_timestamp"))
               for actual, wanted in zip(steps, prefix)):
            continue
        if steps[-1].get("observe", [None])[-1] is not require_goal:
            continue
        evidence = sequence.get("admission_evidence", {})
        if (sequence.get("admitted") is not True or
                sequence.get("replayed_by_medusa") is not True or
                sequence.get("is_complete_sequence") is not True or
                evidence.get("kind") != "medusa_v1.5.1_post_sequence_event" or
                evidence.get("event") != "FuzzerWorker.CallSequenceTested" or
                evidence.get("full_sequence_executed") is not True or
                evidence.get("native_input_hash_matched") is not True or
                evidence.get("cancellation_before_event") is not False or
                evidence.get("shrink_requests") != 0):
            continue
        return sequence
    return None
