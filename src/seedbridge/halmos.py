"""Fail-closed interpretation of the pinned Halmos 0.3.3 output format."""

import json
import math
from pathlib import Path
import re
import shlex
import tempfile

from .config import UINT256_MAX
from .doctor import tool_environment
from .process import run_command


EXPECTED_TESTS = {"check_prefix()", "check_goal(uint256)"}
SYMBOL = re.compile(r"p_arg0_uint256_[0-9a-f]+_[0-9]+\Z")


def _result(status: str, reason: str, **extra: object) -> dict:
    return {"status": status, "reason": reason, "candidates": [], **extra}


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def parse_result(document: object, expected_test: str) -> dict:
    if expected_test not in EXPECTED_TESTS:
        raise ValueError("only the generated prefix and goal tests are supported")
    if not isinstance(document, dict) or type(document.get("exitcode")) is not int:
        return _result("result_mismatch", "missing top-level integer exitcode")
    contracts = document.get("test_results")
    if not isinstance(contracts, dict) or len(contracts) != 1:
        return _result("result_mismatch", "expected exactly one selected contract")
    contract, tests = next(iter(contracts.items()))
    if not isinstance(contract, str) or not contract.endswith(":BridgeHarnessTest"):
        return _result("result_mismatch", "unexpected contract identity")
    if not isinstance(tests, list) or len(tests) != 1 or not isinstance(tests[0], dict):
        return _result("result_mismatch", "expected exactly one completed test")
    test = tests[0]
    if test.get("name") != expected_test or type(test.get("exitcode")) is not int:
        return _result("result_mismatch", "unexpected test identity or exitcode")
    exitcode = test["exitcode"]
    if exitcode not in range(6) or document["exitcode"] != (0 if exitcode == 0 else 1):
        return _result("result_mismatch", "inconsistent top-level and per-test outcomes")
    models = test.get("models")
    count = test.get("num_models")
    paths = test.get("num_paths")
    bounds = test.get("num_bounded_loops")
    timing = test.get("time")
    if (not isinstance(models, list) or not _nonnegative_int(count) or count != len(models)
            or not isinstance(paths, list) or len(paths) != 3
            or not all(_nonnegative_int(item) for item in paths)
            or paths[1] > paths[0] or paths[2] > paths[0]
            or not _nonnegative_int(bounds)
            or not isinstance(timing, list) or len(timing) != 3
            or any(type(item) not in (int, float) or not math.isfinite(item) or item < 0
                   for item in timing)):
        return _result("result_mismatch", "missing or invalid full 0.3.3 result fields")
    details = {"halmos_exitcode": exitcode, "num_paths": paths,
               "num_bounded_loops": bounds, "test": expected_test}
    if exitcode != 1 and models:
        return _result("result_mismatch", "models require a counterexample outcome", **details)
    if exitcode in (2, 3, 4, 5):
        statuses = {2: "timeout", 3: "stuck", 4: "all_paths_reverted", 5: "tool_error"}
        return _result(statuses[exitcode], "Halmos did not complete this query successfully", **details)
    if exitcode == 0:
        if expected_test == "check_prefix()":
            status = "prefix_confirmed" if bounds == 0 and paths[1] > 0 and paths[2] == 0 else "prefix_incomplete"
            return _result(status, "prefix checks completed in the configured model", **details)
        return _result("no_witness_within_bounds", "no candidate was produced; this is not an unreachability proof", **details)
    if expected_test == "check_prefix()":
        return _result("prefix_mismatch", "the recorded prefix observations were not confirmed", **details)
    if not models:
        return _result("decode_error", "counterexample outcome contains no model", **details)
    candidates = []
    invalid = 0
    for candidate in models:
        if not isinstance(candidate, dict) or type(candidate.get("is_valid")) is not bool:
            return _result("decode_error", "malformed PotentialModel", **details)
        if candidate["is_valid"] is False:
            invalid += 1
            continue
        variables = candidate.get("model")
        if not isinstance(variables, dict) or len(variables) != 1:
            return _result("decode_error", "expected exactly one typed arg0 assignment", **details)
        name, variable = next(iter(variables.items()))
        if (not isinstance(name, str) or not SYMBOL.fullmatch(name)
                or not isinstance(variable, dict)
                or variable.get("full_name") != name
                or variable.get("variable_name") != "arg0"
                or variable.get("solidity_type") != "uint256"
                or variable.get("smt_type") != "BitVec 256"
                or type(variable.get("size_bits")) is not int or variable["size_bits"] != 256
                or type(variable.get("value")) is not int
                or not 0 <= variable["value"] <= UINT256_MAX):
            return _result("decode_error", "invalid typed uint256 arg0 model", **details)
        value = str(variable["value"])
        if value not in candidates:
            candidates.append(value)
    if not candidates:
        return _result("invalid_model", "all candidate models were marked potentially invalid", invalid_models=invalid, **details)
    return _result("candidate", "typed candidates require independent concrete replay",
                   candidates=candidates, invalid_models=invalid, **details)


def run_halmos(project: Path, expected_test: str, output_dir: Path, timeout: float,
               solver: str, executable: str = "halmos") -> dict:
    if expected_test not in EXPECTED_TESTS:
        raise ValueError("unsupported generated test signature")
    project = Path(project).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="halmos-", dir=output_dir))
    output_file = run_dir / "result.json"
    log_path = run_dir / "command.log"
    command = [executable, "--root", str(project), "--contract", "BridgeHarnessTest",
               "--match-test", "^" + re.escape(expected_test) + "$",
               "--json-output", str(output_file), "--no-status", "--solver-threads", "1",
               "--solver-command", shlex.quote(str(Path(solver).resolve())),
               "--solver-timeout-assertion", "10s", "--width", "0", "--depth", "0"]
    invocation = run_command(command, cwd=project, log_path=log_path,
                             timeout=timeout, env=tool_environment())
    metadata = {"command": command, "command_result": invocation.to_dict(),
                "output_path": str(output_file), "log_path": str(log_path),
                "run_directory": str(run_dir), "expected_test": expected_test}
    if invocation.timed_out:
        return {**_result("timeout", "external whole-process deadline reached"), **metadata}
    if not output_file.is_file():
        return {**_result("tool_error", "Halmos produced no fresh JSON result"), **metadata}
    try:
        document = json.loads(output_file.read_text())
    except (OSError, ValueError) as error:
        return {**_result("tool_error", f"cannot read fresh Halmos JSON: {error}"), **metadata}
    parsed = parse_result(document, expected_test)
    if isinstance(document, dict) and document.get("exitcode") != invocation.returncode:
        parsed = _result("result_mismatch", "process and JSON exitcodes disagree")
    log = log_path.read_text()
    incomplete = ("incomplete execution due to the specified limit" in log or
                  "paths have not been fully explored" in log)
    if incomplete and parsed["status"] == "prefix_confirmed":
        parsed = _result("prefix_incomplete", "Halmos logged an exploration bound")
    return {**parsed, **metadata, "incomplete_warning": incomplete}
