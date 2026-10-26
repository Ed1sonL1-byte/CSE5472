"""Bounded, ordered one/two-call suffix plans for owned local fixtures."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from itertools import product
import json
import re
from pathlib import Path

from eth_hash.auto import keccak

from .config import UINT256_MAX, get_scenario
from .io import file_hash
from .trace import validate_prefix


SIGNATURE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\((?:uint256)?\)\Z")


@dataclass(frozen=True)
class SuffixCall:
    signature: str
    selector: str
    variable: str | None
    actor: str
    target: str
    value: str
    actual_block: str
    actual_timestamp: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SuffixPlan:
    fixture_id: str
    prefix_id: str
    query_id: str
    calls: tuple[SuffixCall, ...]

    @property
    def variables(self) -> tuple[str, ...]:
        return tuple(call.variable for call in self.calls if call.variable is not None)

    @property
    def test_signature(self) -> str:
        return "check_suffix(" + ",".join("uint256" for _ in self.variables) + ")"

    def to_dict(self) -> dict:
        return {"schema_version": 1, "fixture_id": self.fixture_id,
                "prefix_id": self.prefix_id, "query_id": self.query_id,
                "test_signature": self.test_signature,
                "variables": list(self.variables),
                "calls": [call.to_dict() for call in self.calls]}

    def concrete_calls(self, assignments: dict[str, str | int]) -> list[dict]:
        if set(assignments) != set(self.variables):
            raise ValueError("candidate assignments do not match the plan variables")
        result = []
        for call in self.calls:
            row = call.to_dict()
            if call.variable is not None:
                raw = assignments[call.variable]
                if type(raw) not in (str, int) or isinstance(raw, str) and (
                        not raw.isdecimal() or len(raw) > 1 and raw[0] == "0"):
                    raise ValueError("candidate argument is not canonical decimal uint256")
                value = int(raw)
                if not 0 <= value <= UINT256_MAX:
                    raise ValueError("candidate argument is outside uint256")
                row["argument"] = str(value)
            else:
                row["argument"] = None
            result.append(row)
        return result


def _digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def prefix_identity(fixture_id: str, prefix: dict) -> str:
    """Include provenance, every call/context, full observed state and roots."""
    scenario = get_scenario(fixture_id)
    if not isinstance(prefix.get("native_digest"), str):
        raise ValueError("prefix lacks native provenance digest")
    steps = []
    for step in prefix["steps"]:
        keys = ("from", "to", "calldata", "value", "actual_block", "actual_timestamp",
                "status", "observe", "property_holds", "invariant_holds",
                "state_root_before_observer", "state_root_after_observer")
        if any(key not in step for key in keys):
            raise ValueError("prefix lacks full context or state-root evidence")
        steps.append({key: step[key] for key in keys})
    return _digest({"fixture_id": fixture_id,
                    "fixture_source_sha256": file_hash(scenario.source_file),
                    "deployer": prefix.get("deployer"),
                    "native_digest": prefix["native_digest"], "steps": steps})


def select_stage5_prefixes(observation: dict, fixture_id: str, limit: int) -> tuple[list[dict], list[dict]]:
    if limit < 1:
        raise ValueError("prefix limit must be positive")
    scenario = get_scenario(fixture_id)
    required = scenario.stage5_required_prefix_call
    selected, rejected, seen = [], [], set()
    for sequence in observation.get("sequences", []):
        try:
            prefix = validate_prefix(sequence, fixture_id=fixture_id, require_ready=False)
            if len(prefix["steps"]) > 3:
                raise ValueError("prefix is longer than three calls")
            for step in prefix["steps"]:
                if step.get("property_holds") is not True:
                    raise ValueError("prefix already violated the safety property")
                if (step.get("observer_state_unchanged") is not True
                        or step.get("state_root_before_observer")
                        != step.get("state_root_after_observer")):
                    raise ValueError("prefix observer changed execution state")
                signature = step.get("signature")
                if (signature not in scenario.allowed_calls
                        or step["calldata"][:10].lower()
                        != "0x" + keccak(signature.encode())[:4].hex()):
                    raise ValueError("prefix call signature disagrees with calldata")
            if required and not any(step["signature"] == required for step in prefix["steps"]):
                raise ValueError("prefix has not executed its declared setup call")
            identity = prefix_identity(fixture_id, prefix)
            if identity in seen:
                raise ValueError("duplicate full-context prefix query")
            seen.add(identity)
            selected.append({**prefix, "stage5_prefix_id": identity})
        except (ValueError, KeyError, TypeError) as error:
            rejected.append({"native_digest": sequence.get("native_digest"),
                             "reason": str(error)})
    selected.sort(key=lambda item: (len(item["steps"]), item["stage5_prefix_id"]))
    return selected[:limit], rejected


def make_plan(fixture_id: str, prefix: dict, signatures: tuple[str, ...]) -> SuffixPlan:
    scenario = get_scenario(fixture_id)
    if not 1 <= len(signatures) <= 2 or len(prefix["steps"]) + len(signatures) > 5:
        raise ValueError("the complete sequence must contain at most five calls")
    if any(signature not in scenario.stage5_suffix_calls or not SIGNATURE.fullmatch(signature)
           for signature in signatures):
        raise ValueError("suffix contains an unsupported call signature")
    last = prefix["steps"][-1]
    calls = []
    argument_index = 0
    for signature in signatures:
        variable = None
        if signature.endswith("(uint256)"):
            variable = f"arg{argument_index}"
            argument_index += 1
        calls.append(SuffixCall(
            signature=signature, selector="0x" + keccak(signature.encode())[:4].hex(),
            variable=variable, actor=last["from"], target=last["to"], value="0",
            actual_block=str(last["actual_block"]),
            actual_timestamp=str(last["actual_timestamp"])))
    if argument_index > 2:
        raise ValueError("at most two symbolic uint256 arguments are supported")
    prefix_id = prefix.get("stage5_prefix_id") or prefix_identity(fixture_id, prefix)
    query_id = _digest({"prefix_id": prefix_id,
                        "calls": [call.to_dict() for call in calls],
                        "solver_test": "check_suffix", "schema_version": 1})
    return SuffixPlan(fixture_id, prefix_id, query_id, tuple(calls))


def enumerate_plans(fixture_id: str, prefix: dict, suffix_length: int,
                    *, max_plans: int = 8) -> tuple[list[SuffixPlan], list[dict]]:
    if suffix_length not in (1, 2) or max_plans < 1:
        raise ValueError("unsupported suffix length or plan limit")
    scenario = get_scenario(fixture_id)
    plans, decisions = [], []
    for signatures in product(scenario.stage5_suffix_calls, repeat=suffix_length):
        descriptor = {"signatures": list(signatures), "suffix_length": suffix_length}
        if len(prefix["steps"]) + suffix_length > 5:
            decisions.append({**descriptor, "status": "skipped", "reason": "full_sequence_limit"})
            continue
        if not any(signature.endswith("(uint256)") for signature in signatures):
            decisions.append({**descriptor, "status": "skipped", "reason": "no_symbolic_argument"})
            continue
        if len(plans) >= max_plans:
            decisions.append({**descriptor, "status": "skipped", "reason": "plan_count_limit"})
            continue
        plan = make_plan(fixture_id, prefix, tuple(signatures))
        plans.append(plan)
        decisions.append({**descriptor, "status": "planned", "query_id": plan.query_id})
    return plans, decisions
