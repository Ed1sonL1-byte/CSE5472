"""Acceptance checks on concrete executions, independent of symbolic models."""

from pathlib import Path

from .doctor import tool_environment
from .process import run_command


def concrete_replay(project: Path, output_dir: Path, timeout: float) -> dict:
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
        return {"status": "reachable_confirmed", "reason": "fresh deployment reached the goal", **metadata}
    if test_status == "Failure" and result.returncode != 0:
        return {"status": "replay_mismatch", "reason": "concrete replay did not satisfy its assertions", **metadata}
    return {"status": "result_mismatch", "reason": "Forge process and test outcomes disagree", **metadata}


def match_native_execution(observation: dict, expected: list[dict],
                           prefix: list[dict], *, require_goal: bool) -> dict | None:
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
