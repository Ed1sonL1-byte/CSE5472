#!/usr/bin/env python3
"""Independently audit a completed Stage 2 benchmark from preserved raw records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from seedbridge.io import read_json, write_json  # noqa: E402
from seedbridge.metrics import segmented_metrics  # noqa: E402


FIXTURES = {"phase_counter", "bounded_ledger", "range_gate", "workflow_gate"}
ARMS = {"native_resume", "concrete_augment", "symbolic_augment"}
REPEATS = {1, 2, 3, 4, 5}


def _lineage_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def audit(directory: Path) -> dict:
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    campaign_paths = sorted(directory.glob("blocks/*/repeat-*/arms/*/campaign.json"))
    expected = {(fixture, repeat, arm) for fixture in FIXTURES
                for repeat in REPEATS for arm in ARMS}
    actual: set[tuple[str, int, str]] = set()
    recomputed = 0
    lineage_events = 0
    mutation_events = 0
    accepted_seeds = 0
    used_seeds: set[tuple[str, int, str, str]] = set()
    complete_sequences = 0

    for record_path in campaign_paths:
        record = read_json(record_path)
        spec = record.get("spec", {})
        fixture = spec.get("fixture_id")
        repeat = spec.get("repeat_id")
        arm = spec.get("arm")
        label = f"{fixture}/repeat-{repeat}/{arm}"
        actual.add((fixture, repeat, arm))

        require(record.get("evaluation_valid") is True, f"{label}: evaluation is invalid")
        require(record.get("execution_status") == "completed", f"{label}: execution did not complete")
        require(record.get("lineage_status") == "verified", f"{label}: lineage is not verified")
        require(spec.get("worker_count") == 1, f"{label}: worker count changed")
        require(spec.get("call_value") == "0", f"{label}: call value changed")

        budget = record.get("budget", {})
        budget_seconds = float(budget.get("budget_seconds", -1))
        charged = float(budget.get("charged_wall_seconds", budget_seconds + 1))
        require(charged <= budget_seconds + 1e-6, f"{label}: charged time exceeds budget")
        stages = record.get("stages", [])
        require(bool(stages), f"{label}: missing stage timings")
        require(all(stage.get("after_deadline") is False for stage in stages),
                f"{label}: a stage crossed the campaign deadline")
        require(all(float(stage.get("finished_offset_seconds", budget_seconds + 1))
                    <= budget_seconds + 1e-6 for stage in stages),
                f"{label}: a stage ended after the campaign budget")
        require(all(float(stages[index - 1]["finished_offset_seconds"])
                    <= float(stages[index]["started_offset_seconds"]) + 1e-6
                    for index in range(1, len(stages))),
                f"{label}: charged stages overlap")

        arm_dir = record_path.parent
        block_dir = record_path.parents[2]
        native = read_json(arm_dir / "native/campaign.json")
        warmup = read_json(block_dir / "warmup/warmup/campaign.json")
        saved_metrics = read_json(arm_dir / "metrics.json")
        lineage = native.get("lineage", [])
        completed = int(native.get("completed_sequences", -1))
        complete = [sequence for sequence in native.get("sequences", [])
                    if sequence.get("is_complete_sequence") is True]
        lineage_events += len(lineage)
        complete_sequences += len(complete)
        require(len(lineage) == completed, f"{label}: lineage count does not match completed count")
        require(len(complete) == completed, f"{label}: complete sequence count does not match")
        require(completed == int(native.get("startup_replays", -1))
                + int(native.get("new_sequences", -1))
                + int(native.get("mutation_sequences", -1)),
                f"{label}: generation-kind counts do not sum to completed count")
        require([event.get("generation_id") for event in lineage] == list(range(1, completed + 1)),
                f"{label}: generation ids are not contiguous")
        require(_lineage_jsonl(arm_dir / "native/lineage.jsonl") == lineage,
                f"{label}: JSONL lineage differs from the campaign report")

        known_outputs: set[str] = set()
        for event in lineage:
            kind = event.get("kind")
            require(kind in {"startup_replay", "new_sequence", "mutation"},
                    f"{label}: unknown lineage generation kind")
            output_hash = event.get("output_hash")
            require(isinstance(output_hash, str) and output_hash.startswith("0x"),
                    f"{label}: lineage event has no native output hash")
            if kind == "mutation":
                mutation_events += 1
                require(bool(event.get("parent_hashes")), f"{label}: mutation has no actual parent")
                require(event.get("parents_resolved") is True,
                        f"{label}: mutation parent was not resolved")
                require(all(parent in known_outputs for parent in event.get("parent_hashes", [])),
                        f"{label}: mutation parent has no earlier executed source")
            require(event.get("executed") is True, f"{label}: lineage event was not executed")
            known_outputs.add(output_hash)

        runtime_digest = native.get("build", {}).get("runtime_bytecode_sha256")
        require(isinstance(runtime_digest, str) and len(runtime_digest) == 64,
                f"{label}: missing runtime bytecode digest")
        for sequence in complete:
            for step in sequence.get("steps", []):
                markers = step.get("coverage_markers", [])
                hits = step.get("coverage_marker_hits", {})
                require(set(markers) == set(hits), f"{label}: marker and hit-count keys differ")
                require(all(marker.startswith(f"{runtime_digest}:") for marker in markers),
                        f"{label}: coverage marker belongs to another runtime bytecode")
                require(all(type(count) is int and count > 0 for count in hits.values()),
                        f"{label}: invalid coverage hit count")
                require(step.get("observer_state_unchanged") is True,
                        f"{label}: state observation changed the persistent state root")
                require(str(step.get("from", "")).lower()
                        == "0x0000000000000000000000000000000000010000",
                        f"{label}: executed call used another actor")
                require(str(step.get("value")) == "0", f"{label}: executed call used nonzero value")
        report_markers = native.get("coverage_markers", [])
        report_hits = native.get("coverage_marker_hits", {})
        require(set(report_markers) == set(report_hits),
                f"{label}: report marker and hit-count keys differ")
        require(len(report_markers) == native.get("coverage_branches"),
                f"{label}: report marker count differs from native branch count")
        require(all(marker.startswith(f"{runtime_digest}:") for marker in report_markers),
                f"{label}: report coverage includes another runtime bytecode")

        try:
            rebuilt_metrics = segmented_metrics(fixture, warmup, native)
        except (KeyError, TypeError, ValueError) as error:
            errors.append(f"{label}: metric recomputation failed: {error}")
        else:
            recomputed += 1
            require(rebuilt_metrics == saved_metrics, f"{label}: saved metrics differ from recomputation")
            require(record.get("goal_reached") == any(rebuilt_metrics["goal_reached"].values()),
                    f"{label}: goal outcome differs from raw state observations")

        augmentation_path = arm_dir / "augmentation/augmentation.json"
        augmentation = read_json(augmentation_path) if augmentation_path.exists() else {"accepted": []}
        accepted = augmentation.get("accepted", [])
        accepted_hashes = {entry.get("medusa_hash") for entry in accepted}
        require(all(isinstance(seed_hash, str) and seed_hash.startswith("0x")
                    for seed_hash in accepted_hashes),
                f"{label}: accepted seed is missing its native hash")
        accepted_seeds += len(accepted_hashes)
        warmup_hashes = {event.get("output_hash") for event in warmup.get("lineage", [])}
        require(accepted_hashes.isdisjoint(warmup_hashes),
                f"{label}: an accepted augmentation duplicates a warmup sequence")
        startup_hashes = {event.get("output_hash") for event in lineage
                          if event.get("kind") == "startup_replay"}
        require(accepted_hashes.issubset(startup_hashes),
                f"{label}: accepted seed was not actually replayed at native startup")
        require(len(accepted_hashes) == record.get("outcomes", {}).get("augmentation_accepted"),
                f"{label}: campaign accepted-seed count differs from augmentation evidence")
        for seed_hash in accepted_hashes:
            selected = [event for event in lineage if event.get("kind") == "mutation"
                        and seed_hash in event.get("parent_hashes", [])]
            require(any(event.get("different_child") is True and event.get("executed") is True
                        for event in selected),
                    f"{label}: accepted seed was not used for a different executed child")
            if selected:
                used_seeds.add((fixture, repeat, arm, seed_hash))

        attribution_path = arm_dir / "seed-attribution.json"
        require(attribution_path.exists(), f"{label}: seed attribution file is missing")
        if attribution_path.exists():
            attribution = read_json(attribution_path)
            require(set(attribution.get("accepted_seed_hashes", [])) == accepted_hashes,
                    f"{label}: seed attribution accepted set differs")

    require(len(campaign_paths) == 60, f"expected 60 campaign records, found {len(campaign_paths)}")
    require(actual == expected, "campaign matrix does not equal 4 fixtures x 5 repeats x 3 arms")

    common_paths = sorted(directory.glob("blocks/*/repeat-*/warmup/common.json"))
    require(len(common_paths) == 20, f"expected 20 shared warmups, found {len(common_paths)}")
    for common_path in common_paths:
        common = read_json(common_path)
        require(common.get("within_common_limit") is True,
                f"{common_path.relative_to(directory)}: common work exceeded its limit")
        warmup = read_json(common_path.parent / "warmup/campaign.json")
        require(len(warmup.get("lineage", [])) == warmup.get("completed_sequences"),
                f"{common_path.relative_to(directory)}: warmup lineage is incomplete")

    summary_path = directory / "summary.json"
    require(summary_path.exists(), "summary.json is missing")
    if summary_path.exists():
        summary = read_json(summary_path)
        require(summary.get("result_count") == 60, "summary result count is not 60")
        require(summary.get("evaluation_valid_count") == 60, "summary valid count is not 60")
        require(len(summary.get("rows", [])) == 60, "summary does not contain 60 rows")

    result = {
        "schema_version": 1,
        "status": "passed" if not errors else "failed",
        "checks": {
            "campaign_records": len(campaign_paths),
            "shared_warmups": len(common_paths),
            "metrics_recomputed": recomputed,
            "lineage_events": lineage_events,
            "mutation_events": mutation_events,
            "complete_sequences": complete_sequences,
            "accepted_seeds": accepted_seeds,
            "accepted_seeds_used": len(used_seeds),
        },
        "errors": errors,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.benchmark.resolve())
    if args.output:
        write_json(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
