"""Generate one-instance symbolic and concrete harnesses for ordered suffixes."""

from __future__ import annotations

from pathlib import Path
import shutil

from .config import get_scenario
from .harness import BUILD, _normalize_prefix, _prefix_lines, _sol_address
from .io import file_hash, write_json
from .safety import SOLIDITY_EXPRESSIONS
from .suffix import SuffixPlan, make_plan, prefix_identity
from .trace import validate_prefix


STEP_EVENT = "BridgeStep(uint256,bool,uint256,uint256,uint256,bool,bool,uint256,uint256)"


def _context(call: dict) -> str:
    sender = _sol_address(call["actor"])
    return (f'        vm.roll({call["actual_block"]});\n'
            f'        vm.warp({call["actual_timestamp"]});\n'
            f"        vm.prank({sender}, {sender});")


def _symbolic_call(call: dict) -> str:
    if call["variable"] is None:
        return f'hex"{call["selector"][2:]}"'
    return f'abi.encodeWithSelector(bytes4({call["selector"]}), {call["variable"]})'


def _concrete_call(call: dict) -> str:
    if call["argument"] is None:
        return f'hex"{call["selector"][2:]}"'
    return f'abi.encodeWithSelector(bytes4({call["selector"]}), uint256({call["argument"]}))'


def _suffix_lines(calls: list[dict], *, symbolic: bool,
                  expect_violation: bool = True) -> str:
    lines = []
    for index, call in enumerate(calls):
        payload = _symbolic_call(call) if symbolic else _concrete_call(call)
        lines.extend(["        {", _context(call),
                      f"        (bool ok,) = address(target).call({payload});"])
        if symbolic:
            lines.extend([f'        require(ok, "SUFFIX_REVERT_{index}");',
                          f'        require(target.invariantHolds(), "SUFFIX_STRUCTURE_{index}");',
                          f'        require(_propertyConsistent(), "SUFFIX_OBSERVER_{index}");'])
            if index < len(calls) - 1:
                lines.append(f'        require(target.propertyHolds(), "EARLY_VIOLATION_{index}");')
            else:
                lines.append("        assert(target.propertyHolds());")
        else:
            if expect_violation:
                lines.append("        assert(ok);")
            lines.extend(["        assert(target.invariantHolds());",
                          "        assert(_propertyConsistent());",
                          "        (uint256 p, uint256 q, uint256 r, bool violation) = target.observe();",
                          "        bool holds = target.propertyHolds();",
                          f"        emit BridgeStep({index}, ok, p, q, r, violation, holds, block.number, block.timestamp);"])
            if expect_violation and index == len(calls) - 1:
                lines.append("        assert(!holds && violation);")
            else:
                lines.append("        assert(holds && !violation);")
        lines.append("        }")
    return "\n".join(lines)


def generate_suffix_harness(fixture_id: str, prefix: dict, plan: SuffixPlan,
                            destination: Path, *, assignments: dict[str, str | int] | None = None,
                            expect_violation: bool = True) -> dict:
    scenario = get_scenario(fixture_id)
    if scenario.mode != "safety" or not scenario.stage5_suffix_calls:
        raise ValueError("multi-call harness requires a declared local safety fixture")
    validate_prefix(prefix, fixture_id=fixture_id, require_ready=False)
    normalized = _normalize_prefix(fixture_id, prefix, require_ready=False)
    source_prefix_id = prefix_identity(fixture_id, prefix)
    verified = make_plan(fixture_id, {**prefix, "stage5_prefix_id": source_prefix_id},
                         tuple(call.signature for call in plan.calls))
    if (plan.fixture_id != fixture_id or plan.prefix_id != source_prefix_id
            or plan.query_id != verified.query_id or plan.calls != verified.calls):
        raise ValueError("suffix plan differs from its traced prefix or declared calls")
    if assignments is not None and set(assignments) != set(plan.variables):
        raise ValueError("concrete assignments do not cover all symbolic variables")
    destination = Path(destination).resolve()
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError("suffix harness destination must be new or empty")
    concrete_calls = None if assignments is None else plan.concrete_calls(assignments)
    plan_calls = [call.to_dict() for call in plan.calls]
    expression = SOLIDITY_EXPRESSIONS[scenario.property_id]
    last = normalized["steps"][-1]
    deploy_line = ""
    if "deployer" in normalized:
        deployer = _sol_address(normalized["deployer"])
        deploy_line = f"        vm.prank({deployer}, {deployer});\n"
    arguments = ", ".join(f"uint256 {variable}" for variable in plan.variables)
    concrete_test = ""
    if concrete_calls is not None:
        concrete_test = f"""
    function test_replay() external {{
        _prefixGuard();
        assert(target.propertyHolds() && _propertyConsistent());
{_suffix_lines(concrete_calls, symbolic=False, expect_violation=expect_violation)}
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

contract BridgeHarnessTest {{
    Vm private constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    {scenario.contract} private target;
    event BridgeStep(uint256 index, bool success, uint256 p, uint256 q, uint256 r,
                     bool violation, bool propertyHolds, uint256 blockNumber, uint256 timestamp);

    function setUp() public {{
{deploy_line}        target = new {scenario.contract}();
    }}

    function _matches(uint256 a, uint256 b, uint256 c, bool d) internal view returns (bool) {{
        (uint256 p, uint256 q, uint256 r, bool s) = target.observe();
        return p == a && q == b && r == c && s == d;
    }}

    function _propertyConsistent() internal view returns (bool) {{
        (uint256 p, uint256 q, uint256 r, bool violation) = target.observe();
        bool computed = {expression};
        return target.propertyHolds() == computed && violation == !computed;
    }}

    function check_prefix() external {{
{_prefix_lines(normalized["steps"], True, True)}
    }}

    function _prefixGuard() internal {{
{_prefix_lines(normalized["steps"], False, True)}
    }}

    function {plan.test_signature.replace('check_suffix(', 'check_suffix(').split('(')[0]}({arguments}) external {{
        _prefixGuard();
        require(target.propertyHolds() && _propertyConsistent(), "PREFIX_PROPERTY");
{_suffix_lines(plan_calls, symbolic=True)}
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
    plan_path = destination / "suffix-plan.json"
    write_json(plan_path, plan.to_dict())
    manifest_path = destination / "manifest.json"
    manifest = {
        "schema_version": 2, "fixture_id": fixture_id, "mode": "safety",
        "expected_violation": expect_violation if assignments is not None else None,
        "project_path": str(destination), "manifest_path": str(manifest_path),
        "harness_path": str(harness_path), "fixture_source_path": str(fixture_copy),
        "prefix_path": str(prefix_path), "plan_path": str(plan_path),
        "source_native_path": prefix["native_path"],
        "source_native_digest": prefix["native_digest"],
        "suffix_calls": concrete_calls if concrete_calls is not None else plan_calls,
        "assignments": None if assignments is None else {key: str(value) for key, value in assignments.items()},
        "expected_test_signatures": ["check_prefix()", plan.test_signature] +
                                    ([] if assignments is None else ["test_replay()"]),
        "build": BUILD, "fixture_source_sha256": file_hash(fixture_copy),
        "foundry_sha256": file_hash(config_path), "harness_sha256": file_hash(harness_path),
        "prefix_sha256": file_hash(prefix_path), "plan_sha256": file_hash(plan_path),
        "address_mapping": {last["to"]: "fresh builtin fixture instance"},
    }
    write_json(manifest_path, manifest)
    return manifest
