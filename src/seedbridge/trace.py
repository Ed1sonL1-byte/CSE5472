"""Validate observed native sequences before emitting concrete harness input."""

import hashlib
import json
from pathlib import Path
import re

from .config import UINT256_MAX
from .io import file_hash

ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}\Z")
CALLDATA = re.compile(r"0x(?:[0-9a-fA-F]{2}){4,}\Z")


def uint(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("Expected a uint256 decimal or hex value")
    number = int(value, 16 if isinstance(value, str) and value.startswith("0x") else 10) if isinstance(value, str) else value
    if not 0 <= number <= UINT256_MAX:
        raise ValueError("Value outside uint256 range")
    return number


def sequence_identity(steps: list[dict]) -> str:
    # Environmental context is part of the identity: do not discard a delay.
    projection = [{key: step[key] for key in
                   ("from", "to", "calldata", "value", "actual_block", "actual_timestamp")}
                  for step in steps]
    return hashlib.sha256(json.dumps(projection, sort_keys=True).encode()).hexdigest()


def validate_prefix(sequence: dict, *, verify_native: bool = True) -> dict:
    steps = sequence.get("steps", [])
    if not 1 <= len(steps) <= 3:
        raise ValueError("A prefix must contain 1–3 concrete calls")
    actor, target = None, None
    previous_block = previous_time = -1
    for step in steps:
        if step.get("status") != "success":
            raise ValueError("Prefix contains an unsuccessful call")
        if not ADDRESS.fullmatch(step.get("from", "")) or not ADDRESS.fullmatch(step.get("to", "")):
            raise ValueError("Malformed actor or target address")
        if not CALLDATA.fullmatch(step.get("calldata", "")):
            raise ValueError("Malformed calldata")
        if uint(step.get("value")) != 0:
            raise ValueError("Only value=0 is supported")
        actor = actor or step["from"].lower()
        target = target or step["to"].lower()
        if actor != step["from"].lower() or target != step["to"].lower():
            raise ValueError("Only one fixed actor and target are supported")
        block, timestamp = uint(step.get("actual_block")), uint(step.get("actual_timestamp"))
        if block < previous_block or timestamp < previous_time:
            raise ValueError("Execution context moves backwards")
        previous_block, previous_time = block, timestamp
        state = step.get("observe", [])
        if len(state) != 4 or type(state[-1]) is not bool:
            raise ValueError("Malformed state projection")
        for number in state[:3]:
            uint(number)
        if step.get("invariant_holds") is not True:
            raise ValueError("Independent fixture invariant did not hold")
    if steps[-1]["observe"][-1]:
        raise ValueError("Goal already holds before the symbolic call")
    if uint(steps[-1]["observe"][0]) != 2:
        raise ValueError("Prefix did not reach the fixture's declared ready state")
    if verify_native:
        native_path = Path(sequence["native_path"])
        if not native_path.is_file() or file_hash(native_path) != sequence["native_digest"]:
            raise ValueError("Native sequence provenance does not match")
    return {**sequence, "case_id": sequence_identity(steps)}


def select_prefixes(observation: dict, limit: int = 5) -> tuple[list[dict], list[dict]]:
    candidates, rejected, seen = [], [], set()
    for sequence in observation.get("sequences", []):
        try:
            prefix = validate_prefix(sequence)
            if prefix["case_id"] in seen:
                raise ValueError("Duplicate prefix")
            seen.add(prefix["case_id"])
            candidates.append(prefix)
        except (ValueError, KeyError, TypeError) as error:
            rejected.append({"native_digest": sequence.get("native_digest"), "reason": str(error)})
    candidates.sort(key=lambda case: (len(case["steps"]), case["case_id"]))
    return candidates[:limit], rejected
