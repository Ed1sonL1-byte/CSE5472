"""Single-batch Stage 1 orchestration for the repository's two teaching fixtures."""

from dataclasses import asdict
from pathlib import Path
import time
import uuid

from .build import assert_medusa_build, assert_same_target, build_manifest
from .config import ROOT, RunConfig, get_scenario
from .doctor import inspect_toolchain
from .halmos import run_halmos
from .harness import generate_harness
from .io import file_hash, read_json, write_json
from .medusa import build_fixture, codec, observe
from .process import EvidenceMismatchError, ToolExecutionError
from .replay import concrete_replay, match_native_execution
from .report import save_report
from .trace import select_prefixes


def _finish_stage(report: dict, name: str, started: float) -> float:
    elapsed = time.monotonic() - started
    stages = report.setdefault("stage_elapsed_seconds", {})
    stages[name] = stages.get(name, 0.0) + elapsed
    return elapsed


def observer_control(observed: dict, unobserved: dict, expected_steps: list[dict]) -> dict:
    def completed(run: dict) -> list[dict]:
        return [sequence for sequence in run["sequences"] if sequence.get("is_complete_sequence")]
    left, right = completed(observed), completed(unobserved)
    if len(left) != 1 or len(right) != 1:
        return {"status": "mismatch", "reason": "control did not execute exactly one sequence"}
    a, b = left[0], right[0]
    if len(a["steps"]) != len(expected_steps) or len(b["steps"]) != len(expected_steps):
        return {"status": "mismatch", "reason": "control sequence length changed"}
    fields = ("from", "to", "calldata", "value", "status", "gas_used", "return_data",
              "actual_block", "actual_timestamp", "state_root_after_observer",
              "coverage_branches", "cumulative_coverage_branches",
              "coverage_digest_sha256", "cumulative_coverage_digest_sha256")
    for enabled, disabled in zip(a["steps"], b["steps"]):
        if not enabled.get("observer_state_unchanged"):
            return {"status": "mismatch", "reason": "observer changed transaction state"}
        if any(field not in enabled or field not in disabled or enabled[field] != disabled[field] for field in fields):
            return {"status": "mismatch", "reason": "observer altered execution or feedback"}
    if not a.get("admitted") or not b.get("admitted"):
        return {"status": "mismatch", "reason": "control did not confirm admission on both runs"}
    if observed.get("coverage_branches", 0) <= 0 or observed.get("coverage_branches") != unobserved.get("coverage_branches"):
        return {"status": "unverified", "reason": "nonempty native coverage evidence is required"}
    if (not observed.get("coverage_digest_sha256") or
            observed["coverage_digest_sha256"] != unobserved.get("coverage_digest_sha256")):
        return {"status": "mismatch", "reason": "native coverage digests differ"}
    return {"status": "passed", "compared_fields": list(fields),
            "enabled_observation": observed["output_path"], "disabled_observation": unobserved["output_path"]}


def run_pipeline(config: RunConfig, output: Path | None = None) -> tuple[dict, Path]:
    directory = (output or ROOT / "runs" / f"{config.fixture_id}-{uuid.uuid4().hex[:12]}").resolve()
    directory.mkdir(parents=True, exist_ok=False)
    scenario_started = time.monotonic()
    scenario = get_scenario(config.fixture_id)
    report = {"schema_version": 1, "fixture_id": config.fixture_id, "config": asdict(config),
              "scenario_path": str(directory / "scenario.json"), "status": "incomplete",
              "attempts": [], "confirmed_count": 0, "stage_elapsed_seconds": {}}
    write_json(directory / "scenario.json", {
        "schema_version": 1,
        "scenario": scenario.to_dict(),
        "run_config": asdict(config),
    })
    _finish_stage(report, "s1_scenario_config", scenario_started)
    started = scenario_started
    try:
        _execute(config, directory, report)
    except ToolExecutionError as error:
        report["status"] = error.status
        report["error"] = f"{type(error).__name__}: {error}"
    except EvidenceMismatchError as error:
        report["status"] = error.status
        report["error"] = f"{type(error).__name__}: {error}"
    except (RuntimeError, ValueError, OSError, KeyError, TypeError) as error:
        report["status"] = "tool_error"
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        report_started = time.monotonic()
        save_report(directory, report)
        _finish_stage(report, "s6_report", report_started)
        save_report(directory, report)
    return report, directory


def _execute(config: RunConfig, directory: Path, report: dict) -> None:
    fixture = config.fixture_id
    scenario = get_scenario(fixture)
    timeout = config.process_timeout
    stage_started = time.monotonic()
    toolchain = inspect_toolchain()
    report["toolchain"] = toolchain
    write_json(directory / "toolchain.json", toolchain)
    if not toolchain["ok"]:
        raise RuntimeError("Toolchain preflight failed; run ./seedbridge doctor")
    report["build_command"] = build_fixture(fixture, directory / "build", timeout)
    build = build_manifest(scenario.root, scenario.contract, directory / "build", timeout)
    report["build"] = build
    _finish_stage(report, "s0_environment_build", stage_started)

    stage_started = time.monotonic()
    warmup = observe(fixture, directory / "warmup", seed=config.seed,
                     tests=config.warmup_tests, timeout=timeout)
    report["warmup"] = {key: value for key, value in warmup.items() if key != "sequences"}
    assert_medusa_build(build, warmup)
    _finish_stage(report, "s2_native_warmup", stage_started)

    stage_started = time.monotonic()
    prefixes, rejected = select_prefixes(warmup, config.max_prefixes)
    report["prefixes"] = prefixes
    write_json(directory / "prefix-selection.json", {"selected": prefixes, "rejected": rejected})
    _finish_stage(report, "s3_prefix_selection", stage_started)
    if not prefixes:
        report["status"] = "no_eligible_prefix"
        return

    # Verify native corpus round-trip and observer neutrality before invoking the solver.
    stage_started = time.monotonic()
    first = prefixes[0]
    on_corpus = directory / "roundtrip-on/corpus"
    on_native = on_corpus / "call_sequences/prefix.json"
    codec(fixture, "roundtrip", Path(first["native_path"]), on_native, timeout)
    on = observe(fixture, directory / "roundtrip-on", seed=config.seed, tests=1,
                 timeout=timeout, corpus=on_corpus)
    assert_medusa_build(build, on)
    matched = match_native_execution(on, first["steps"], first["steps"], require_goal=False)
    if matched is None:
        raise EvidenceMismatchError("Native round-trip did not preserve the selected prefix or admission")
    report["roundtrip"] = {"status": "passed", "source": first["native_path"],
                           "export_sha256": file_hash(on_native), "observation": on["output_path"],
                           "admission_evidence": matched["admission_evidence"]}
    off_corpus = directory / "roundtrip-off/corpus"
    codec(fixture, "roundtrip", Path(first["native_path"]), off_corpus / "call_sequences/prefix.json", timeout)
    off = observe(fixture, directory / "roundtrip-off", seed=config.seed, tests=1,
                  timeout=timeout, corpus=off_corpus, enabled=False)
    assert_medusa_build(build, off)
    report["observer_control"] = observer_control(on, off, first["steps"])
    if report["observer_control"]["status"] != "passed":
        raise EvidenceMismatchError("Observer neutrality control did not pass", status="observer_mismatch")
    _finish_stage(report, "s2_roundtrip_observer_control", stage_started)

    deadline = time.monotonic() + config.total_solve_timeout
    existing_hashes = {sequence["medusa_hash"] for sequence in warmup["sequences"]}
    solver = toolchain["tools"]["z3"]["path"]
    executable = toolchain["tools"]["halmos"]["path"]
    for index, prefix in enumerate(prefixes):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            report["status"] = "solve_budget_exhausted"
            return
        case_dir = directory / f"attempt-{index}"
        stage_started = time.monotonic()
        generated = generate_harness(fixture, prefix, case_dir / "symbolic")
        attempt = {"case_id": prefix["case_id"], "harness": generated,
                   "stage_elapsed_seconds": {}}
        report["attempts"].append(attempt)
        project = Path(generated["project_path"])
        prefix_result = run_halmos(project, "check_prefix()", case_dir / "prefix-check",
                                   min(timeout, remaining), solver, executable)
        attempt["prefix_check"] = prefix_result
        if prefix_result["status"] != "prefix_confirmed":
            attempt["stage_elapsed_seconds"]["s3_harness_prefix_replay"] = _finish_stage(
                report, "s3_harness_prefix_replay", stage_started)
            continue
        generated_build = build_manifest(project, scenario.contract, case_dir / "build", timeout)
        assert_same_target(build, generated_build)
        attempt["build"] = generated_build
        attempt["stage_elapsed_seconds"]["s3_harness_prefix_replay"] = _finish_stage(
            report, "s3_harness_prefix_replay", stage_started)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            report["status"] = "solve_budget_exhausted"
            return
        stage_started = time.monotonic()
        solved = run_halmos(project, "check_goal(uint256)", case_dir / "solve",
                           min(timeout, remaining), solver, executable)
        attempt["solve"] = solved
        attempt["stage_elapsed_seconds"]["s4_halmos_solve"] = _finish_stage(
            report, "s4_halmos_solve", stage_started)
        if solved["status"] != "candidate":
            continue
        # Both teaching predicates have one witness for any fixed ready-state prefix.
        argument = solved["candidates"][0]
        attempt["candidate"] = {"argument": argument, "type": "uint256", "name": "arg0",
                                "source_case": prefix["case_id"], "model_file": solved["output_path"]}
        write_json(case_dir / "candidate.json", attempt["candidate"])
        stage_started = time.monotonic()
        concrete = generate_harness(fixture, prefix, case_dir / "concrete", int(argument))
        replay = concrete_replay(Path(concrete["project_path"]), case_dir / "concrete-check", timeout)
        attempt["replay"] = replay
        if replay["status"] != "reachable_confirmed":
            attempt["stage_elapsed_seconds"]["s5_replay_reinsert"] = _finish_stage(
                report, "s5_replay_reinsert", stage_started)
            continue
        concrete_build = build_manifest(Path(concrete["project_path"]), scenario.contract,
                                        case_dir / "concrete-build", timeout)
        assert_same_target(build, concrete_build)
        attempt["concrete_build"] = concrete_build
        corpus = case_dir / "reinsert/corpus"
        native = corpus / "call_sequences/candidate.json"
        codec(fixture, "encode-candidate", Path(prefix["native_path"]), native, timeout, argument)
        decoded_path = case_dir / "candidate-decoded.json"
        codec(fixture, "decode-corpus", native, decoded_path, timeout)
        decoded = read_json(decoded_path)
        candidate_hash = decoded["medusa_hash"]
        novelty_path = case_dir / "novelty.json"
        novelty = {
            "status": "duplicate" if candidate_hash in existing_hashes else "new_sequence",
            "candidate_medusa_hash": candidate_hash,
            "warmup_medusa_hashes": sorted(existing_hashes),
            "compared_count": len(existing_hashes),
            "warmup_observation": warmup["output_path"],
        }
        write_json(novelty_path, novelty)
        attempt["novelty"] = {
            "status": novelty["status"],
            "candidate_medusa_hash": candidate_hash,
            "compared_count": len(existing_hashes),
            "evidence_path": str(novelty_path),
        }
        if novelty["status"] == "duplicate":
            attempt["admission"] = {"status": "duplicate"}
            attempt["stage_elapsed_seconds"]["s5_replay_reinsert"] = _finish_stage(
                report, "s5_replay_reinsert", stage_started)
            continue
        expected = decoded["steps"]
        for key in ("actual_block", "actual_timestamp"):
            expected[-1][key] = concrete["suffix_context"][key]
        restarted = observe(fixture, case_dir / "reinsert", seed=config.seed, tests=1,
                            timeout=timeout, corpus=corpus)
        assert_medusa_build(build, restarted)
        accepted = match_native_execution(restarted, expected, prefix["steps"], require_goal=True)
        if accepted is None:
            attempt["admission"] = {"status": "replay_mismatch", "observation": restarted["output_path"]}
            attempt["stage_elapsed_seconds"]["s5_replay_reinsert"] = _finish_stage(
                report, "s5_replay_reinsert", stage_started)
            continue
        attempt["admission"] = {"status": "admitted_for_mutation", "native_path": str(native),
                                "native_sha256": file_hash(native), "observation": restarted["output_path"],
                                "medusa_hash": accepted["medusa_hash"],
                                "replayed_by_medusa": accepted["replayed_by_medusa"],
                                "complete_sequence": accepted["is_complete_sequence"],
                                "executed_steps": len(accepted["steps"]),
                                "goal_before_suffix": prefix["steps"][-1]["observe"][-1],
                                "goal_after_suffix": accepted["steps"][-1]["observe"][-1],
                                "evidence": accepted["admission_evidence"],
                                "final_state": accepted["steps"][-1]["observe"]}
        attempt["stage_elapsed_seconds"]["s5_replay_reinsert"] = _finish_stage(
            report, "s5_replay_reinsert", stage_started)
        report["confirmed_count"] += 1
        report["status"] = "stage1_confirmed"
        return
    report["status"] = summarize_unsuccessful(report["attempts"])


def summarize_unsuccessful(attempts: list[dict]) -> str:
    states = {attempt[stage]["status"] for attempt in attempts
              for stage in ("prefix_check", "solve", "replay", "admission") if stage in attempt}
    if states & {"tool_error", "result_mismatch", "decode_error"}:
        return "tool_error"
    if "timeout" in states:
        return "timeout"
    if states & {"stuck", "prefix_incomplete", "all_paths_reverted"}:
        return "inconclusive"
    if states & {"prefix_mismatch", "replay_mismatch", "candidate_rejected", "invalid_model"}:
        return "validation_failed"
    if states <= {"prefix_confirmed", "no_witness_within_bounds"} and states:
        return "no_witness_within_bounds"
    return "no_confirmed_candidate"
