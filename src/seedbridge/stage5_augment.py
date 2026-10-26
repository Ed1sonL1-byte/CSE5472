"""One charged Stage 5 query and its independent confirmation records."""

from __future__ import annotations

from pathlib import Path
import time

from .build import assert_same_target, build_manifest
from .config import get_scenario
from .halmos import run_halmos
from .io import read_json, write_json
from .medusa import codec, observe
from .multi_harness import generate_suffix_harness
from .process import EvidenceMismatchError, ToolExecutionError
from .replay import concrete_replay_suffix
from .stage5_replay import validate_native_suffix
from .suffix import SuffixPlan, make_plan


def _remaining(deadline: float, cap: float) -> float:
    value = min(deadline - time.monotonic(), cap)
    if value < 0.15:
        raise ToolExecutionError("Stage 5 query has no remaining process budget",
                                 status="timeout")
    return value


def execute_query(fixture_id: str, prefix: dict, plan: SuffixPlan,
                  directory: Path, *, deadline: float, per_process_limit: float,
                  prefix_limit: float, solver_limit: float,
                  solver: str, halmos: str, baseline_build: dict,
                  seed: int, warmup_hashes: set[str]) -> dict:
    """Execute a planned query; all outputs remain on disk for independent review."""
    directory.mkdir(parents=True, exist_ok=False)
    scenario = get_scenario(fixture_id)
    row = {"schema_version": 1, "query_id": plan.query_id, "plan": plan.to_dict(),
           "prefix_id": prefix["stage5_prefix_id"], "status": "running",
           "candidates": [], "started_monotonic": time.monotonic()}
    try:
        generated = generate_suffix_harness(fixture_id, prefix, plan,
                                            directory / "symbolic")
        project = Path(generated["project_path"])
        row["harness_manifest"] = generated["manifest_path"]
        row["prefix_check"] = run_halmos(
            project, "check_prefix()", directory / "prefix-check",
            _remaining(deadline, prefix_limit), solver, halmos)
        if row["prefix_check"]["status"] != "prefix_confirmed":
            row["status"] = ("unsupported" if row["prefix_check"]["status"] == "stuck"
                             else row["prefix_check"]["status"])
            return row
        assert_same_target(baseline_build, build_manifest(
            project, scenario.contract, directory / "symbolic-build",
            _remaining(deadline, per_process_limit)))
        row["solve"] = run_halmos(
            project, plan.test_signature, directory / "solve",
            _remaining(deadline, solver_limit), solver, halmos)
        if row["solve"]["status"] != "candidate":
            row["status"] = row["solve"]["status"]
            return row
        for index, assignments in enumerate(row["solve"]["candidates"]):
            place = directory / f"candidate-{index:02d}"
            candidate = {"assignments": assignments,
                         "model_file": row["solve"]["output_path"],
                         "status": "pending"}
            row["candidates"].append(candidate)
            concrete = generate_suffix_harness(
                fixture_id, prefix, plan, place / "flawed-foundry",
                assignments=assignments)
            replay = concrete_replay_suffix(
                Path(concrete["project_path"]), place / "flawed-replay",
                _remaining(deadline, per_process_limit))
            candidate["foundry"] = replay
            if replay["status"] != "violation_confirmed":
                candidate["status"] = replay["status"]
                if replay["status"] in {"replay_mismatch", "result_mismatch", "tool_error"}:
                    row["status"] = replay["status"]
                    return row
                continue
            assert_same_target(baseline_build, build_manifest(
                Path(concrete["project_path"]), scenario.contract,
                place / "flawed-build", _remaining(deadline, per_process_limit)))
            corpus = place / "flawed-native/corpus"
            native_path = corpus / "call_sequences/candidate.json"
            plan_path = place / "flawed-native/suffix-plan.json"
            write_json(plan_path, {"calls": plan.concrete_calls(assignments)})
            codec(fixture_id, "encode-suffix", Path(prefix["native_path"]),
                  native_path, _remaining(deadline, per_process_limit), plan=plan_path)
            decoded_path = place / "flawed-native/decoded.json"
            codec(fixture_id, "decode-corpus", native_path, decoded_path,
                  _remaining(deadline, per_process_limit))
            decoded = read_json(decoded_path)
            if decoded["medusa_hash"] in warmup_hashes:
                candidate["status"] = "duplicate_warmup_sequence"
                continue
            observed = observe(fixture_id, place / "flawed-native/observed",
                               seed=seed, tests=1,
                               timeout=_remaining(deadline, per_process_limit),
                               corpus=corpus, max_steps=5)
            native = validate_native_suffix(fixture_id, observed, decoded, prefix,
                                            plan, assignments, replay["steps"])
            candidate["native_record"] = observed["output_path"]
            candidate["native_input"] = str(native_path)
            candidate["native_confirmation"] = {
                key: value for key, value in native.items() if key != "steps"}
            repaired_id = scenario.stage5_repaired_fixture
            if repaired_id and repaired_id != fixture_id:
                repaired_prefix = {key: value for key, value in prefix.items()
                                   if key != "stage5_prefix_id"}
                repaired_plan = make_plan(repaired_id, repaired_prefix,
                                          tuple(call.signature for call in plan.calls))
                repaired_harness = generate_suffix_harness(
                    repaired_id, repaired_prefix, repaired_plan,
                    place / "repaired-foundry", assignments=assignments,
                    expect_violation=False)
                repaired_replay = concrete_replay_suffix(
                    Path(repaired_harness["project_path"]),
                    place / "repaired-replay", _remaining(deadline, per_process_limit))
                candidate["repaired_foundry"] = repaired_replay
                if repaired_replay["status"] != "property_preserved":
                    candidate["status"] = repaired_replay["status"]
                    row["status"] = ("repaired_regression_failure"
                                     if repaired_replay["status"] == "violation_confirmed"
                                     else repaired_replay["status"])
                    return row
                repaired_corpus = place / "repaired-native/corpus"
                repaired_path = repaired_corpus / "call_sequences/candidate.json"
                repaired_plan_path = place / "repaired-native/suffix-plan.json"
                write_json(repaired_plan_path,
                           {"calls": repaired_plan.concrete_calls(assignments)})
                codec(repaired_id, "encode-suffix", Path(prefix["native_path"]),
                      repaired_path, _remaining(deadline, per_process_limit),
                      plan=repaired_plan_path)
                repaired_decoded_path = place / "repaired-native/decoded.json"
                codec(repaired_id, "decode-corpus", repaired_path,
                      repaired_decoded_path, _remaining(deadline, per_process_limit))
                repaired_observed = observe(
                    repaired_id, place / "repaired-native/observed", seed=seed,
                    tests=1, timeout=_remaining(deadline, per_process_limit),
                    corpus=repaired_corpus, max_steps=5)
                repaired_native = validate_native_suffix(
                    repaired_id, repaired_observed, read_json(repaired_decoded_path),
                    prefix, repaired_plan, assignments, repaired_replay["steps"],
                    repaired=True)
                if len(native["steps"]) != len(repaired_native["steps"]):
                    raise EvidenceMismatchError("repaired call count differs",
                                                status="replay_mismatch")
                call_keys = ("from", "to", "calldata", "value",
                             "actual_block", "actual_timestamp")
                if any(any(a.get(key) != b.get(key) for key in call_keys)
                       for a, b in zip(native["steps"], repaired_native["steps"])):
                    raise EvidenceMismatchError("repaired calls differ",
                                                status="replay_mismatch")
                candidate["repaired_native_record"] = repaired_observed["output_path"]
                candidate["repaired_native_input"] = str(repaired_path)
            candidate["status"] = "confirmed"
            row["status"] = "confirmed"
            return row
        row["status"] = "candidate_rejected"
        return row
    except ToolExecutionError as error:
        row["status"] = error.status
        row["error"] = str(error)
        return row
    except EvidenceMismatchError as error:
        row["status"] = error.status
        row["error"] = str(error)
        return row
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
        row["status"] = "tool_error"
        row["error"] = f"{type(error).__name__}: {error}"
        return row
    finally:
        row["elapsed_seconds"] = time.monotonic() - row["started_monotonic"]
        write_json(directory / "query.json", row)
