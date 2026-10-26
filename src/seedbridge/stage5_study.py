"""Paired warmup, charged symbolic augmentation, and native continuation."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import shutil
import time

from .budget import BudgetLedger, CampaignDeadlineError
from .build import assert_medusa_build, build_manifest
from .cache import copy_isolated_workspace, create_fixture_base, tree_manifest
from .config import get_scenario
from .doctor import inspect_toolchain
from .io import file_hash, read_json, write_json
from .medusa import build_fixture, campaign
from .process import EvidenceMismatchError, ToolExecutionError
from .safety import checked_state
from .stage5_augment import execute_query
from .stage5_scheduler import QueryScheduler
from .suffix import enumerate_plans, select_stage5_prefixes
from .study_runner import current_execution_source, snapshot_execution_source


ARMS = ("native_resume", "symbolic_one", "symbolic_two", "symbolic_adaptive")
FIXTURES = ("reservation_flawed", "reservation_repaired", "request_flawed",
            "request_repaired", "accounting_flawed", "accounting_repaired")


def validate_config(value: dict) -> dict:
    if (value.get("schema_version") != 1
            or value.get("study_id") not in {"stage5-bounded-suffix-v1",
                                             "stage5-bounded-suffix-v2"}
            or tuple(value.get("fixtures", [])) != FIXTURES
            or tuple(value.get("arms", [])) != ARMS):
        raise ValueError("Stage 5 fixed case/arm protocol differs")
    repeats = value.get("repeats")
    if (not isinstance(repeats, list) or not repeats
            or any(type(item) is not int or item < 1 for item in repeats)
            or len(set(repeats)) != len(repeats)):
        raise ValueError("invalid repeat matrix")
    for key in ("total_budget_seconds", "common_limit_seconds", "augmentation_limit_seconds",
                "prefix_check_limit_seconds", "solver_limit_seconds",
                "minimum_query_seconds", "continuation_reserve_seconds",
                "process_limit_seconds", "cleanup_tolerance_seconds"):
        if type(value.get(key)) not in (int, float) or value[key] <= 0:
            raise ValueError(f"invalid {key}")
    for key in ("warmup_sequences", "max_prefixes", "max_plans_per_length",
                "max_queries", "continuation_sequence_limit"):
        if type(value.get(key)) is not int or value[key] < 1:
            raise ValueError(f"invalid {key}")
    if (value.get("max_complete_steps") != 5 or value.get("worker_count") != 1
            or value.get("arm_order") not in (None, "cyclic_by_repeat")):
        raise ValueError("Stage 5 fixed execution boundary differs")
    if value["common_limit_seconds"] >= value["total_budget_seconds"]:
        raise ValueError("common preparation exceeds total budget")
    if value["augmentation_limit_seconds"] + value["continuation_reserve_seconds"] \
            >= value["total_budget_seconds"] - value["common_limit_seconds"]:
        raise ValueError("no charged native continuation remains")
    return value


def _seed(fixture_id: str, repeat: int) -> int:
    return 91000 + FIXTURES.index(fixture_id) * 100 + repeat


def _violations(fixture_id: str, sequences: list[dict]) -> list[dict]:
    result = []
    for sequence in sequences:
        steps = sequence.get("steps", [])
        for index, step in enumerate(steps):
            state = checked_state(fixture_id, step.get("observe"))
            if (state is None or step.get("invariant_holds") is not True
                    or step.get("property_holds") is not state["property_holds"]
                    or step.get("observer_state_unchanged") is not True
                    or step.get("state_root_before_observer")
                    != step.get("state_root_after_observer")):
                raise EvidenceMismatchError("native step failed independent safety/observer check",
                                            status="evidence_error")
            if not state["property_holds"]:
                result.append({"sequence_index": sequence.get("sequence_index"),
                               "call_index": index, "native_digest": sequence.get("native_digest")})
                break
    return result


def prepare_common(config: dict, fixture_id: str, repeat: int, directory: Path) -> dict:
    began = time.monotonic()
    directory.mkdir(parents=True, exist_ok=False)
    project = directory / "cache-base/project"
    create_fixture_base(fixture_id, project)
    build_fixture(fixture_id, directory / "build-command",
                  config["common_limit_seconds"], project=project)
    baseline = build_manifest(project, get_scenario(fixture_id).contract,
                              directory / "build-manifest", config["common_limit_seconds"])
    corpus = directory / "warmup/corpus"
    warmup = campaign(
        fixture_id, directory / "warmup", seed=_seed(fixture_id, repeat),
        tests=config["warmup_sequences"],
        fuzz_timeout=config["common_limit_seconds"],
        process_timeout=config["common_limit_seconds"] + 2,
        corpus=corpus, project=project, max_steps=5)
    assert_medusa_build(baseline, warmup)
    violations = _violations(fixture_id, warmup["sequences"])
    prefixes, rejected = select_stage5_prefixes(
        warmup, fixture_id, config["max_prefixes"])
    write_json(directory / "prefix-pool.json", {"selected": prefixes, "rejected": rejected})
    elapsed = time.monotonic() - began
    row = {"schema_version": 1, "fixture_id": fixture_id, "repeat": repeat,
           "seed": _seed(fixture_id, repeat), "elapsed_seconds": elapsed,
           "within_common_limit": elapsed <= config["common_limit_seconds"],
           "baseline_build": baseline, "project": str(project),
           "cache_manifest": tree_manifest(project), "corpus": str(corpus),
           "corpus_manifest": tree_manifest(corpus),
           "warmup_record": warmup["output_path"],
           "prefix_pool": str(directory / "prefix-pool.json"),
           "warmup_violations": violations,
           "warmup_status": warmup["status"],
           "warmup_stop_reason": warmup["stop_reason"]}
    write_json(directory / "common.json", row)
    return {**row, "warmup": warmup, "prefixes": prefixes}


def _plan_pool(fixture_id: str, prefixes: list[dict], length: int,
               max_plans: int) -> tuple[list, list[dict]]:
    plans, decisions = [], []
    for prefix in prefixes:
        found, logged = enumerate_plans(fixture_id, prefix, length,
                                         max_plans=max_plans)
        plans.extend((prefix, plan) for plan in found)
        decisions.extend({"prefix_id": prefix["stage5_prefix_id"], **item}
                         for item in logged)
    return plans, decisions


def run_slot(config: dict, fixture_id: str, repeat: int, arm: str,
             common: dict, directory: Path, toolchain: dict) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    ledger = BudgetLedger(config["total_budget_seconds"],
                          cleanup_tolerance_seconds=config["cleanup_tolerance_seconds"],
                          initial_charge_seconds=common["elapsed_seconds"])
    row = {"schema_version": 1, "fixture_id": fixture_id, "repeat": repeat,
           "seed": common["seed"], "arm": arm, "status": "running",
           "evaluation_valid": False, "warmup_violations": common["warmup_violations"],
           "queries": [], "planner_decisions": [], "scheduler_decisions": [],
           "candidate_confirmations": [], "failure": None}
    native = None
    try:
        with ledger.stage("input_and_cache_prepare", kind="preparation"):
            project = directory / "workspace/project"
            copy_isolated_workspace(Path(common["project"]), project)
            corpus = directory / "corpus"
            shutil.copytree(common["corpus"], corpus)
            if tree_manifest(corpus)["content_sha256"] != common["corpus_manifest"]["content_sha256"]:
                raise EvidenceMismatchError("paired warmup corpus copy differs",
                                            status="evidence_error")
        if arm != "native_resume" and not common["warmup_violations"]:
            with ledger.stage("symbolic_augmentation", kind="augmentation") as stage:
                one, decisions1 = _plan_pool(fixture_id, common["prefixes"], 1,
                                              config["max_plans_per_length"])
                two, decisions2 = _plan_pool(fixture_id, common["prefixes"], 2,
                                              config["max_plans_per_length"])
                row["planner_decisions"] = decisions1 + decisions2
                by_id = {plan.query_id: (prefix, plan) for prefix, plan in one + two}
                scheduler = QueryScheduler(
                    arm, [plan for _, plan in one], [plan for _, plan in two],
                    config["minimum_query_seconds"],
                    config["continuation_reserve_seconds"])
                augment_deadline = min(time.monotonic() + config["augmentation_limit_seconds"],
                                       ledger.deadline - config["continuation_reserve_seconds"])
                hashes = {seq["medusa_hash"] for seq in common["warmup"]["sequences"]}
                for ordinal in range(config["max_queries"]):
                    remaining = min(ledger.remaining_seconds,
                                    max(0.0, augment_deadline - time.monotonic())
                                    + config["continuation_reserve_seconds"])
                    selected = scheduler.next_query(remaining)
                    if selected is None:
                        break
                    scheduler.decisions[-1]["allocated_query_seconds"] = max(
                        0.0, augment_deadline - time.monotonic())
                    scheduler.decisions[-1]["prefix_check_limit_seconds"] = config[
                        "prefix_check_limit_seconds"]
                    scheduler.decisions[-1]["solver_limit_seconds"] = config[
                        "solver_limit_seconds"]
                    prefix, plan = by_id[selected.query_id]
                    started = time.monotonic()
                    query = execute_query(
                        fixture_id, prefix, plan, directory / f"query-{ordinal:02d}",
                        deadline=augment_deadline,
                        per_process_limit=config["process_limit_seconds"],
                        prefix_limit=config["prefix_check_limit_seconds"],
                        solver_limit=config["solver_limit_seconds"],
                        solver=toolchain["tools"]["z3"]["path"],
                        halmos=toolchain["tools"]["halmos"]["path"],
                        baseline_build=common["baseline_build"], seed=common["seed"],
                        warmup_hashes=hashes)
                    row["queries"].append({"query_id": plan.query_id,
                                           "record": str(directory / f"query-{ordinal:02d}/query.json"),
                                           "status": query["status"],
                                           "suffix_length": len(plan.calls)})
                    feedback = query["status"]
                    if feedback in {"prefix_confirmed", "running"}:
                        feedback = "tool_error"
                    scheduler.record_feedback(
                        plan, feedback, actual_seconds=time.monotonic() - started,
                        remaining_seconds=ledger.remaining_seconds)
                    if feedback == "confirmed":
                        confirmed = [item for item in query["candidates"]
                                     if item["status"] == "confirmed"]
                        if len(confirmed) != 1:
                            raise EvidenceMismatchError("confirmed query lacks one native candidate",
                                                        status="evidence_error")
                        target = corpus / "call_sequences" / f"zz-stage5-{ordinal:02d}.json"
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(confirmed[0]["native_input"], target)
                        row["candidate_confirmations"].append({
                            "query_id": plan.query_id, "native_input": confirmed[0]["native_input"],
                            "imported_input": str(target),
                            "native_record": confirmed[0]["native_record"],
                            "first_violation_call_index": confirmed[0]["native_confirmation"]["first_violation_call_index"],
                            "two_step_only": confirmed[0]["native_confirmation"]["two_step_only"]})
                        break
                    if feedback in {"tool_error", "result_mismatch", "decode_error",
                                    "prefix_mismatch", "replay_mismatch", "state_mismatch",
                                    "observer_mismatch", "invalid_model",
                                    "repaired_regression_failure"}:
                        raise EvidenceMismatchError(f"symbolic query failed: {feedback}",
                                                    status=feedback)
                row["scheduler_decisions"] = scheduler.decisions
                row["scheduler_feedback"] = scheduler.feedback
                if not common["prefixes"]:
                    stage.finish("no_eligible_prefix", "no executed, property-safe prefix")
                elif not row["candidate_confirmations"]:
                    stage.finish("no_candidate", "no confirmed candidate inside query budget")
        else:
            reason = ("native control" if arm == "native_resume" else
                      "common warmup already confirmed a violation")
            ledger.record_skipped("symbolic_augmentation", kind="augmentation",
                                  status="skipped", reason=reason)
        with ledger.stage("native_startup_and_continuation", kind="native") as stage:
            remaining = ledger.remaining_seconds
            evidence_reserve = max(config["cleanup_tolerance_seconds"] + 0.25,
                                   config["continuation_reserve_seconds"] / 2)
            fuzz_time = remaining - evidence_reserve
            if fuzz_time < 0.2:
                raise CampaignDeadlineError("no time remains for native continuation")
            native = campaign(
                fixture_id, directory / "native", seed=common["seed"],
                tests=config["continuation_sequence_limit"],
                fuzz_timeout=fuzz_time,
                process_timeout=remaining + config["cleanup_tolerance_seconds"],
                corpus=corpus, project=project, compact=True, max_steps=5)
            if native["stop_reason"] not in {"time_limit", "property_failure"}:
                raise EvidenceMismatchError(
                    f"unexpected native termination: {native['stop_reason']}",
                    status="evidence_error")
        with ledger.stage("online_evidence_validation", kind="evidence"):
            if len(native["lineage"]) != native["completed_sequences"]:
                raise EvidenceMismatchError("native lineage is incomplete",
                                            status="evidence_error")
            if any(not item["parents_resolved"] for item in native["lineage"]
                   if item["kind"] == "mutation"):
                raise EvidenceMismatchError("native mutation parent is unresolved",
                                            status="evidence_error")
            native_violations = _violations(fixture_id, native["sequences"])
            row["native_violations"] = native_violations
            row["native_record"] = native["output_path"]
            row["native_event_stream"] = native["compact_events"]["path"]
            row["native_completion_timing"] = native["completion_path"]
            row["native_stop_reason"] = native["stop_reason"]
            row["native_completed_sequences"] = native["completed_sequences"]
            row["native_mutation_sequences"] = native["mutation_sequences"]
            row["native_startup_replays"] = native["startup_replays"]
        row["status"] = "completed"
    except CampaignDeadlineError as error:
        row["status"] = "campaign_deadline"
        row["failure"] = str(error)
    except (ToolExecutionError, EvidenceMismatchError) as error:
        row["status"] = error.status
        row["failure"] = str(error)
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
        row["status"] = "tool_error"
        row["failure"] = f"{type(error).__name__}: {error}"
    finally:
        row["stages"] = ledger.records
        row["budget"] = ledger.summary()
        row["evaluation_valid"] = (row["status"] == "completed"
                                   and common["within_common_limit"]
                                   and not any(stage.get("after_deadline") for stage in ledger.records))
        write_json(directory / "slot.json", row)
    return row


def _slot_record_exists(root: Path, item: dict) -> bool:
    path = Path(item.get("record", "")).resolve()
    return path.is_relative_to(root) and path.is_file()


def run_stage5_study(config_path: Path, output: Path, *,
                     smoke_blocks: int | None = None,
                     resume: bool = False) -> dict:
    config_path = Path(config_path).resolve()
    config = validate_config(read_json(config_path))
    if smoke_blocks is not None and (type(smoke_blocks) is not int or smoke_blocks < 1):
        raise ValueError("smoke block count must be positive")
    output = Path(output).resolve()
    if resume:
        if not output.is_dir():
            raise ValueError("Stage 5 resume requires an existing study directory")
        manifest = read_json(output / "manifest.json")
        if file_hash(config_path) != manifest["config_sha256"]:
            raise ValueError("resume configuration differs from frozen input")
        current = current_execution_source()
        if current["content_sha256"] != manifest["execution_source"]["content_sha256"]:
            raise ValueError("execution source changed; start a new formal study")
        manifest.setdefault("failed_block_attempts", [])
        manifest["status"] = "running"
    else:
        if output.exists():
            raise ValueError("Stage 5 study output must be a new directory")
        output.mkdir(parents=True)
        shutil.copy2(config_path, output / "frozen-config.json")
        source = snapshot_execution_source(output / "source")
    toolchain = inspect_toolchain()
    if not toolchain["ok"]:
        raise ToolExecutionError("Stage 5 toolchain preflight failed", status="tool_error")
    if not resume:
        manifest = {"schema_version": 1, "study_id": config["study_id"],
                    "status": "running", "config_sha256": file_hash(config_path),
                    "execution_source": source,
                    "toolchain": toolchain, "blocks": [], "slots": [],
                    "failed_block_attempts": [],
                    "note": "each arm is restarted from a copied common warmup corpus; later Medusa RNG is not paired"}
    write_json(output / "manifest.json", manifest)
    for fixture_id in config["fixtures"]:
        for repeat in config["repeats"]:
            if smoke_blocks is not None and len(manifest["blocks"]) >= smoke_blocks:
                break
            block = output / "blocks" / fixture_id / f"repeat-{repeat:02d}"
            old_slots = [item for item in manifest["slots"]
                         if item["fixture_id"] == fixture_id and item["repeat"] == repeat]
            if (len(old_slots) == len(config["arms"])
                    and all(item["evaluation_valid"] and _slot_record_exists(output, item)
                            for item in old_slots)
                    and (block / "common/common.json").is_file()):
                continue
            if block.exists():
                failed = output / "failed-attempts" / fixture_id / f"repeat-{repeat:02d}-attempt-{len(manifest['failed_block_attempts']) + 1:03d}"
                failed.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(block), str(failed))
                manifest["failed_block_attempts"].append({
                    "fixture_id": fixture_id, "repeat": repeat,
                    "record": str(failed), "prior_slots": old_slots})
                manifest["blocks"] = [item for item in manifest["blocks"]
                                      if not (item["fixture_id"] == fixture_id
                                              and item["repeat"] == repeat)]
                manifest["slots"] = [item for item in manifest["slots"]
                                     if not (item["fixture_id"] == fixture_id
                                             and item["repeat"] == repeat)]
                write_json(output / "manifest.json", manifest)
            common = prepare_common(config, fixture_id, repeat, block / "common")
            manifest["blocks"].append({"fixture_id": fixture_id, "repeat": repeat,
                                       "record": str(block / "common/common.json")})
            shift = ((repeat - 1) % len(config["arms"])
                     if config.get("arm_order") == "cyclic_by_repeat" else 0)
            order = config["arms"][shift:] + config["arms"][:shift]
            for arm in order:
                slot = run_slot(config, fixture_id, repeat, arm, common,
                                block / "arms" / arm, toolchain)
                manifest["slots"].append({"fixture_id": fixture_id, "repeat": repeat,
                                          "arm": arm, "record": str(block / "arms" / arm / "slot.json"),
                                          "status": slot["status"],
                                          "evaluation_valid": slot["evaluation_valid"]})
                write_json(output / "manifest.json", manifest)
        if smoke_blocks is not None and len(manifest["blocks"]) >= smoke_blocks:
            break
    manifest["status"] = ("complete" if len(manifest["slots"]) == 240
                          and all(slot["evaluation_valid"] for slot in manifest["slots"])
                          else "incomplete")
    write_json(output / "manifest.json", manifest)
    return manifest
