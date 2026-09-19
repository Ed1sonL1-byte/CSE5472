"""Generate a bounded replay harness only for the two owned state machines."""

import re
from pathlib import Path
import shutil

from eth_hash.auto import keccak

from .config import UINT256_MAX, get_scenario
from .io import file_hash, write_json


ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}\Z")
HEX_BYTES = re.compile(r"0x(?:[0-9a-fA-F]{2})*\Z")
UINT_TEXT = re.compile(r"(?:[0-9]+|0x[0-9a-fA-F]+)\Z")
BUILD = {"solc": "0.8.36", "evm_version": "shanghai", "optimizer": False}


def _uint(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a uint256, not a boolean")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and UINT_TEXT.fullmatch(value):
        result = int(value, 16 if value.startswith("0x") else 10)
    else:
        raise ValueError(f"{label} must be an integer or canonical numeric string")
    if not 0 <= result <= UINT256_MAX:
        raise ValueError(f"{label} is outside uint256")
    return result


def _address(value: object, label: str) -> str:
    if not isinstance(value, str) or not ADDRESS.fullmatch(value):
        raise ValueError(f"{label} must be a 20-byte hex address")
    return value.lower()


def _sol_address(value: str) -> str:
    # A bytes literal avoids Solidity's address-literal checksum interpretation.
    return f'address(bytes20(hex"{value[2:]}"))'


def _normalize_prefix(fixture_id: str, prefix: dict) -> dict:
    scenario = get_scenario(fixture_id)
    if not isinstance(prefix, dict):
        raise ValueError("prefix must be an object")
    steps = prefix.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 3:
        raise ValueError("a prefix must have one to three steps")
    permitted = {
        keccak(signature.encode())[:4].hex(): (4 if "()" in signature else 36)
        for signature in scenario.allowed_calls
    }
    normalized = []
    target = None
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or step.get("status") != "success":
            raise ValueError(f"step {index} must record a successful call")
        sender = _address(step.get("from"), f"step {index} sender")
        if sender != scenario.actor.lower():
            raise ValueError("prefix sender differs from the scenario actor")
        recipient = _address(step.get("to"), f"step {index} target")
        if target is not None and recipient != target:
            raise ValueError("all prefix calls must target the same fixture instance")
        target = recipient
        calldata = step.get("calldata")
        if not isinstance(calldata, str) or not HEX_BYTES.fullmatch(calldata):
            raise ValueError(f"step {index} calldata must be even-length hex")
        calldata = calldata.lower()
        selector = calldata[2:10]
        if selector not in permitted or (len(calldata) - 2) // 2 != permitted[selector]:
            raise ValueError(f"step {index} is not a supported static fixture call")
        if _uint(step.get("value"), "call value") != 0:
            raise ValueError("SeedBridge only supports zero-value calls")
        block = _uint(step.get("actual_block"), "actual_block")
        timestamp = _uint(step.get("actual_timestamp"), "actual_timestamp")
        if normalized and (block < int(normalized[-1]["actual_block"]) or
                           timestamp < int(normalized[-1]["actual_timestamp"])):
            raise ValueError("prefix block number and timestamp must not decrease")
        observation = step.get("observe")
        if not isinstance(observation, list) or len(observation) != 4:
            raise ValueError("observe must contain three uint256 values and one boolean")
        observation = [str(_uint(item, "observation")) for item in observation[:3]] + [observation[3]]
        if type(observation[3]) is not bool:
            raise ValueError("observation goal must be a boolean")
        if observation[3]:
            raise ValueError("the prefix must not already reach the goal")
        if step.get("invariant_holds") is not True:
            raise ValueError("every prefix observation must satisfy the fixture invariant")
        normalized.append({"from": sender, "to": recipient, "calldata": calldata,
                           "value": "0", "actual_block": str(block),
                           "actual_timestamp": str(timestamp), "status": "success",
                           "observe": observation, "invariant_holds": True})
    result = {"fixture_id": scenario.fixture_id, "steps": normalized}
    if not scenario.ready(normalized[-1]["observe"], len(normalized)):
        raise ValueError("prefix does not satisfy the scenario ready predicate and length bounds")
    if "deployer" in prefix:
        result["deployer"] = _address(prefix["deployer"], "deployer")
        if result["deployer"] != scenario.deployer.lower():
            raise ValueError("prefix deployer differs from the scenario deployment recipe")
    return result


def _prefix_lines(steps: list[dict], assertions: bool) -> str:
    lines = []
    for index, step in enumerate(steps):
        sender = _sol_address(step["from"])
        observation = step["observe"]
        expression = f'_matches({observation[0]}, {observation[1]}, {observation[2]}, false)'
        lines += ["        {", f'            vm.roll({step["actual_block"]});',
                  f'            vm.warp({step["actual_timestamp"]});',
                  f"            vm.prank({sender}, {sender});",
                  f'            (bool ok, ) = address(target).call(hex"{step["calldata"][2:]}");']
        if assertions:
            lines += ["            assert(ok);", f"            assert({expression});",
                      "            assert(target.invariantHolds());"]
        else:
            lines += [f'            require(ok, "PREFIX_CALL_{index}");',
                      f'            require({expression}, "PREFIX_STATE_{index}");',
                      f'            require(target.invariantHolds(), "PREFIX_INVARIANT_{index}");']
        lines.append("        }")
    return "\n".join(lines)


def generate_harness(fixture_id: str, prefix: dict, destination: Path,
                     argument: int | None = None) -> dict:
    scenario = get_scenario(fixture_id)
    normalized = _normalize_prefix(fixture_id, prefix)
    concrete_argument = None if argument is None else _uint(argument, "argument")
    destination = Path(destination).resolve()
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError("harness destination must be new or empty")
    last = normalized["steps"][-1]
    suffix = {key: last[key] for key in
              ("from", "to", "value", "actual_block", "actual_timestamp")}
    suffix["signature"] = f"{scenario.suffix}(uint256)"
    deploy_line = ""
    if "deployer" in normalized:
        deployer = _sol_address(normalized["deployer"])
        deploy_line = f"        vm.prank({deployer}, {deployer});\n"
    sender = _sol_address(suffix["from"])
    context_lines = (f'        vm.roll({suffix["actual_block"]});\n'
                     f'        vm.warp({suffix["actual_timestamp"]});\n'
                     f"        vm.prank({sender}, {sender});")
    concrete_test = ""
    if concrete_argument is not None:
        concrete_test = f"""
    function test_replay() external {{
        _prefixGuard();
        (, , , bool beforeGoal) = target.observe();
        assert(!beforeGoal);
{context_lines}
        target.{scenario.suffix}({concrete_argument});
        (, , , bool afterGoal) = target.observe();
        assert(afterGoal);
        assert(target.invariantHolds());
    }}
"""
    source = f"""// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;
import {{{scenario.contract}}} from "../src/{scenario.contract}.sol";

interface Vm {{
    function prank(address sender, address origin) external;
    function roll(uint256 blockNumber) external;
    function warp(uint256 timestamp) external;
}}

// Generated solely for an owned, inert state-machine fixture.
contract BridgeHarnessTest {{
    Vm private constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    {scenario.contract} private target;

    function setUp() public {{
{deploy_line}        target = new {scenario.contract}();
    }}

    function _matches(uint256 a, uint256 b, uint256 c, bool d) internal view returns (bool) {{
        (uint256 p, uint256 q, uint256 r, bool s) = target.observe();
        return p == a && q == b && r == c && s == d;
    }}

    function check_prefix() external {{
{_prefix_lines(normalized["steps"], True)}
    }}

    function _prefixGuard() internal {{
{_prefix_lines(normalized["steps"], False)}
    }}

    function check_goal(uint256 arg0) external {{
        _prefixGuard();
        (, , , bool beforeGoal) = target.observe();
        require(!beforeGoal, "GOAL_ALREADY_TRUE");
{context_lines}
        target.{scenario.suffix}(arg0);
        require(target.invariantHolds(), "SUFFIX_INVARIANT");
        (, , , bool goal) = target.observe();
        assert(!goal);
    }}
{concrete_test}}}
"""
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "src").mkdir()
    (destination / "test").mkdir()
    fixture_copy = destination / "src" / scenario.source_file.name
    shutil.copyfile(scenario.source_file, fixture_copy)
    config_path = destination / "foundry.toml"
    shutil.copyfile(scenario.root / "foundry.toml", config_path)
    harness_path = destination / "test" / "BridgeHarness.t.sol"
    harness_path.write_text(source)
    prefix_path = destination / "prefix.json"
    write_json(prefix_path, normalized)
    manifest_path = destination / "manifest.json"
    manifest = {
        "schema_version": 1, "fixture_id": fixture_id,
        "project_path": str(destination), "manifest_path": str(manifest_path),
        "harness_path": str(harness_path), "fixture_source_path": str(fixture_copy),
        "prefix_path": str(prefix_path), "argument": None if argument is None else str(concrete_argument),
        "suffix_signature": suffix["signature"], "suffix_context": suffix,
        "expected_test_signatures": ["check_prefix()", "check_goal(uint256)"] +
                                    ([] if argument is None else ["test_replay()"]),
        "build": BUILD, "fixture_source_sha256": file_hash(fixture_copy),
        "foundry_sha256": file_hash(config_path), "harness_sha256": file_hash(harness_path),
        "prefix_sha256": file_hash(prefix_path),
        "address_mapping": {last["to"]: "fresh builtin fixture instance"},
    }
    write_json(manifest_path, manifest)
    return manifest
