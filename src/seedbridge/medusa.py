"""Invoke the fixed Go adapter; never reimplement its native corpus codec."""

from pathlib import Path

from .compact import read_compact_events
from .config import ROOT, get_scenario
from .doctor import tool_environment
from .io import read_json
from .process import EvidenceMismatchError, ToolExecutionError, run_command


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


def build_fixture(fixture_id: str, directory: Path, timeout: float,
                  project: Path | None = None) -> dict:
    scenario = get_scenario(fixture_id)
    result = run_command(["forge", "build", "--ast", "--extra-output", "storageLayout", "metadata"],
                         cwd=Path(project or scenario.root), log_path=directory / "forge-build.log",
                         timeout=timeout, env=tool_environment())
    if result.timed_out or result.returncode:
        status = "timeout" if result.timed_out else "tool_error"
        raise ToolExecutionError(f"Fixture build failed: {result.log_path}", status=status)
    return result.to_dict()


def observe(fixture_id: str, directory: Path, *, seed: int, tests: int,
            timeout: float, corpus: Path | None = None, enabled: bool = True,
            project: Path | None = None) -> dict:
    output = directory / "observation.json"
    if output.exists():
        raise ValueError("Observation output must be fresh")
    arguments = ["run-observed", "--fixture", fixture_id,
                      "--corpus-dir", str(corpus or directory / "corpus"),
                      "--output", str(output), "--seed", str(seed),
                      "--tests", str(tests), "--max-steps", "3" if corpus is None else "4",
                      "--timeout", f"{min(timeout, 300)}s", f"--observe={str(enabled).lower()}"]
    if project is not None:
        arguments.extend(["--project-dir", str(Path(project).resolve())])
    command = invoke(arguments, directory, timeout)
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


def campaign(fixture_id: str, directory: Path, *, seed: int, tests: int,
             fuzz_timeout: float, process_timeout: float, corpus: Path,
             observe_state: bool = True, record_lineage: bool = True,
             compact: bool = False, flush_delay: float = 0.0,
             project: Path | None = None) -> dict:
    """Run the patched native continuation mode and retain valid partial timeout evidence."""
    if compact and not record_lineage:
        raise ValueError("compact campaigns require lineage recording")
    if flush_delay < 0:
        raise ValueError("flush delay cannot be negative")
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / "campaign.json"
    lineage = directory / "lineage.jsonl"
    events = directory / "events.jsonl.gz"
    completion = directory / "completion.json"
    if (output.exists() or (record_lineage and not compact and lineage.exists())
            or (compact and (events.exists() or completion.exists()))):
        raise ValueError("Campaign outputs must be fresh")
    arguments = [
        "run-campaign", "--fixture", fixture_id, "--corpus-dir", str(corpus),
        "--output", str(output), "--seed", str(seed), "--tests", str(tests),
        "--max-steps", "4", "--timeout", f"{fuzz_timeout:.6f}s",
        f"--observe={str(observe_state).lower()}",
        f"--record-lineage={str(record_lineage).lower()}",
    ]
    if record_lineage:
        if compact:
            arguments.extend([
                "--compact=true", "--event-output", str(events),
                "--completion-output", str(completion),
                "--flush-delay", f"{flush_delay:.6f}s",
            ])
        else:
            arguments.extend(["--lineage-output", str(lineage)])
    if project is not None:
        arguments.extend(["--project-dir", str(Path(project).resolve())])
    result = run_command([str(ROOT / ".bin/medusa-adapter"), *arguments], cwd=ROOT,
                         log_path=directory / "adapter.log", timeout=process_timeout,
                         env=tool_environment())
    if result.timed_out:
        raise ToolExecutionError("Medusa campaign exceeded its outer process deadline", status="timeout")
    if not output.is_file():
        raise ToolExecutionError("Medusa campaign produced no report", status="tool_error")
    observation = read_json(output)
    expected_schema = 3 if compact else 2
    if (observation.get("schema_version") != expected_schema or observation.get("medusa_version") != "v1.5.1"
            or observation.get("fixture") != fixture_id
            or observation.get("status") not in {"complete", "timeout", "tool_error"}
            or type(observation.get("completed_sequences")) is not int):
        raise RuntimeError("Adapter returned an incomplete or incompatible campaign report")
    if observation["status"] == "tool_error":
        detail = observation.get("error") or "no adapter error detail"
        raise ToolExecutionError(f"Medusa campaign failed: {detail}", status="tool_error")
    if result.returncode != 0 and observation["status"] != "timeout":
        raise ToolExecutionError("Medusa campaign failed", status="tool_error")
    if record_lineage and compact:
        decoded = read_compact_events(events, observation.get("compact_events", {}))
        observation["sequences"] = decoded["sequences"]
        observation["lineage"] = decoded["lineage"]
        observation["partial_sequences"] = decoded["partial_sequences"]
        if not completion.is_file():
            raise EvidenceMismatchError(
                "compact campaign produced no completion timing marker",
                status="evidence_error",
            )
        timing = read_json(completion)
        values = [timing.get(key) for key in (
            "search_started", "last_observed_event", "search_stopped",
            "event_stream_finished", "evidence_flush_finished",
        )]
        if (timing.get("schema_version") != 1
                or any(type(value) not in (int, float) or value < 0 for value in values)
                or not values[0] <= values[2] <= values[3] <= values[4]
                or not (values[1] == 0 or values[0] <= values[1] <= values[2])):
            raise EvidenceMismatchError(
                "compact campaign timing marker is inconsistent",
                status="evidence_error",
            )
        observation["completion_timing"] = timing
    elif record_lineage:
        if not lineage.is_file() or len(observation.get("lineage", [])) != observation["completed_sequences"]:
            raise RuntimeError("Campaign lineage does not cover every completed sequence")
    if record_lineage and len(observation.get("lineage", [])) != observation["completed_sequences"]:
        raise RuntimeError("Campaign lineage does not cover every completed sequence")
    for sequence in observation.get("sequences", []):
        sequence["admitted"] = sequence.get("admitted_for_mutation", False)
        sequence["deployer"] = observation["deployment"]["deployer"]
        for step in sequence["steps"]:
            step["actual_block"] = str(step["block_number"])
            step["actual_timestamp"] = str(step["block_timestamp"])
    return {**observation, "command_result": result.to_dict(), "output_path": str(output)}


def codec(fixture_id: str, operation: str, source: Path, output: Path,
          timeout: float, argument: str | None = None,
          project: Path | None = None) -> dict:
    arguments = [operation, "--fixture", fixture_id, "--input", str(source), "--output", str(output)]
    if argument is not None:
        arguments.extend(["--argument", argument])
    if project is not None:
        arguments.extend(["--project-dir", str(Path(project).resolve())])
    return invoke(arguments, output.parent, timeout)


def codec_batch(fixture_id: str, plan: Path, output: Path, timeout: float,
                project: Path | None = None) -> dict:
    arguments = ["encode-batch", "--fixture", fixture_id, "--input", str(plan),
                 "--output", str(output)]
    if project is not None:
        arguments.extend(["--project-dir", str(Path(project).resolve())])
    invoke(arguments, output.parent, timeout)
    document = read_json(output)
    if (document.get("schema_version") != 1 or document.get("fixture") != fixture_id
            or not isinstance(document.get("entries"), list)):
        raise RuntimeError("Adapter returned an incompatible codec batch manifest")
    return document
