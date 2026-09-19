"""Stage 2 common-warmup campaigns and offline benchmark reporting."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
import platform
from pathlib import Path
import shutil
import socket
import subprocess
import time
import uuid

from .augmentation import concrete_augment, save_augmentation, symbolic_augment
from .build import assert_medusa_build, build_manifest
from .budget import BudgetLedger, CampaignDeadlineError
from .campaign import ARMS, BudgetSpec, CampaignRecord, CampaignSpec
from .config import ROOT, SCENARIOS, get_scenario
from .doctor import inspect_toolchain
from .io import file_hash, read_json, write_json
from .medusa import build_fixture, campaign
from .metrics import save_segmented_metrics, segmented_metrics, set_delta, snapshot
from .process import EvidenceMismatchError, ToolExecutionError
from .trace import select_prefixes


@dataclass(frozen=True)
class BenchmarkConfig:
    fixtures: tuple[str, ...]
    repeats: tuple[int, ...]
    arms: tuple[str, ...]
    arm_orders: dict[str, tuple[str, ...]]
    seeds: dict[str, int]
    warmup_sequences: int
    continuation_test_limit: int
    max_prefixes: int
    max_candidates: int
    concrete_attempts_per_prefix: int
    boundary_values: tuple[int, ...]
    budget: BudgetSpec
    schema_version: int = 1

    @classmethod
    def from_dict(cls, document: dict) -> "BenchmarkConfig":
        if not isinstance(document, dict) or document.get("schema_version") != 1:
            raise ValueError("benchmark config schema_version must be 1")
        config = cls(
            fixtures=tuple(document["fixtures"]),
            repeats=tuple(document["repeats"]),
            arms=tuple(document["arms"]),
            arm_orders={str(key): tuple(value) for key, value in document["arm_orders"].items()},
            seeds={str(key): int(value) for key, value in document["seeds"].items()},
            warmup_sequences=int(document["warmup_sequences"]),
            continuation_test_limit=int(document["continuation_test_limit"]),
            max_prefixes=int(document["max_prefixes"]),
            max_candidates=int(document["max_candidates"]),
            concrete_attempts_per_prefix=int(document["concrete_attempts_per_prefix"]),
            boundary_values=tuple(int(value) for value in document["boundary_values"]),
            budget=BudgetSpec(**document["budget"]),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if set(self.fixtures) != set(SCENARIOS) or len(self.fixtures) != 4:
            raise ValueError("formal benchmark must contain exactly the four built-in fixtures")
        if self.repeats != (1, 2, 3, 4, 5):
            raise ValueError("formal benchmark repeats must be 1..5")
        if set(self.arms) != set(ARMS) or len(self.arms) != 3:
            raise ValueError("formal benchmark must contain exactly the three Stage 2 arms")
        if not 2 <= self.warmup_sequences <= 10000 or not 2 <= self.continuation_test_limit <= 10000:
            raise ValueError("native sequence limits must be in 2..10000")
        if not 1 <= self.max_prefixes <= 4 or not 1 <= self.max_candidates <= 4:
            raise ValueError("prefix and candidate limits must be in 1..4")
        if not 1 <= self.concrete_attempts_per_prefix <= 64:
            raise ValueError("concrete attempts per prefix must be in 1..64")
        for repeat in self.repeats:
            if set(self.arm_orders.get(str(repeat), ())) != set(ARMS):
                raise ValueError(f"arm order for repeat {repeat} is missing or invalid")
        for fixture in self.fixtures:
            get_scenario(fixture)
            for repeat in self.repeats:
                key = f"{fixture}:{repeat}"
                if key not in self.seeds or not 0 <= self.seeds[key] < (1 << 63):
                    raise ValueError(f"missing valid seed for {key}")

    def seed(self, fixture: str, repeat: int) -> int:
        return self.seeds[f"{fixture}:{repeat}"]


def load_benchmark_config(path: Path) -> BenchmarkConfig:
    return BenchmarkConfig.from_dict(read_json(path))


def _git_text(*arguments: str) -> str:
    result = subprocess.run(["git", *arguments], cwd=ROOT, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    return result.stdout.strip()


def benchmark_manifest(config_path: Path, config: BenchmarkConfig) -> dict:
    patch = ROOT / "adapters/medusa/patches/medusa-v1.5.1-lineage.patch"
    binary = ROOT / ".bin/medusa-adapter"
    return {
        "schema_version": 1,
        "benchmark_id": uuid.uuid4().hex,
        "config_path": str(config_path.resolve()),
        "config_sha256": file_hash(config_path),
        "git_head": _git_text("rev-parse", "HEAD"),
        "git_status": _git_text("status", "--porcelain=v1"),
        "host": {"hostname": socket.gethostname(), "platform": platform.platform(),
                 "python": platform.python_version()},
        "medusa": {
            "upstream_version": "v1.5.1",
            "upstream_zip_sum": "h1:euR4vTAV85QglBsIiwvCDrGT6Fu/6KHkZF2jmzxxe2Q=",
            "lineage_patch": str(patch),
            "lineage_patch_sha256": file_hash(patch),
            "adapter_binary_sha256": file_hash(binary),
        },
        "fixtures": {
            fixture: {"source_sha256": file_hash(get_scenario(fixture).source_file)}
            for fixture in config.fixtures
        },
        "run_order": [
            {"fixture": fixture, "repeat_id": repeat,
             "arms": list(config.arm_orders[str(repeat)])}
            for fixture in config.fixtures for repeat in config.repeats
        ],
        "randomness_boundary": {
            "controlled": ["worker RNG seed", "fixture order", "repeat order", "arm order",
                           "import filename order", "concrete random samples"],
            "uncontrolled": ["Medusa corpus chooser clock-seeded RNG",
                             "Medusa mutation strategy chooser clock-seeded RNG"],
        },
        "cache_protocol": "one physical build/warmup per fixture-repeat; each arm receives a fresh corpus copy",
        "config": {
            "fixtures": list(config.fixtures), "repeats": list(config.repeats),
            "arms": list(config.arms), "budget": config.budget.__dict__,
        },
    }


def prepare_common(config: BenchmarkConfig, fixture_id: str, repeat_id: int,
                   directory: Path, toolchain: dict) -> dict:
    started = time.monotonic()
    scenario = get_scenario(fixture_id)
    directory.mkdir(parents=True, exist_ok=False)
    build_fixture(fixture_id, directory / "build", config.budget.common_limit_seconds)
    build = build_manifest(scenario.root, scenario.contract, directory / "build",
                           config.budget.common_limit_seconds)
    corpus = directory / "warmup/corpus"
    warmup = campaign(
        fixture_id, directory / "warmup", seed=config.seed(fixture_id, repeat_id),
        tests=config.warmup_sequences,
        fuzz_timeout=config.budget.common_limit_seconds,
        process_timeout=config.budget.common_limit_seconds + config.budget.cleanup_tolerance_seconds,
        corpus=corpus,
    )
    assert_medusa_build(build, warmup)
    prefixes, rejected = select_prefixes(warmup, config.max_prefixes, fixture_id)
    write_json(directory / "prefix-pool.json", {"selected": prefixes, "rejected": rejected})
    elapsed = time.monotonic() - started
    result = {
        "schema_version": 1,
        "fixture_id": fixture_id,
        "repeat_id": repeat_id,
        "seed": config.seed(fixture_id, repeat_id),
        "elapsed_seconds": elapsed,
        "within_common_limit": elapsed <= config.budget.common_limit_seconds,
        "build": build,
        "warmup_path": warmup["output_path"],
        "corpus_path": str(corpus),
        "prefix_pool_path": str(directory / "prefix-pool.json"),
        "selected_prefixes": len(prefixes),
        "warmup_goal_reached": any(
            step.get("goal") is True
            for sequence in warmup.get("sequences", []) for step in sequence.get("steps", [])
        ),
        "toolchain": toolchain,
    }
    write_json(directory / "common.json", result)
    return {**result, "warmup": warmup, "prefixes": prefixes}


def _copy_accepted_seeds(augmentation: dict, corpus: Path) -> list[str]:
    paths = []
    destination = corpus / "call_sequences"
    destination.mkdir(parents=True, exist_ok=True)
    for index, candidate in enumerate(augmentation.get("accepted", [])):
        target = destination / f"zz-augmentation-{index:02d}.json"
        shutil.copy2(candidate["accepted_native_path"], target)
        paths.append(str(target))
    return paths


def run_arm(config: BenchmarkConfig, fixture_id: str, repeat_id: int, arm: str,
            common: dict, directory: Path) -> dict:
    spec = CampaignSpec(
        fixture_id=fixture_id, arm=arm, repeat_id=repeat_id,
        seed=config.seed(fixture_id, repeat_id), warmup_sequences=config.warmup_sequences,
        budget=config.budget, max_prefixes=config.max_prefixes,
        max_candidates=config.max_candidates,
        concrete_attempts_per_prefix=config.concrete_attempts_per_prefix,
    )
    record = CampaignRecord(spec)
    directory.mkdir(parents=True, exist_ok=False)
    corpus = directory / "corpus"
    shutil.copytree(common["corpus_path"], corpus)
    ledger = BudgetLedger(
        config.budget.total_seconds,
        cleanup_tolerance_seconds=config.budget.cleanup_tolerance_seconds,
        initial_charge_seconds=common["elapsed_seconds"],
    )
    augmentation: dict = {"status": "not_applicable", "attempts": [], "accepted": []}
    native: dict | None = None
    metrics: dict | None = None
    try:
        with ledger.stage("prefix_pool", kind="prefix") as stage:
            prefixes = list(common["prefixes"])
            write_json(directory / "prefix-pool.json", {"selected": prefixes})
            if not prefixes and arm != "native_resume":
                stage.finish("no_eligible_prefix", "common warmup produced no eligible goal=false prefix")

        if arm == "native_resume":
            ledger.record_skipped("augmentation", kind="augmentation", status="skipped",
                                  reason="native_resume performs no augmentation")
        elif not prefixes:
            augmentation = {"status": "no_eligible_prefix", "attempts": [], "accepted": []}
            record.augmentation_status = "no_eligible_prefix"
            ledger.record_skipped("augmentation", kind="augmentation", status="no_eligible_prefix",
                                  reason="common prefix pool is empty")
        else:
            with ledger.stage("augmentation", kind="augmentation") as stage:
                available = ledger.timeout_for(
                    config.budget.augmentation_limit_seconds,
                    reserve_seconds=(config.budget.startup_reserve_seconds
                                     + config.budget.continuation_reserve_seconds),
                )
                if arm == "concrete_augment":
                    augmentation = concrete_augment(
                        fixture_id, prefixes, common["warmup"], directory / "augmentation",
                        seed=spec.seed, attempts_per_prefix=spec.concrete_attempts_per_prefix,
                        max_candidates=spec.max_candidates, timeout=available,
                        boundary_values=config.boundary_values,
                    )
                else:
                    toolchain = common["toolchain"]
                    augmentation = symbolic_augment(
                        fixture_id, prefixes, common["warmup"], directory / "augmentation",
                        seed=spec.seed, max_candidates=spec.max_candidates,
                        query_timeout=min(config.budget.query_limit_seconds, available),
                        process_timeout=available,
                        total_timeout=available,
                        solver=toolchain["tools"]["z3"]["path"],
                        executable=toolchain["tools"]["halmos"]["path"],
                        baseline_build=common["build"],
                    )
                save_augmentation(directory / "augmentation", augmentation)
                record.augmentation_status = augmentation["status"]
                if augmentation["status"] in {"no_candidate", "timeout", "invalid_model", "replay_mismatch"}:
                    stage.finish(augmentation["status"], "augmentation completed without an accepted seed")
            record.artifacts["accepted_seed_paths"] = _copy_accepted_seeds(augmentation, corpus)

        with ledger.stage("native_startup_and_continuation", kind="native"):
            remaining = ledger.remaining_seconds
            # Native setup and JSON/JSONL flushing are charged but occur outside Medusa's
            # internal fuzz timer. The frozen startup reserve and cleanup tolerance cover
            # those costs; the small flush margin was calibrated before the formal run.
            setup_margin = (config.budget.startup_reserve_seconds
                            + config.budget.cleanup_tolerance_seconds + 0.25)
            fuzz_timeout = remaining - setup_margin
            if fuzz_timeout <= 0:
                raise CampaignDeadlineError("no budget remains for native continuation")
            native = campaign(
                fixture_id, directory / "native", seed=spec.seed,
                tests=config.continuation_test_limit, fuzz_timeout=fuzz_timeout,
                process_timeout=remaining + config.budget.cleanup_tolerance_seconds,
                corpus=corpus,
            )
        continuation_events = [event for event in native["lineage"]
                               if event["kind"] in {"new_sequence", "mutation"}]
        mutation_events = [event for event in continuation_events if event["kind"] == "mutation"]
        lineage_ok = (
            len(native["lineage"]) == native["completed_sequences"]
            and bool(continuation_events)
            and all(event["parents_resolved"] for event in mutation_events)
        )
        record.lineage_status = "verified" if lineage_ok else "unverified"
        metrics = segmented_metrics(fixture_id, common["warmup"], native)
        save_segmented_metrics(directory, metrics)
        record.goal_reached = any(metrics["goal_reached"].values())
        record.execution_status = "completed"
        record.evaluation_valid = (
            common["within_common_limit"] and lineage_ok
            and not any(stage.get("after_deadline") for stage in ledger.records)
        )
        record.artifacts.update({
            "common_path": str(Path(common["warmup_path"]).parents[1] / "common.json"),
            "native_report": native["output_path"],
            "lineage": native["lineage_path"],
            "coverage": str(directory / "coverage.json"),
            "states": str(directory / "states.json"),
            "metrics": str(directory / "metrics.json"),
        })
        record.outcomes = {
            "warmup_goal_reached": common["warmup_goal_reached"],
            "augmentation_accepted": len(augmentation.get("accepted", [])),
            "completed_sequences": native["completed_sequences"],
            "startup_replays": native["startup_replays"],
            "new_sequences": native["new_sequences"],
            "mutation_sequences": native["mutation_sequences"],
            "native_status": native["status"],
            "native_timing_seconds": native.get("native_timing_seconds", {}),
            "dimension_deltas": metrics["dimensions"],
        }
    except CampaignDeadlineError as error:
        record.execution_status = "campaign_deadline"
        record.failure = {"classification": "campaign_deadline", "reason": str(error)}
    except ToolExecutionError as error:
        record.execution_status = "tool_error"
        record.failure = {"classification": error.status, "reason": str(error)}
    except EvidenceMismatchError as error:
        record.execution_status = "evidence_error"
        record.failure = {"classification": error.status, "reason": str(error)}
    except (RuntimeError, ValueError, OSError, KeyError, TypeError) as error:
        record.execution_status = "tool_error"
        record.failure = {"classification": "tool_error", "reason": f"{type(error).__name__}: {error}"}
    finally:
        record.finalize(ledger)
        record.save(directory / "campaign.json")
    return record.to_dict()


def run_single(config_path: Path, fixture_id: str, arm: str, repeat_id: int,
               output: Path) -> dict:
    config = load_benchmark_config(config_path)
    if fixture_id not in config.fixtures or arm not in config.arms or repeat_id not in config.repeats:
        raise ValueError("fixture, arm, or repeat is outside the frozen benchmark config")
    output.mkdir(parents=True, exist_ok=False)
    toolchain = inspect_toolchain()
    if not toolchain["ok"]:
        raise RuntimeError("toolchain preflight failed")
    common = prepare_common(config, fixture_id, repeat_id, output / "warmup", toolchain)
    result = run_arm(config, fixture_id, repeat_id, arm, common, output / "arm")
    write_json(output / "manifest.json", benchmark_manifest(config_path, config))
    return result


def run_benchmark(config_path: Path, output: Path) -> dict:
    config = load_benchmark_config(config_path)
    output.mkdir(parents=True, exist_ok=False)
    manifest = benchmark_manifest(config_path, config)
    write_json(output / "manifest.json", manifest)
    toolchain = inspect_toolchain()
    if not toolchain["ok"]:
        raise RuntimeError("toolchain preflight failed")
    physical_started = time.monotonic()
    records = []
    for fixture_id in config.fixtures:
        for repeat_id in config.repeats:
            block = output / "blocks" / fixture_id / f"repeat-{repeat_id}"
            common = prepare_common(config, fixture_id, repeat_id, block / "warmup", toolchain)
            for arm in config.arm_orders[str(repeat_id)]:
                record = run_arm(config, fixture_id, repeat_id, arm, common, block / "arms" / arm)
                records.append(record)
    manifest["physical_elapsed_seconds"] = time.monotonic() - physical_started
    manifest["result_count"] = len(records)
    manifest["evaluation_valid_count"] = sum(record["evaluation_valid"] for record in records)
    write_json(output / "manifest.json", manifest)
    return build_benchmark_report(output)


def _campaign_paths(directory: Path) -> list[Path]:
    return sorted(directory.glob("blocks/*/repeat-*/arms/*/campaign.json"))


def _elapsed(result: dict | None) -> float:
    if not isinstance(result, dict):
        return 0.0
    command = result.get("command_result")
    return float(command.get("elapsed_seconds", 0.0)) if isinstance(command, dict) else 0.0


def _row_evidence(path: Path, record: dict) -> dict:
    arm_dir = path.parent
    block_dir = path.parents[2]
    common = read_json(block_dir / "warmup/common.json")
    warmup = read_json(block_dir / "warmup/warmup/campaign.json")
    native = read_json(arm_dir / "native/campaign.json")
    augmentation_path = arm_dir / "augmentation/augmentation.json"
    augmentation = read_json(augmentation_path) if augmentation_path.exists() else {
        "status": "not_applicable", "attempts": [], "accepted": [],
    }
    stages = {stage["name"]: stage for stage in record["stages"]}
    common_charge = float(stages["common_build_warmup_charge"]["elapsed_seconds"])

    goal_events: list[dict] = []
    warmup_timing = warmup.get("native_timing_seconds", {})
    pre_warmup = max(0.0, common_charge - float(warmup_timing.get("adapter_total", 0.0)))
    for event in warmup.get("lineage", []):
        if event.get("goal_reached") is True:
            goal_events.append({
                "stage": "warmup_native",
                "time_seconds": pre_warmup + float(warmup_timing.get("setup_before_fuzz", 0.0))
                + float(event.get("completed_offset_seconds", 0.0)),
                "time_basis": "native_sequence_completion",
                "generation_id": event.get("generation_id"),
            })

    native_stage = stages.get("native_startup_and_continuation", {})
    native_timing = native.get("native_timing_seconds", {})
    native_start = float(native_stage.get("started_offset_seconds", common_charge))
    for event in native.get("lineage", []):
        if event.get("goal_reached") is True:
            goal_events.append({
                "stage": ("native_import" if event.get("kind") == "startup_replay"
                          else "native_continuation"),
                "time_seconds": native_start + float(native_timing.get("setup_before_fuzz", 0.0))
                + float(event.get("completed_offset_seconds", 0.0)),
                "time_basis": "native_sequence_completion",
                "generation_id": event.get("generation_id"),
            })

    if augmentation.get("accepted"):
        augmentation_stage = stages.get("augmentation", {})
        goal_events.append({
            "stage": "auxiliary_concrete_validation",
            "time_seconds": float(augmentation_stage.get("finished_offset_seconds", common_charge)),
            "time_basis": "augmentation_stage_completion_upper_bound",
            "generation_id": None,
        })
    goal_events.sort(key=lambda event: event["time_seconds"])
    native_goal_events = [event for event in goal_events if event["stage"] != "auxiliary_concrete_validation"]

    accepted_hashes = {entry["medusa_hash"] for entry in augmentation.get("accepted", [])}
    selected_events = [
        event for event in native.get("lineage", [])
        if event.get("kind") == "mutation"
        and accepted_hashes.intersection(event.get("parent_hashes", []))
    ]
    used_hashes = {
        parent for event in selected_events for parent in event.get("parent_hashes", [])
        if parent in accepted_hashes
    }
    complete_by_index = {
        sequence["sequence_index"]: sequence
        for sequence in native.get("sequences", [])
        if sequence.get("is_complete_sequence") is True
    }
    seed_children = [complete_by_index[event["sequence_index"]] for event in selected_events
                     if event["sequence_index"] in complete_by_index
                     and event.get("different_child") is True and event.get("executed") is True]
    child_snapshot = snapshot(record["spec"]["fixture_id"], seed_children)
    arm_metrics = read_json(arm_dir / "metrics.json")
    base_states = {row["state_id"] for segment in ("warmup", "import")
                   for row in arm_metrics[segment]["states"]}
    base_coverage = {marker for segment in ("warmup", "import")
                     for marker in arm_metrics[segment]["coverage_markers"]}
    child_state_ids = [row["state_id"] for row in child_snapshot["states"]]
    child_state_delta = set_delta(base_states, child_state_ids)
    child_coverage_delta = set_delta(base_coverage, child_snapshot["coverage_markers"])
    write_json(arm_dir / "seed-attribution.json", {
        "schema_version": 1,
        "accepted_seed_hashes": sorted(accepted_hashes),
        "used_seed_hashes": sorted(used_hashes),
        "selected_generation_ids": [event["generation_id"] for event in selected_events],
        "different_executed_child_sequences": child_snapshot["sequence_ids"],
        "child_state_delta": child_state_delta,
        "child_coverage_delta": child_coverage_delta,
    })
    symbolic_attempts = augmentation.get("symbolic_attempts", [])
    opportunities = (len(symbolic_attempts) if record["spec"]["arm"] == "symbolic_augment"
                     else len(augmentation.get("attempts", [])))
    solver_seconds = sum(
        _elapsed(attempt.get(stage))
        for attempt in symbolic_attempts for stage in ("prefix_check", "solve")
    )
    replay_seconds = sum(_elapsed(attempt.get("replay")) for attempt in symbolic_attempts)
    augmentation_seconds = float(stages.get("augmentation", {}).get("elapsed_seconds", 0.0))
    return {
        "first_goal_stage": goal_events[0]["stage"] if goal_events else "right_censored",
        "first_goal_seconds": goal_events[0]["time_seconds"] if goal_events else None,
        "first_goal_time_basis": goal_events[0]["time_basis"] if goal_events else "budget_deadline",
        "first_native_goal_stage": native_goal_events[0]["stage"] if native_goal_events else "right_censored",
        "first_native_goal_seconds": native_goal_events[0]["time_seconds"] if native_goal_events else None,
        "right_censored": not goal_events,
        "censor_seconds": record["budget"]["budget_seconds"] if not goal_events else None,
        "candidate_opportunities": opportunities,
        "accepted_seed_count": len(accepted_hashes),
        "used_seed_count": len(used_hashes),
        "seed_parent_selections": len(selected_events),
        "different_seed_children": sum(event.get("different_child") is True for event in selected_events),
        "executed_seed_children": sum(event.get("executed") is True for event in selected_events),
        "seed_child_new_states": child_state_delta["new_count"],
        "seed_child_new_coverage": child_coverage_delta["new_count"],
        "accepted_seed_rate": (len(accepted_hashes) / opportunities if opportunities else None),
        "used_seed_rate": (len(used_hashes) / len(accepted_hashes) if accepted_hashes else None),
        "common_seconds": common_charge,
        "prefix_seconds": float(stages.get("prefix_pool", {}).get("elapsed_seconds", 0.0)),
        "augmentation_seconds": augmentation_seconds,
        "solver_seconds": solver_seconds,
        "concrete_replay_seconds": replay_seconds,
        "augmentation_other_seconds": max(0.0, augmentation_seconds - solver_seconds - replay_seconds),
        "native_restart_setup_seconds": float(native_timing.get("setup_before_fuzz", 0.0)),
        "native_startup_replay_seconds": float(native_timing.get("startup_replay", 0.0)),
        "native_continuation_seconds": float(native_timing.get("continuation", 0.0)),
    }


def _write_goal_hits_chart(summary: dict, path: Path) -> None:
    """Write a dependency-free SVG of the descriptive hit counts."""
    fixtures = ("phase_counter", "bounded_ledger", "range_gate", "workflow_gate")
    arms = (
        ("native_resume", "native", "#4c78a8"),
        ("concrete_augment", "concrete", "#f58518"),
        ("symbolic_augment", "symbolic", "#54a24b"),
    )
    width, height = 900, 390
    left, top, plot_width = 175, 60, 650
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<style>text{font-family:ui-sans-serif,system-ui,sans-serif;fill:#202124}.title{font-size:20px;font-weight:600}.label{font-size:13px}.tick{font-size:12px;fill:#5f6368}</style>',
        '<text class="title" x="24" y="30">Stage 2 goal hits by fixture and arm (n=5)</text>',
    ]
    for tick in range(6):
        x = left + plot_width * tick / 5
        lines.append(f'<line x1="{x:.1f}" y1="45" x2="{x:.1f}" y2="330" stroke="#e0e0e0"/>')
        lines.append(f'<text class="tick" x="{x:.1f}" y="350" text-anchor="middle">{tick}</text>')
    for fixture_index, fixture in enumerate(fixtures):
        base_y = top + fixture_index * 68
        lines.append(f'<text class="label" x="165" y="{base_y + 23}" text-anchor="end">{fixture}</text>')
        for arm_index, (arm, label, color) in enumerate(arms):
            group = summary["groups"][f"{fixture}:{arm}"]
            hits = int(group["goal_hits"])
            y = base_y + arm_index * 16
            bar_width = plot_width * hits / 5
            lines.append(f'<rect x="{left}" y="{y}" width="{bar_width:.1f}" height="12" rx="2" fill="{color}"/>')
            lines.append(f'<text class="tick" x="{left + bar_width + 6:.1f}" y="{y + 10}">{hits}/5</text>')
    legend_x = 210
    for arm_index, (_, label, color) in enumerate(arms):
        x = legend_x + arm_index * 170
        lines.append(f'<rect x="{x}" y="370" width="12" height="12" fill="{color}"/>')
        lines.append(f'<text class="label" x="{x + 18}" y="381">{label}</text>')
    lines.append("</svg>")
    path.write_text("\n".join(lines) + "\n")


def build_benchmark_report(directory: Path) -> dict:
    rows = []
    for path in _campaign_paths(directory):
        record = read_json(path)
        spec = record["spec"]
        deltas = record.get("outcomes", {}).get("dimension_deltas", {})
        evidence = _row_evidence(path, record)
        rows.append({
            "fixture": spec["fixture_id"], "repeat_id": spec["repeat_id"], "arm": spec["arm"],
            "evaluation_valid": record["evaluation_valid"],
            "execution_status": record["execution_status"],
            "augmentation_status": record["augmentation_status"],
            "lineage_status": record["lineage_status"],
            "goal_reached": record["goal_reached"],
            "new_sequences": deltas.get("sequences", {}).get("total", {}).get("new_count"),
            "new_states": deltas.get("states", {}).get("total", {}).get("new_count"),
            "new_coverage": deltas.get("coverage", {}).get("total", {}).get("new_count"),
            "continuation_new_states": deltas.get("states", {}).get("continuation", {}).get("new_count"),
            "continuation_new_coverage": deltas.get("coverage", {}).get("continuation", {}).get("new_count"),
            "accepted_seeds": record.get("outcomes", {}).get("augmentation_accepted", 0),
            "charged_wall_seconds": record.get("budget", {}).get("charged_wall_seconds"),
            **evidence,
            "record_path": str(path.relative_to(directory)),
        })
    summary = {
        "schema_version": 1,
        "result_count": len(rows),
        "evaluation_valid_count": sum(row["evaluation_valid"] for row in rows),
        "rows": rows,
        "groups": {},
    }
    for row in rows:
        key = f"{row['fixture']}:{row['arm']}"
        group = summary["groups"].setdefault(key, {
            "fixture": row["fixture"], "arm": row["arm"], "runs": 0, "valid": 0,
            "goal_hits": 0, "right_censored": 0,
            "new_states": [], "new_coverage": [], "continuation_new_states": [],
            "continuation_new_coverage": [], "accepted_seeds": [], "used_seeds": [],
            "seed_parent_selections": [], "seed_child_new_states": [],
            "seed_child_new_coverage": [], "charged_wall_seconds": [],
            "augmentation_seconds": [], "native_continuation_seconds": [],
        })
        group["runs"] += 1
        group["valid"] += int(row["evaluation_valid"])
        group["goal_hits"] += int(row["goal_reached"])
        group["right_censored"] += int(row["right_censored"])
        mappings = {
            "new_states": "new_states", "new_coverage": "new_coverage",
            "continuation_new_states": "continuation_new_states",
            "continuation_new_coverage": "continuation_new_coverage",
            "accepted_seeds": "accepted_seed_count", "used_seeds": "used_seed_count",
            "seed_parent_selections": "seed_parent_selections",
            "seed_child_new_states": "seed_child_new_states",
            "seed_child_new_coverage": "seed_child_new_coverage",
            "charged_wall_seconds": "charged_wall_seconds",
            "augmentation_seconds": "augmentation_seconds",
            "native_continuation_seconds": "native_continuation_seconds",
        }
        for key_name, row_name in mappings.items():
            if row[row_name] is not None:
                group[key_name].append(row[row_name])
    write_json(directory / "summary.json", summary)
    _write_goal_hits_chart(summary, directory / "goal-hits.svg")
    if rows:
        with (directory / "summary.csv").open("w", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    lines = ["# Stage 2 benchmark report", "", "Local teaching-state-machine exploration only; this report does not claim vulnerabilities.", "",
             f"Valid results: **{summary['evaluation_valid_count']} / {summary['result_count']}**", "",
             "![Goal hits across five repeats](goal-hits.svg)", "",
             "| Fixture | Arm | Valid | Goal hits | New states | New coverage | Accepted/used seeds |",
             "| --- | --- | ---: | ---: | --- | --- | --- |"]
    for group in summary["groups"].values():
        lines.append(f"| {group['fixture']} | {group['arm']} | {group['valid']}/{group['runs']} | "
                     f"{group['goal_hits']}/{group['runs']} | {group['new_states']} | {group['new_coverage']} | "
                     f"{group['accepted_seeds']} / {group['used_seeds']} |")
    lines.extend(["", "Per-run first-hit stage/time, right-censored misses, import and continuation deltas, seed selections, and all charged costs are in `summary.json` and `summary.csv`.", ""])
    (directory / "summary.md").write_text("\n".join(lines))
    return summary
