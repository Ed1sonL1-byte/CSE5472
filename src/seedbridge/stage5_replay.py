"""Fail-closed Medusa confirmation of a concrete ordered suffix."""

from __future__ import annotations

from eth_hash.auto import keccak

from .config import get_scenario
from .process import EvidenceMismatchError
from .safety import checked_state
from .suffix import SuffixPlan


def expected_calldata(signature: str, argument: str | None) -> str:
    selector = keccak(signature.encode())[:4].hex()
    if signature.endswith("()"):
        if argument is not None:
            raise ValueError("a no-argument call has an argument")
        return "0x" + selector
    if not signature.endswith("(uint256)") or argument is None:
        raise ValueError("only one uint256 argument per call is supported")
    value = int(argument)
    if not 0 <= value < (1 << 256):
        raise ValueError("candidate argument is outside uint256")
    return "0x" + selector + value.to_bytes(32, "big").hex()


def _observed_step(fixture_id: str, step: dict) -> dict:
    if (step.get("invariant_holds") is not True
            or step.get("observer_state_unchanged") is not True
            or step.get("state_root_before_observer")
            != step.get("state_root_after_observer")):
        raise ValueError("native step failed structural or observer-neutrality checks")
    state = checked_state(fixture_id, step.get("observe"))
    if state is None or step.get("property_holds") is not state["property_holds"]:
        raise ValueError("native step property read disagrees with independent arithmetic")
    return state


def validate_native_suffix(fixture_id: str, observation: dict, native_summary: dict,
                           prefix: dict, plan: SuffixPlan, assignments: dict[str, str],
                           foundry_steps: list[dict], *, repaired: bool = False) -> dict:
    scenario = get_scenario(fixture_id)
    if scenario.mode != "safety" or len(foundry_steps) != len(plan.calls):
        raise ValueError("native suffix confirmation requires matching safety calls")
    calls = plan.concrete_calls(assignments)
    input_steps = native_summary.get("steps")
    if (not isinstance(input_steps, list)
            or len(input_steps) != len(prefix["steps"]) + len(calls)):
        raise ValueError("native input does not contain the complete planned sequence")
    expected_hash = native_summary.get("medusa_hash")
    matches = [sequence for sequence in observation.get("sequences", [])
               if sequence.get("is_complete_sequence") is True
               and sequence.get("medusa_hash") == expected_hash]
    if len(matches) != 1:
        raise ValueError("native input was not uniquely executed as a complete sequence")
    sequence = matches[0]
    admission = sequence.get("admission_evidence", {})
    if (sequence.get("admitted_for_mutation") is not True
            or sequence.get("replayed_by_medusa") is not True
            or admission.get("kind") != "medusa_v1.5.1_post_sequence_event"
            or admission.get("event") != "FuzzerWorker.CallSequenceTested"
            or admission.get("native_input_hash_matched") is not True
            or admission.get("full_sequence_executed") is not True
            or admission.get("cancellation_before_event") is not False
            or admission.get("shrink_requests") != 0):
        raise ValueError("native candidate lacks completed execution and mutation admission")
    steps = sequence.get("steps", [])
    if len(steps) != len(input_steps):
        raise ValueError("native execution length differs from the encoded candidate")
    for position, (step, encoded) in enumerate(zip(steps, input_steps)):
        if any(str(step.get(key)).lower() != str(encoded.get(key)).lower()
               for key in ("from", "to", "value", "calldata")):
            raise ValueError(f"native execution call {position} differs from encoded input")
        _observed_step(fixture_id, step)
    for position, (actual, expected) in enumerate(zip(steps, prefix["steps"])):
        keys = ("from", "to", "value", "calldata", "status", "observe",
                "invariant_holds", "property_holds", "actual_block", "actual_timestamp")
        if any(str(actual.get(key)).lower() != str(expected.get(key)).lower()
               for key in keys):
            raise ValueError(f"native replay prefix step {position} differs")
        if not repaired and any(actual.get(key) != expected.get(key)
                                for key in ("state_root_before_observer",
                                            "state_root_after_observer")):
            raise ValueError(f"native replay prefix root {position} differs")
    suffix = steps[len(prefix["steps"]):]
    for position, (step, call, foundry) in enumerate(zip(suffix, calls, foundry_steps)):
        if (step.get("signature") != call["signature"]
                or step.get("calldata", "").lower()
                != expected_calldata(call["signature"], call["argument"])
                or step.get("from", "").lower() != call["actor"].lower()
                or step.get("to", "").lower() != call["target"].lower()
                or str(step.get("value")) != call["value"]
                or str(step.get("actual_block")) != call["actual_block"]
                or str(step.get("actual_timestamp")) != call["actual_timestamp"]
                or step.get("success") is not foundry["success"]
                or step.get("observe") != foundry["observe"]
                or step.get("property_holds") is not foundry["property_holds"]):
            raise ValueError(f"native suffix step {position} differs from plan or fresh Foundry replay")
    violations = [index for index, step in enumerate(suffix)
                  if not _observed_step(fixture_id, step)["property_holds"]]
    first = violations[0] if violations else None
    if repaired and first is not None:
        raise EvidenceMismatchError(
            "repaired native sequence violates its independent property",
            status="repaired_regression_failure")
    if not repaired and first is None:
        raise ValueError("flawed native sequence did not confirm a property violation")
    return {"status": "property_preserved" if repaired else "violation_confirmed",
            "medusa_hash": expected_hash, "admitted_for_mutation": True,
            "complete_sequence_executed": True, "first_violation_suffix_index": first,
            "first_violation_call_index": (None if first is None else
                                           len(prefix["steps"]) + first),
            "two_step_only": first == 1 and len(calls) == 2,
            "classification": ("property_preserved" if repaired else
                               "single_step_counterexample" if first == 0 else
                               "two_step_only_counterexample"),
            "steps": steps, "admission_evidence": admission}
