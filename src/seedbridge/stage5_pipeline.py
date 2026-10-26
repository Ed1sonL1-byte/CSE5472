"""Real Medusa → joint Halmos → fresh Foundry → native Medusa mechanism runs."""

from __future__ import annotations

from pathlib import Path
import time

from .build import assert_medusa_build, assert_same_target, build_manifest
from .config import RunConfig, get_scenario
from .doctor import inspect_toolchain
from .halmos import run_halmos
from .io import file_hash, read_json, write_json
from .medusa import build_fixture, codec, observe
from .multi_harness import generate_suffix_harness
from .process import EvidenceMismatchError, ToolExecutionError
from .replay import concrete_replay_suffix
from .stage5_replay import validate_native_suffix
from .suffix import enumerate_plans, make_plan, select_stage5_prefixes


def _compact_native(value: dict, observation: dict) -> dict:
    return {key: result for key, result in value.items() if key != "steps"} | {
        "observation_file": observation["output_path"],
        "states": [{"index": index, "status": step["status"],
                    "observe": step["observe"],
                    "property_holds": step["property_holds"],
                    "state_root_before_observer": step["state_root_before_observer"],
                    "state_root_after_observer": step["state_root_after_observer"]}
                   for index, step in enumerate(value["steps"])],
    }


def _same_calls(left: list[dict], right: list[dict]) -> bool:
    keys = ("from", "to", "calldata", "value", "actual_block", "actual_timestamp")
    return len(left) == len(right) and all(
        all(str(a.get(key)).lower() == str(b.get(key)).lower() for key in keys)
        for a, b in zip(left, right))


def run_stage5_mechanism(config: RunConfig, output: Path,
                         *, suffix_length: int = 2) -> dict:
    scenario = get_scenario(config.fixture_id)
    if scenario.mode != "safety" or not scenario.stage5_suffix_calls:
        raise ValueError("Stage 5 mechanism requires one of the declared safety fixtures")
    if suffix_length not in (1, 2):
        raise ValueError("suffix length must be one or two")
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("mechanism output must be a new directory")
    output.mkdir(parents=True)
    report = {"schema_version": 1, "fixture_id": config.fixture_id,
              "repaired_fixture_id": scenario.stage5_repaired_fixture,
              "suffix_length": suffix_length, "seed": config.seed,
              "warmup_tests": config.warmup_tests, "status": "running",
              "prefixes": [], "prefix_rejections": [], "attempts": []}
    started = time.monotonic()
    try:
        toolchain = inspect_toolchain()
        if not toolchain["ok"]:
            raise ToolExecutionError("Stage 5 toolchain preflight failed", status="tool_error")
        report["toolchain"] = toolchain
        build_fixture(config.fixture_id, output / "build", config.process_timeout)
        baseline = build_manifest(scenario.root, scenario.contract, output / "build-manifest",
                                  config.process_timeout)
        warmup = observe(config.fixture_id, output / "warmup", seed=config.seed,
                         tests=config.warmup_tests, timeout=config.process_timeout,
                         max_steps=5)
        assert_medusa_build(baseline, warmup)
        report["warmup"] = {"record": warmup["output_path"],
                            "sequence_count": len(warmup["sequences"]),
                            "property_violation_seen": any(
                                step.get("property_holds") is False
                                for sequence in warmup["sequences"]
                                for step in sequence.get("steps", []))}
        prefixes, rejected = select_stage5_prefixes(
            warmup, config.fixture_id, config.max_prefixes)
        report["prefixes"] = [{"prefix_id": item["stage5_prefix_id"],
                               "native_path": item["native_path"],
                               "native_digest": item["native_digest"],
                               "steps": item["steps"]} for item in prefixes]
        report["prefix_rejections"] = rejected
        if not prefixes:
            report["status"] = "no_eligible_prefix"
            return report
        deadline = time.monotonic() + config.total_solve_timeout
        solver = toolchain["tools"]["z3"]["path"]
        executable = toolchain["tools"]["halmos"]["path"]
        warmup_hashes = {sequence["medusa_hash"] for sequence in warmup["sequences"]}
        for prefix_index, prefix in enumerate(prefixes):
            plans, decisions = enumerate_plans(config.fixture_id, prefix, suffix_length)
            report.setdefault("planner", []).append({
                "prefix_id": prefix["stage5_prefix_id"], "decisions": decisions})
            for plan_index, plan in enumerate(plans):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    report["status"] = "solve_budget_exhausted"
                    return report
                directory = output / f"prefix-{prefix_index:02d}-plan-{plan_index:02d}"
                attempt = {"query_id": plan.query_id, "plan": plan.to_dict(),
                           "source_prefix_id": prefix["stage5_prefix_id"]}
                report["attempts"].append(attempt)
                generated = generate_suffix_harness(
                    config.fixture_id, prefix, plan, directory / "symbolic")
                project = Path(generated["project_path"])
                attempt["harness"] = generated["manifest_path"]
                prefix_check = run_halmos(project, "check_prefix()", directory / "prefix-check",
                                          min(config.process_timeout, remaining), solver, executable)
                attempt["prefix_check"] = prefix_check
                if prefix_check["status"] != "prefix_confirmed":
                    attempt["status"] = prefix_check["status"]
                    continue
                generated_build = build_manifest(project, scenario.contract,
                                                 directory / "symbolic-build",
                                                 config.process_timeout)
                assert_same_target(baseline, generated_build)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    report["status"] = "solve_budget_exhausted"
                    return report
                solved = run_halmos(project, plan.test_signature, directory / "solve",
                                    min(config.process_timeout, remaining), solver, executable)
                attempt["solve"] = solved
                if solved["status"] != "candidate":
                    attempt["status"] = solved["status"]
                    continue
                for candidate_index, assignments in enumerate(solved["candidates"]):
                    candidate_dir = directory / f"candidate-{candidate_index:02d}"
                    candidate = {"assignments": assignments, "model_file": solved["output_path"],
                                 "plan": plan.to_dict(), "status": "pending"}
                    attempt.setdefault("candidates", []).append(candidate)
                    concrete = generate_suffix_harness(
                        config.fixture_id, prefix, plan, candidate_dir / "flawed-foundry",
                        assignments=assignments)
                    replay = concrete_replay_suffix(
                        Path(concrete["project_path"]), candidate_dir / "flawed-replay",
                        config.process_timeout)
                    candidate["flawed_replay"] = replay
                    if replay["status"] != "violation_confirmed":
                        candidate["status"] = replay["status"]
                        continue
                    concrete_build = build_manifest(
                        Path(concrete["project_path"]), scenario.contract,
                        candidate_dir / "flawed-build", config.process_timeout)
                    assert_same_target(baseline, concrete_build)
                    corpus = candidate_dir / "flawed-native/corpus"
                    native_path = corpus / "call_sequences/candidate.json"
                    plan_path = candidate_dir / "flawed-native/suffix-plan.json"
                    write_json(plan_path, {"calls": plan.concrete_calls(assignments)})
                    codec(config.fixture_id, "encode-suffix", Path(prefix["native_path"]),
                          native_path, config.process_timeout, plan=plan_path)
                    decoded_path = candidate_dir / "flawed-native/decoded.json"
                    codec(config.fixture_id, "decode-corpus", native_path,
                          decoded_path, config.process_timeout)
                    decoded = read_json(decoded_path)
                    if decoded["medusa_hash"] in warmup_hashes:
                        candidate["status"] = "duplicate_warmup_sequence"
                        continue
                    native_observation = observe(
                        config.fixture_id, candidate_dir / "flawed-native/observed",
                        seed=config.seed, tests=1, timeout=config.process_timeout,
                        corpus=corpus, max_steps=5)
                    native = validate_native_suffix(
                        config.fixture_id, native_observation, decoded, prefix, plan,
                        assignments, replay["steps"])
                    candidate["flawed_native"] = _compact_native(native, native_observation)
                    candidate["flawed_native_file"] = str(native_path)
                    repaired_id = scenario.stage5_repaired_fixture
                    if repaired_id is None:
                        raise ValueError("Stage 5 case lacks a repair")
                    repaired_scenario = get_scenario(repaired_id)
                    repaired_prefix = {key: value for key, value in prefix.items()
                                       if key != "stage5_prefix_id"}
                    repaired_plan = make_plan(repaired_id, repaired_prefix,
                                              tuple(call.signature for call in plan.calls))
                    repaired_harness = generate_suffix_harness(
                        repaired_id, repaired_prefix, repaired_plan,
                        candidate_dir / "repaired-foundry", assignments=assignments,
                        expect_violation=False)
                    repaired_replay = concrete_replay_suffix(
                        Path(repaired_harness["project_path"]),
                        candidate_dir / "repaired-replay", config.process_timeout)
                    candidate["repaired_replay"] = repaired_replay
                    if repaired_replay["status"] != "property_preserved":
                        candidate["status"] = "repaired_regression_failure"
                        continue
                    repaired_corpus = candidate_dir / "repaired-native/corpus"
                    repaired_native_path = repaired_corpus / "call_sequences/candidate.json"
                    repaired_plan_path = candidate_dir / "repaired-native/suffix-plan.json"
                    write_json(repaired_plan_path,
                               {"calls": repaired_plan.concrete_calls(assignments)})
                    codec(repaired_id, "encode-suffix", Path(prefix["native_path"]),
                          repaired_native_path, config.process_timeout, plan=repaired_plan_path)
                    repaired_decoded_path = candidate_dir / "repaired-native/decoded.json"
                    codec(repaired_id, "decode-corpus", repaired_native_path,
                          repaired_decoded_path, config.process_timeout)
                    repaired_observation = observe(
                        repaired_id, candidate_dir / "repaired-native/observed",
                        seed=config.seed, tests=1, timeout=config.process_timeout,
                        corpus=repaired_corpus, max_steps=5)
                    repaired_native = validate_native_suffix(
                        repaired_id, repaired_observation, read_json(repaired_decoded_path),
                        prefix, repaired_plan, assignments, repaired_replay["steps"],
                        repaired=True)
                    if not _same_calls(native["steps"], repaired_native["steps"]):
                        raise EvidenceMismatchError("flawed and repaired native calls differ",
                                                    status="replay_mismatch")
                    candidate["repaired_native"] = _compact_native(
                        repaired_native, repaired_observation)
                    candidate["repaired_native_file"] = str(repaired_native_path)
                    candidate["status"] = "safety_confirmed"
                    report["status"] = "safety_confirmed"
                    report["confirmed"] = {"query_id": plan.query_id,
                                           "prefix_id": prefix["stage5_prefix_id"],
                                           "assignments": assignments,
                                           "full_sequence_length": len(native["steps"]),
                                           "first_violation_call_index": native["first_violation_call_index"],
                                           "classification": native["classification"],
                                           "two_step_only": native["two_step_only"],
                                           "flawed_native_record": native_observation["output_path"],
                                           "repaired_native_record": repaired_observation["output_path"],
                                           "flawed_foundry_record": replay["command_result"]["log_path"],
                                           "repaired_foundry_record": repaired_replay["command_result"]["log_path"]}
                    return report
                attempt["status"] = "no_candidate"
        report["status"] = "no_candidate"
        return report
    except ToolExecutionError as error:
        report["status"] = error.status
        report["error"] = str(error)
        return report
    except EvidenceMismatchError as error:
        report["status"] = error.status
        report["error"] = str(error)
        return report
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
        report["status"] = "tool_error"
        report["error"] = f"{type(error).__name__}: {error}"
        return report
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        write_json(output / "report.json", report)
