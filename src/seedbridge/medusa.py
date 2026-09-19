"""Invoke the fixed Go adapter; never reimplement its native corpus codec."""

from pathlib import Path

from .config import ROOT, get_scenario
from .doctor import tool_environment
from .io import read_json
from .process import ToolExecutionError, run_command


def invoke(arguments: list[str], directory: Path, timeout: float) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    result = run_command([str(ROOT / ".bin/medusa-adapter"), *arguments], cwd=ROOT,
                         log_path=directory / "adapter.log", timeout=timeout,
                         env=tool_environment())
    if result.timed_out or result.returncode != 0:
        status = "timeout" if result.timed_out else "tool_error"
        raise ToolExecutionError(
            f"Medusa adapter {'timed out' if result.timed_out else 'failed'}: {result.log_path}",
            status=status,
        )
    return result.to_dict()


def build_fixture(fixture_id: str, directory: Path, timeout: float) -> dict:
    scenario = get_scenario(fixture_id)
    result = run_command(["forge", "build", "--ast", "--extra-output", "storageLayout", "metadata"],
                         cwd=scenario.root, log_path=directory / "forge-build.log",
                         timeout=timeout, env=tool_environment())
    if result.timed_out or result.returncode:
        status = "timeout" if result.timed_out else "tool_error"
        raise ToolExecutionError(f"Fixture build failed: {result.log_path}", status=status)
    return result.to_dict()


def observe(fixture_id: str, directory: Path, *, seed: int, tests: int,
            timeout: float, corpus: Path | None = None, enabled: bool = True) -> dict:
    output = directory / "observation.json"
    if output.exists():
        raise ValueError("Observation output must be fresh")
    command = invoke(["run-observed", "--fixture", fixture_id,
                      "--corpus-dir", str(corpus or directory / "corpus"),
                      "--output", str(output), "--seed", str(seed),
                      "--tests", str(tests), "--max-steps", "3" if corpus is None else "4",
                      "--timeout", f"{min(timeout, 300)}s", f"--observe={str(enabled).lower()}"],
                     directory, timeout)
    if not output.exists():
        raise RuntimeError("Adapter did not produce the expected observation")
    observation = read_json(output)
    if (observation.get("schema_version") != 1 or observation.get("medusa_version") != "v1.5.1"
            or observation.get("fixture") != fixture_id or observation.get("status") != "complete"
            or observation.get("timed_out") is not False):
        raise RuntimeError("Adapter returned an incomplete or incompatible observation")
    # Retain native fields and raw JSON; expose one versioned interface to the harness.
    for sequence in observation.get("sequences", []):
        sequence["admitted"] = sequence.get("admitted_for_mutation", False)
        sequence["deployer"] = observation["deployment"]["deployer"]
        for step in sequence["steps"]:
            step["actual_block"] = str(step["block_number"])
            step["actual_timestamp"] = str(step["block_timestamp"])
    return {**observation, "command_result": command, "output_path": str(output)}


def codec(fixture_id: str, operation: str, source: Path, output: Path,
          timeout: float, argument: str | None = None) -> dict:
    arguments = [operation, "--fixture", fixture_id, "--input", str(source), "--output", str(output)]
    if argument is not None:
        arguments.extend(["--argument", argument])
    return invoke(arguments, output.parent, timeout)
