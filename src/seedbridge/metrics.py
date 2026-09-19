"""Offline-recomputable Stage 2 sequence, state, and native coverage metrics."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Iterable

from .config import get_scenario
from .io import write_json


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def normalized_sequence_identity(steps: list[dict]) -> str:
    """Hash call structure and calldata while excluding nonce and timing metadata."""
    projection = []
    for step in steps:
        projection.append({
            "from": str(step["from"]).lower(),
            "to": str(step["to"]).lower(),
            "value": str(step["value"]),
            "calldata": str(step["calldata"]).lower(),
        })
    return _digest(projection)


def projected_state(fixture_id: str, observation: list[object]) -> dict:
    scenario = get_scenario(fixture_id)
    if not isinstance(observation, list) or len(observation) != 4 or type(observation[3]) is not bool:
        raise ValueError("state observation must contain three integers and a boolean")
    values: list[int | bool] = []
    for index, (low, high) in enumerate(scenario.state_bounds):
        value = observation[index]
        if isinstance(value, bool):
            raise ValueError("numeric state projection cannot contain a boolean")
        try:
            number = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError("numeric state projection is not an integer") from error
        if not low <= number <= high:
            raise ValueError(f"state projection field {index} is outside its declared finite domain")
        values.append(number)
    values.append(observation[3])
    return {name: value for name, value in zip(scenario.state_fields, values)}


def projected_state_identity(fixture_id: str, observation: list[object]) -> str:
    return _digest(projected_state(fixture_id, observation))


def _complete_sequences(report: dict) -> list[dict]:
    return [sequence for sequence in report.get("sequences", [])
            if sequence.get("is_complete_sequence") is True]


def snapshot(fixture_id: str, sequences: Iterable[dict]) -> dict:
    sequence_ids: set[str] = set()
    state_rows: dict[str, dict] = {}
    coverage: set[str] = set()
    hits: Counter[str] = Counter()
    goal_reached = False
    for sequence in sequences:
        steps = sequence.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError("complete sequence is missing executed steps")
        sequence_ids.add(normalized_sequence_identity(steps))
        for step in steps:
            state = projected_state(fixture_id, step["observe"])
            state_rows[_digest(state)] = state
            goal_reached = goal_reached or bool(state["goal"])
            markers = step.get("coverage_markers")
            marker_hits = step.get("coverage_marker_hits")
            if not isinstance(markers, list) or not isinstance(marker_hits, dict):
                raise ValueError("native marker set and hit counts are required")
            if set(markers) != set(marker_hits):
                raise ValueError("coverage marker set and hit-count keys disagree")
            coverage.update(markers)
            for marker, count in marker_hits.items():
                if type(count) is not int or count < 1:
                    raise ValueError("coverage hit count must be a positive integer")
                hits[marker] += count
    return {
        "sequence_ids": sorted(sequence_ids),
        "states": [{"state_id": key, "projection": state_rows[key]} for key in sorted(state_rows)],
        "coverage_markers": sorted(coverage),
        "coverage_marker_hits": dict(sorted(hits.items())),
        "goal_reached": goal_reached,
    }


def set_delta(base: Iterable[str], addition: Iterable[str]) -> dict:
    base_set, addition_set = set(base), set(addition)
    return {
        "base_count": len(base_set),
        "segment_count": len(addition_set),
        "new_count": len(addition_set - base_set),
        "new_items": sorted(addition_set - base_set),
        "union_count": len(base_set | addition_set),
    }


def segmented_metrics(fixture_id: str, warmup_report: dict, campaign_report: dict) -> dict:
    warmup = snapshot(fixture_id, _complete_sequences(warmup_report))
    lineage = campaign_report.get("lineage")
    if not isinstance(lineage, list) or len(lineage) != campaign_report.get("completed_sequences"):
        raise ValueError("campaign lineage does not cover every completed sequence")
    kinds = {event["sequence_index"]: event["kind"] for event in lineage}
    complete = _complete_sequences(campaign_report)
    imports = snapshot(fixture_id, (s for s in complete if kinds.get(s["sequence_index"]) == "startup_replay"))
    continuation = snapshot(fixture_id, (s for s in complete if kinds.get(s["sequence_index"]) in {"new_sequence", "mutation"}))

    def ids(value: dict, key: str) -> list[str]:
        if key == "states":
            return [row["state_id"] for row in value[key]]
        return value[key]

    dimensions = {}
    for name, key in (("sequences", "sequence_ids"), ("states", "states"),
                      ("coverage", "coverage_markers")):
        warmup_ids = ids(warmup, key)
        import_ids = ids(imports, key)
        continuation_ids = ids(continuation, key)
        after_import = set(warmup_ids) | set(import_ids)
        dimensions[name] = {
            "import": set_delta(warmup_ids, import_ids),
            "continuation": set_delta(after_import, continuation_ids),
            "total": set_delta(warmup_ids, set(import_ids) | set(continuation_ids)),
        }

    seed_use: dict[str, dict[str, int]] = {}
    for event in lineage:
        if event.get("kind") != "mutation":
            continue
        for parent in event.get("parent_hashes", []):
            row = seed_use.setdefault(parent, {"selected": 0, "different_child": 0, "child_executed": 0})
            row["selected"] += 1
            row["different_child"] += int(event.get("different_child") is True)
            row["child_executed"] += int(event.get("executed") is True)

    return {
        "schema_version": 1,
        "fixture_id": fixture_id,
        "warmup": warmup,
        "import": imports,
        "continuation": continuation,
        "dimensions": dimensions,
        "seed_use": dict(sorted(seed_use.items())),
        "goal_reached": {
            "warmup": warmup["goal_reached"],
            "import": imports["goal_reached"],
            "continuation": continuation["goal_reached"],
        },
    }


def save_segmented_metrics(directory: Path, metrics: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / "metrics.json", metrics)
    write_json(directory / "coverage.json", {
        "schema_version": 1,
        "fixture_id": metrics["fixture_id"],
        "warmup": metrics["warmup"]["coverage_markers"],
        "import": metrics["import"]["coverage_markers"],
        "continuation": metrics["continuation"]["coverage_markers"],
        "hit_counts": {
            name: metrics[name]["coverage_marker_hits"]
            for name in ("warmup", "import", "continuation")
        },
        "deltas": metrics["dimensions"]["coverage"],
    })
    write_json(directory / "states.json", {
        "schema_version": 1,
        "fixture_id": metrics["fixture_id"],
        "projection": get_scenario(metrics["fixture_id"]).to_dict()["state_projection"],
        "warmup": metrics["warmup"]["states"],
        "import": metrics["import"]["states"],
        "continuation": metrics["continuation"]["states"],
        "deltas": metrics["dimensions"]["states"],
    })
