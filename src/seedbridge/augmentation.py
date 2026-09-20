"""Fixed concrete and symbolic Stage 2 augmentation policies."""

from __future__ import annotations

import random
import shutil
import time
from pathlib import Path

from .build import assert_same_target, build_manifest
from .config import UINT256_MAX, get_scenario
from .halmos import run_halmos
from .harness import generate_harness
from .io import read_json, write_json
from .medusa import codec, codec_batch, observe
from .metrics import normalized_sequence_identity
from .replay import concrete_replay
from .process import EvidenceMismatchError, ToolExecutionError


DEFAULT_BOUNDARY_VALUES = (
    0, 1, 2, 3, 7, 9, 10, 13, 15, 16, 31, 32, 63, 64, 255, UINT256_MAX,
)


def _checked_result_status(result: object, *, stage: str,
                           allowed: set[str]) -> str:
    """Return a declared domain result, but never hide tool or evidence failures."""
    if not isinstance(result, dict) or not isinstance(result.get("status"), str):
        raise EvidenceMismatchError(
            f"{stage} returned no classified result", status="result_mismatch")
    status = result["status"]
    reason = result.get("reason", "no reason recorded")
    if status == "tool_error":
        raise ToolExecutionError(f"{stage} failed: {reason}", status="tool_error")
    if status in {"result_mismatch", "decode_error"}:
        raise EvidenceMismatchError(
            f"{stage} returned inconsistent evidence: {reason}", status="result_mismatch")
    if stage == "symbolic prefix check" and status == "prefix_mismatch":
        raise EvidenceMismatchError(
            f"symbolic prefix disagrees with the concrete trace: {reason}",
            status="state_mismatch",
        )
    if status not in allowed:
        raise EvidenceMismatchError(
            f"{stage} returned unsupported status {status!r}: {reason}",
            status="result_mismatch",
        )
    return status


def _unsuccessful_symbolic_status(statuses: list[str]) -> str:
    """Preserve the most material valid negative result when no seed is accepted."""
    for status in ("timeout", "invalid_model", "replay_mismatch"):
        if status in statuses:
            return status
    return "no_candidate"


def concrete_values(seed: int, limit: int,
                    boundary_values: tuple[int, ...] = DEFAULT_BOUNDARY_VALUES) -> list[int]:
    if limit <= 0:
        raise ValueError("concrete attempt limit must be positive")
    values: list[int] = []
    for value in boundary_values:
        if type(value) is not int or not 0 <= value <= UINT256_MAX:
            raise ValueError("boundary dictionary contains a non-uint256 value")
        if value not in values:
            values.append(value)
        if len(values) == limit:
            return values
    generator = random.Random(seed)
    while len(values) < limit:
        value = generator.getrandbits(256)
        if value not in values:
            values.append(value)
    return values


def warmup_sequence_ids(warmup: dict) -> set[str]:
    return {
        normalized_sequence_identity(sequence["steps"])
        for sequence in warmup.get("sequences", [])
        if sequence.get("is_complete_sequence") is True
    }


def validate_native_batch(fixture_id: str, entries: list[dict], directory: Path, *,
                          seed: int, timeout: float, existing_ids: set[str],
                          max_candidates: int) -> dict:
    if not entries:
        return {"status": "no_candidate", "attempts": [], "accepted": []}
    observation = observe(fixture_id, directory, seed=seed, tests=len(entries),
                          timeout=timeout, corpus=directory / "corpus")
    by_source = {
        str(Path(sequence.get("source_native_path", "")).resolve()): sequence
        for sequence in observation.get("sequences", [])
        if sequence.get("is_complete_sequence") is True
    }
    accepted: list[dict] = []
    selected_prefixes: set[str] = set()
    accepted_ids = set(existing_ids)
    for entry in entries:
        sequence = by_source.get(str(Path(entry["native_path"]).resolve()))
        if sequence is None:
            entry["validation_status"] = "replay_mismatch"
            continue
        entry["execution"] = {
            "medusa_hash": sequence["medusa_hash"],
            "steps": sequence["steps"],
            "admitted": sequence.get("admitted") is True,
            "complete": sequence.get("is_complete_sequence") is True,
        }
        if (not sequence["steps"][-1]["observe"][3]
                or sequence["steps"][-1].get("invariant_holds") is not True):
            entry["validation_status"] = "goal_false"
            continue
        identity = normalized_sequence_identity(sequence["steps"])
        entry["sequence_identity"] = identity
        if identity in accepted_ids:
            entry["validation_status"] = "duplicate"
            continue
        if entry["case_id"] in selected_prefixes:
            entry["validation_status"] = "prefix_candidate_limit"
            continue
        if len(accepted) >= max_candidates:
            entry["validation_status"] = "batch_candidate_limit"
            continue
        entry["validation_status"] = "accepted"
        selected_prefixes.add(entry["case_id"])
        accepted_ids.add(identity)
        accepted.append(entry)
    accepted_dir = directory / "accepted"
    for index, entry in enumerate(accepted):
        destination = accepted_dir / f"seed-{index:02d}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry["native_path"], destination)
        entry["accepted_native_path"] = str(destination)
    return {
        "status": "completed" if accepted else "no_candidate",
        "attempts": entries,
        "accepted": accepted,
        "observation_path": observation["output_path"],
    }


def concrete_augment(fixture_id: str, prefixes: list[dict], warmup: dict, directory: Path, *,
                     seed: int, attempts_per_prefix: int, max_candidates: int,
                     timeout: float, boundary_values: tuple[int, ...] = DEFAULT_BOUNDARY_VALUES) -> dict:
    started = time.monotonic()
    entries: list[dict] = []
    values = concrete_values(seed, attempts_per_prefix, boundary_values)
    corpus = directory / "corpus/call_sequences"
    requests = []
    for prefix_index, prefix in enumerate(prefixes):
        for attempt_index, argument in enumerate(values):
            native = corpus / f"p{prefix_index:02d}-a{attempt_index:03d}.json"
            requests.append({
                "input": str(Path(prefix["native_path"])), "output": str(native),
                "argument": str(argument), "prefix_index": prefix_index,
                "attempt_index": attempt_index, "case_id": prefix["case_id"],
            })
    plan = directory / "codec-batch-plan.json"
    write_json(plan, [{key: request[key] for key in ("input", "output", "argument")}
                      for request in requests])
    manifest = codec_batch(fixture_id, plan, directory / "codec-batch-result.json", timeout)
    if len(manifest["entries"]) != len(requests):
        raise RuntimeError("native codec batch result count differs from its plan")
    for request, encoded in zip(requests, manifest["entries"]):
        decoded = encoded["summary"]
        identity = normalized_sequence_identity(decoded["steps"])
        entry = {
            "policy": "fixed_boundary_then_seeded_random",
            "prefix_index": request["prefix_index"],
            "attempt_index": request["attempt_index"],
            "case_id": request["case_id"],
            "argument": request["argument"],
            "native_path": encoded["native_path"],
            "medusa_hash": decoded["medusa_hash"],
            "sequence_identity": identity,
        }
        entries.append(entry)
    result = validate_native_batch(
        fixture_id, entries, directory, seed=seed, timeout=timeout,
        existing_ids=warmup_sequence_ids(warmup), max_candidates=max_candidates,
    )
    result["elapsed_seconds"] = time.monotonic() - started
    result["attempt_limit_per_prefix"] = attempts_per_prefix
    result["boundary_values"] = [str(value) for value in boundary_values]
    return result


def symbolic_augment(fixture_id: str, prefixes: list[dict], warmup: dict, directory: Path, *,
                     seed: int, max_candidates: int, query_timeout: float,
                     process_timeout: float, total_timeout: float,
                     solver: str, executable: str,
                     baseline_build: dict) -> dict:
    started = time.monotonic()
    deadline = started + total_timeout

    def remaining(limit: float, *, validation_reserve: float = 0.0) -> float:
        value = min(limit, deadline - time.monotonic() - validation_reserve)
        if value < 0.15:
            raise TimeoutError("symbolic augmentation total deadline reached")
        return value

    entries: list[dict] = []
    attempts: list[dict] = []
    unsuccessful_statuses: list[str] = []
    scenario = get_scenario(fixture_id)
    for prefix_index, prefix in enumerate(prefixes):
        if deadline - time.monotonic() <= 0.25:
            attempts.append({"prefix_index": prefix_index, "case_id": prefix["case_id"],
                             "status": "not_attempted_budget_reserve"})
            break
        attempt_started = time.monotonic()
        case = directory / f"case-{prefix_index:02d}"
        attempt = {"prefix_index": prefix_index, "case_id": prefix["case_id"]}
        attempts.append(attempt)
        try:
            generated = generate_harness(fixture_id, prefix, case / "symbolic")
            project = Path(generated["project_path"])
            prefix_result = run_halmos(project, "check_prefix()", case / "prefix-check",
                                       remaining(query_timeout, validation_reserve=0.5), solver, executable)
            attempt["prefix_check"] = prefix_result
            prefix_status = _checked_result_status(
                prefix_result, stage="symbolic prefix check",
                allowed={"prefix_confirmed", "prefix_incomplete", "timeout", "stuck",
                         "all_paths_reverted"},
            )
            if prefix_status != "prefix_confirmed":
                unsuccessful_statuses.append(prefix_status)
                attempt["elapsed_seconds"] = time.monotonic() - attempt_started
                continue
            generated_build = build_manifest(
                project, scenario.contract, case / "build",
                remaining(process_timeout, validation_reserve=0.5))
            assert_same_target(baseline_build, generated_build)
            solved = run_halmos(project, "check_goal(uint256)", case / "solve",
                                remaining(query_timeout, validation_reserve=0.5), solver, executable)
            attempt["solve"] = solved
            solve_status = _checked_result_status(
                solved, stage="symbolic goal solve",
                allowed={"candidate", "no_witness_within_bounds", "timeout", "stuck",
                         "all_paths_reverted", "invalid_model"},
            )
            if solve_status != "candidate":
                unsuccessful_statuses.append(solve_status)
                attempt["elapsed_seconds"] = time.monotonic() - attempt_started
                continue
            argument = solved["candidates"][0]
            concrete = generate_harness(fixture_id, prefix, case / "concrete", int(argument))
            replay = concrete_replay(
                Path(concrete["project_path"]), case / "concrete-check",
                remaining(process_timeout, validation_reserve=0.5))
            attempt["replay"] = replay
            replay_status = _checked_result_status(
                replay, stage="concrete candidate replay",
                allowed={"reachable_confirmed", "replay_mismatch", "timeout"},
            )
            if replay_status != "reachable_confirmed":
                unsuccessful_statuses.append(replay_status)
                attempt["elapsed_seconds"] = time.monotonic() - attempt_started
                continue
            concrete_build = build_manifest(
                Path(concrete["project_path"]), scenario.contract,
                case / "concrete-build", remaining(process_timeout, validation_reserve=0.5))
            assert_same_target(baseline_build, concrete_build)
            native = directory / "native-validation/corpus/call_sequences" / f"p{prefix_index:02d}.json"
            codec(fixture_id, "encode-candidate", Path(prefix["native_path"]), native,
                  remaining(process_timeout, validation_reserve=0.5), argument)
            decoded_path = case / "decoded.json"
            codec(fixture_id, "decode-corpus", native, decoded_path,
                  remaining(process_timeout, validation_reserve=0.5))
            decoded = read_json(decoded_path)
            entry = {
                "policy": "halmos_one_uint256_query",
                "prefix_index": prefix_index,
                "attempt_index": 0,
                "case_id": prefix["case_id"],
                "argument": argument,
                "native_path": str(native),
                "medusa_hash": decoded["medusa_hash"],
                "sequence_identity": normalized_sequence_identity(decoded["steps"]),
                "model_file": solved["output_path"],
            }
            entries.append(entry)
            attempt["candidate"] = entry
            attempt["elapsed_seconds"] = time.monotonic() - attempt_started
        except TimeoutError as error:
            unsuccessful_statuses.append("timeout")
            attempt["status"] = "timeout"
            attempt["reason"] = str(error)
            attempt["elapsed_seconds"] = time.monotonic() - attempt_started
            break
        except ToolExecutionError as error:
            if error.status != "timeout":
                raise
            unsuccessful_statuses.append("timeout")
            attempt["status"] = "timeout"
            attempt["reason"] = str(error)
            attempt["elapsed_seconds"] = time.monotonic() - attempt_started
            break
        if len(entries) >= max_candidates:
            break
    try:
        validation = validate_native_batch(
            fixture_id, entries, directory / "native-validation", seed=seed,
            timeout=remaining(process_timeout), existing_ids=warmup_sequence_ids(warmup),
            max_candidates=max_candidates,
        )
    except TimeoutError as error:
        unsuccessful_statuses.append("timeout")
        validation = {"status": "timeout", "reason": str(error),
                      "attempts": entries, "accepted": []}
    except ToolExecutionError as error:
        if error.status != "timeout":
            raise
        unsuccessful_statuses.append("timeout")
        validation = {"status": "timeout", "reason": str(error),
                      "attempts": entries, "accepted": []}
    if not validation.get("accepted") and validation.get("status") == "no_candidate":
        validation["status"] = _unsuccessful_symbolic_status(unsuccessful_statuses)
    validation["symbolic_attempts"] = attempts
    validation["elapsed_seconds"] = time.monotonic() - started
    return validation


def save_augmentation(directory: Path, result: dict) -> None:
    write_json(directory / "augmentation.json", result)
