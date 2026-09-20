#!/usr/bin/env python3
"""Build the small, path-sanitized Stage 2 evidence bundle from preserved runs."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from seedbridge.io import read_json, write_json  # noqa: E402


RUNS = ROOT / "runs"
DESTINATION = ROOT / "evidence/stage2"


def _sanitize(value: object) -> object:
    if isinstance(value, str):
        root = f"{ROOT}/"
        return value.replace(root, "") if value.startswith(root) else value
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    return value


def _complete_sequence(report: dict, index: int) -> dict:
    return next(sequence for sequence in report["sequences"]
                if sequence.get("sequence_index") == index
                and sequence.get("is_complete_sequence") is True)


def _sequence_projection(report: dict) -> dict:
    sequence = next(item for item in report["sequences"] if item.get("is_complete_sequence"))
    return {
        "medusa_hash": sequence["medusa_hash"],
        "native_digest": sequence["native_digest"],
        "steps": sequence["steps"],
        "coverage_branches": report["coverage_branches"],
        "coverage_digest_sha256": report["coverage_digest_sha256"],
    }


def build() -> None:
    if DESTINATION.exists():
        shutil.rmtree(DESTINATION)
    DESTINATION.mkdir(parents=True)

    formal = RUNS / "stage2-formal-02"
    shutil.copy2(ROOT / "configs/stage2-benchmark.json", DESTINATION / "benchmark-config.json")
    for name in ("summary.json", "summary.csv", "summary.md", "goal-hits.svg", "audit.json"):
        shutil.copy2(formal / name, DESTINATION / name)

    manifest = read_json(formal / "manifest.json")
    manifest.get("host", {}).pop("hostname", None)
    write_json(DESTINATION / "manifest.json", _sanitize(manifest))

    mechanism = read_json(RUNS / "stage2-p1-mechanism/campaign-01.json")
    event = next(event for event in mechanism["lineage"]
                 if event.get("kind") == "mutation"
                 and event.get("imported_parent") is True
                 and event.get("different_child") is True
                 and event.get("executed") is True)
    parent_hash = event["parent_hashes"][0]
    imported_selections = [row for row in mechanism["lineage"]
                           if parent_hash in (row.get("parent_hashes") or [])]
    mechanism_summary = {
        "schema_version": 1,
        "fixture": mechanism["fixture"],
        "completed_sequences": mechanism["completed_sequences"],
        "startup_replays": mechanism["startup_replays"],
        "new_sequences": mechanism["new_sequences"],
        "mutation_sequences": mechanism["mutation_sequences"],
        "imported_seed_hash": parent_hash,
        "imported_seed_parent_selections": len(imported_selections),
        "different_executed_children": sum(
            row.get("different_child") is True and row.get("executed") is True
            for row in imported_selections
        ),
        "representative_event": event,
        "representative_child": _complete_sequence(mechanism, event["sequence_index"]),
    }
    write_json(DESTINATION / "mechanism.json", _sanitize(mechanism_summary))
    shutil.copy2(RUNS / "stage2-p1-mechanism/corpus/call_sequences/symbolic-seed.json",
                 DESTINATION / "mechanism-parent-seed.json")
    child_path = RUNS / "stage2-p1-mechanism/campaign-01.native" / (
        f"sequence-{event['sequence_index']:05d}-prefix-4.json")
    shutil.copy2(child_path, DESTINATION / "mechanism-child-sequence.json")

    recording_on = read_json(RUNS / "stage2-p1-recording-on/campaign.json")
    recording_off = read_json(RUNS / "stage2-p1-recording-off/campaign.json")
    on_projection = _sequence_projection(recording_on)
    off_projection = _sequence_projection(recording_off)
    write_json(DESTINATION / "recording-neutrality.json", {
        "schema_version": 1,
        "same_startup_replay_projection": on_projection == off_projection,
        "recording_on_lineage_events": len(recording_on.get("lineage", [])),
        "recording_off_lineage_events": len(recording_off.get("lineage", [])),
        "recording_on_enabled": recording_on["lineage_enabled"],
        "recording_off_enabled": recording_off["lineage_enabled"],
        "projection": on_projection,
    })

    p2 = []
    for name in ("range", "workflow"):
        report_path = RUNS / f"stage2-p2-{name}-stage1/report.json"
        report = read_json(report_path)
        p2.append({
            "fixture_id": report["fixture_id"],
            "status": report["status"],
            "attempts": len(report.get("attempts", [])),
            "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        })
    write_json(DESTINATION / "new-fixture-stage1-validation.json",
               {"schema_version": 1, "results": p2})

    smoke = []
    smoke_root = RUNS / "stage2-p4-smoke-05/arms"
    for arm_dir in sorted(smoke_root.iterdir()):
        record = read_json(arm_dir / "campaign.json")
        smoke.append({
            "arm": record["spec"]["arm"],
            "evaluation_valid": record["evaluation_valid"],
            "execution_status": record["execution_status"],
            "augmentation_status": record["augmentation_status"],
            "lineage_status": record["lineage_status"],
            "goal_reached": record["goal_reached"],
            "charged_wall_seconds": record["budget"]["charged_wall_seconds"],
            "accepted_seeds": record["outcomes"]["augmentation_accepted"],
        })
    write_json(DESTINATION / "three-arm-smoke.json", {"schema_version": 1, "results": smoke})

    sample_arm = formal / "blocks/phase_counter/repeat-1/arms/symbolic_augment"
    sample_record = read_json(sample_arm / "campaign.json")
    sample_augmentation = read_json(sample_arm / "augmentation/augmentation.json")
    sample_native = read_json(sample_arm / "native/campaign.json")
    accepted = [{key: row[key] for key in (
        "argument", "case_id", "medusa_hash", "policy", "prefix_index",
        "sequence_identity", "validation_status")}
        for row in sample_augmentation["accepted"]]
    accepted_hashes = {row["medusa_hash"] for row in accepted}
    selected = [event for event in sample_native["lineage"]
                if event.get("kind") == "mutation"
                and accepted_hashes.intersection(event.get("parent_hashes") or [])]
    if len(selected) != 170 or not selected:
        raise ValueError("formal symbolic sample must contain 170 mutation parent selections")
    write_json(DESTINATION / "formal-symbolic-sample.json", _sanitize({
        "schema_version": 1,
        "spec": sample_record["spec"],
        "execution_status": sample_record["execution_status"],
        "augmentation_status": sample_record["augmentation_status"],
        "lineage_status": sample_record["lineage_status"],
        "evaluation_valid": sample_record["evaluation_valid"],
        "goal_reached": sample_record["goal_reached"],
        "budget": sample_record["budget"],
        "stages": sample_record["stages"],
        "accepted": accepted,
        "selected_as_parent_count": len(selected),
        "different_executed_child_count": sum(
            event.get("different_child") is True and event.get("executed") is True
            for event in selected),
        "first_selected_event": selected[0],
        "seed_attribution": read_json(sample_arm / "seed-attribution.json"),
    }))

    write_json(DESTINATION / "superseded-run.json", {
        "schema_version": 1,
        "run": "runs/stage2-formal-01",
        "status": "superseded",
        "selected_for_summary": False,
        "valid_results": 56,
        "planned_results": 60,
        "reason": (
            "Four symbolic campaigns crossed the deadline boundary while cleanup errors escaped. "
            "The complete matrix was rerun after process cleanup and deadline-result handling fixes."
        ),
        "replacement": "runs/stage2-formal-02",
    })

    index = """# Stage 2 evidence index

This bundle is a small, path-sanitized extract of the preserved local runs. The full raw runs remain under `runs/` and are intentionally excluded from Git because they contain more than 127,000 generated files.

| File | Evidence |
| --- | --- |
| `benchmark-config.json` | Frozen four-fixture, five-repeat, three-arm matrix and budgets |
| `manifest.json` | Tool, patch, fixture and config hashes; run order and randomness boundary |
| `summary.{json,csv,md}` | All 60 selected results and grouped outcomes |
| `goal-hits.svg` | Descriptive goal-hit chart generated by the offline reporter |
| `audit.json` | Independent raw-record audit and recomputation counts |
| `mechanism.json` | Imported symbolic seed, actual parent selection, different child and execution event |
| `mechanism-parent-seed.json` / `mechanism-child-sequence.json` | Exact native Medusa inputs for the representative lineage edge |
| `recording-neutrality.json` | Recording-on/off comparison for the same concrete replay |
| `new-fixture-stage1-validation.json` | Stage 1 core-flow status for both added fixtures |
| `three-arm-smoke.json` | Common-warmup smoke result for all three strategies |
| `formal-symbolic-sample.json` | One selected formal arm with budget, seed and lineage attribution |
| `superseded-run.json` | Preserved first formal attempt and why it is excluded |
| `checksums.sha256` | SHA-256 for every other file in this bundle |

The benchmark covers repository-owned teaching state machines. Goal reachability is not a vulnerability finding, and the results do not establish performance on third-party contracts.
"""
    (DESTINATION / "INDEX.md").write_text(index)

    lines = []
    for path in sorted(DESTINATION.rglob("*")):
        if path.is_file() and path.name != "checksums.sha256":
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  {path.relative_to(DESTINATION)}")
    (DESTINATION / "checksums.sha256").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    build()
    print(DESTINATION)
