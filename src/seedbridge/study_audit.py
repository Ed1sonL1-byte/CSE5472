"""Independent, standard-library-only audit of a stored Stage 3 study."""

from __future__ import annotations

import base64
from collections import Counter
import csv
import gzip
import hashlib
import json
from pathlib import Path
import time


ACTOR = "0x0000000000000000000000000000000000010000"
FIXTURES = {
    "phase_counter": {
        "fields": ("phase", "counter", "unused", "goal"),
        "bounds": ((0, 3), (0, 19), (0, 0)),
        "calls": {"begin()", "advance(uint256)", "complete(uint256)"},
    },
    "bounded_ledger": {
        "fields": ("phase", "total", "reserved", "goal"),
        "bounds": ((0, 3), (0, 30), (0, 23)),
        "calls": {"open()", "reserve(uint256)", "settle(uint256)"},
    },
    "range_gate": {
        "fields": ("phase", "bound", "offset", "goal"),
        "bounds": ((0, 3), (0, 30), (0, 32)),
        "calls": {"begin()", "configure(uint256)", "passRange(uint256)"},
    },
    "workflow_gate": {
        "fields": ("phase", "lane", "progress", "goal"),
        "bounds": ((0, 5), (0, 3), (0, 4)),
        "calls": {"start()", "choose(uint256)", "unlock(uint256)", "continueWork(uint256)"},
    },
}


class StudyAuditError(ValueError):
    pass


def _read(path: Path) -> dict:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise StudyAuditError(f"JSON object required: {path}")
    return value


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _sequence_identity(steps: list[dict]) -> str:
    return _digest([
        {
            "from": str(step["from"]).lower(),
            "to": str(step["to"]).lower(),
            "value": str(step["value"]),
            "calldata": str(step["calldata"]).lower(),
        }
        for step in steps
    ])


def _state(fixture: str, observation: object) -> dict:
    definition = FIXTURES[fixture]
    if not isinstance(observation, list) or len(observation) != 4 or type(observation[3]) is not bool:
        raise StudyAuditError(f"{fixture}: invalid finite-state observation")
    values: list[int | bool] = []
    for index, (low, high) in enumerate(definition["bounds"]):
        if isinstance(observation[index], bool):
            raise StudyAuditError(f"{fixture}: boolean in numeric state field")
        try:
            number = int(observation[index])
        except (TypeError, ValueError) as error:
            raise StudyAuditError(f"{fixture}: noninteger state field") from error
        if not low <= number <= high:
            raise StudyAuditError(f"{fixture}: projected state outside frozen bounds")
        values.append(number)
    values.append(observation[3])
    return dict(zip(definition["fields"], values))


def _validate_steps(fixture: str, steps: object) -> None:
    if not isinstance(steps, list) or not 1 <= len(steps) <= 4:
        raise StudyAuditError(f"{fixture}: complete sequence has invalid step count")
    for step in steps:
        if (step.get("signature") not in FIXTURES[fixture]["calls"]
                or str(step.get("from", "")).lower() != ACTOR
                or str(step.get("value")) != "0"):
            raise StudyAuditError(f"{fixture}: caller, value, or call signature left the frozen scope")
        if (step.get("invariant_holds") is not True
                or step.get("observer_state_unchanged") is not True
                or step.get("state_root_before_observer") != step.get("state_root_after_observer")):
            raise StudyAuditError(f"{fixture}: observer or invariant marker is invalid")
        _state(fixture, step.get("observe"))
        markers = step.get("coverage_markers")
        hits = step.get("coverage_marker_hits")
        if (not isinstance(markers, list) or not isinstance(hits, dict)
                or set(markers) != set(hits)
                or any(type(count) is not int or count < 1 for count in hits.values())):
            raise StudyAuditError(f"{fixture}: native coverage markers are invalid")
        if step.get("success") is not (step.get("status") == "success"):
            raise StudyAuditError(f"{fixture}: step outcome fields disagree")


def _snapshot(fixture: str, sequences: list[dict]) -> dict:
    sequence_ids: set[str] = set()
    states: dict[str, dict] = {}
    markers: set[str] = set()
    hits: Counter[str] = Counter()
    goal = False
    for sequence in sequences:
        steps = sequence["steps"]
        _validate_steps(fixture, steps)
        sequence_ids.add(_sequence_identity(steps))
        for step in steps:
            state = _state(fixture, step["observe"])
            states[_digest(state)] = state
            goal = goal or state["goal"]
            markers.update(step["coverage_markers"])
            hits.update(step["coverage_marker_hits"])
    return {
        "sequence_ids": sorted(sequence_ids),
        "states": [{"state_id": key, "projection": states[key]} for key in sorted(states)],
        "coverage_markers": sorted(markers),
        "coverage_marker_hits": dict(sorted(hits.items())),
        "goal_reached": goal,
    }


def _delta(base: list[str], addition: list[str]) -> dict:
    left, right = set(base), set(addition)
    return {
        "base_count": len(left),
        "segment_count": len(right),
        "new_count": len(right - left),
        "new_items": sorted(right - left),
        "union_count": len(left | right),
    }


def _metrics(fixture: str, warmup: list[dict], imports: list[dict],
             continuation: list[dict], lineage: list[dict]) -> dict:
    snapshots = {
        "warmup": _snapshot(fixture, warmup),
        "import": _snapshot(fixture, imports),
        "continuation": _snapshot(fixture, continuation),
    }
    dimensions = {}
    for name, key in (("sequences", "sequence_ids"), ("states", "states"),
                      ("coverage", "coverage_markers")):
        def ids(segment: str) -> list[str]:
            values = snapshots[segment][key]
            return [row["state_id"] for row in values] if key == "states" else values

        baseline = ids("warmup")
        imported = ids("import")
        continued = ids("continuation")
        dimensions[name] = {
            "import": _delta(baseline, imported),
            "continuation": _delta(sorted(set(baseline) | set(imported)), continued),
            "total": _delta(baseline, sorted(set(imported) | set(continued))),
        }
    seed_use: dict[str, dict[str, int]] = {}
    for event in lineage:
        if event["kind"] != "mutation":
            continue
        for parent in event["parent_hashes"]:
            row = seed_use.setdefault(
                parent, {"selected": 0, "different_child": 0, "child_executed": 0})
            row["selected"] += 1
            row["different_child"] += int(event["different_child"] is True)
            row["child_executed"] += int(event["executed"] is True)
    return {
        "schema_version": 1,
        "fixture_id": fixture,
        **snapshots,
        "dimensions": dimensions,
        "seed_use": dict(sorted(seed_use.items())),
        "goal_reached": {
            segment: snapshots[segment]["goal_reached"]
            for segment in ("warmup", "import", "continuation")
        },
    }


def _read_compact(path: Path, metadata: dict, fixture: str, *,
                  search_started: float, budget: float) -> dict:
    if (metadata.get("schema_version") != 2 or metadata.get("encoding") != "gzip-jsonl"
            or metadata.get("compressed_bytes") != path.stat().st_size
            or metadata.get("sha256") != _sha(path)):
        raise StudyAuditError(f"compact metadata mismatch: {path}")
    seen_indices: set[int] = set()
    known_prefixes: dict[str, str] = {}
    complete = []
    partial = []
    lineage = []
    late = []
    first_goal: dict | None = None
    eof = None
    with gzip.open(path, "rt", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            event = json.loads(line)
            if not isinstance(event, dict) or event.get("schema_version") != 2:
                raise StudyAuditError(f"bad compact schema at {path}:{line_number}")
            if eof is not None:
                raise StudyAuditError(f"record after EOF: {path}")
            if event.get("record_type") == "eof":
                eof = event
                continue
            if event.get("record_type") not in {"sequence", "partial"}:
                raise StudyAuditError(f"unknown compact record at {path}:{line_number}")
            sequence = event.get("sequence")
            index = sequence.get("sequence_index") if isinstance(sequence, dict) else None
            if type(index) is not int or index in seen_indices:
                raise StudyAuditError(f"duplicate or absent sequence ID at {path}:{line_number}")
            seen_indices.add(index)
            try:
                payload = base64.b64decode(event["native_payload_base64"], validate=True)
            except Exception as error:
                raise StudyAuditError(f"invalid native payload at {path}:{line_number}") from error
            if hashlib.sha256(payload).hexdigest() != sequence.get("native_digest"):
                raise StudyAuditError(f"native payload digest mismatch at {path}:{line_number}")
            try:
                native = json.loads(payload)
            except Exception as error:
                raise StudyAuditError(f"native payload is not JSON at {path}:{line_number}") from error
            if not isinstance(native, list) or not 1 <= len(native) <= 4:
                raise StudyAuditError(f"native payload is not a short sequence at {path}:{line_number}")
            refs = event.get("prefix_references")
            if not isinstance(refs, list) or not refs:
                raise StudyAuditError(f"missing prefix dictionary at {path}:{line_number}")
            hashes = []
            for position, reference in enumerate(refs, 1):
                if (not isinstance(reference, dict) or reference.get("step_count") != position
                        or not isinstance(reference.get("medusa_hash"), str)
                        or not isinstance(reference.get("identity_hash"), str)):
                    raise StudyAuditError(f"invalid prefix dictionary at {path}:{line_number}")
                hashes.append(reference["medusa_hash"])
            if len(set(hashes)) != len(hashes):
                raise StudyAuditError(f"duplicate prefix hash at {path}:{line_number}")
            if event["record_type"] == "partial":
                if sequence.get("is_complete_sequence") is True or event.get("lineage") is not None:
                    raise StudyAuditError(f"partial record claims completion at {path}:{line_number}")
                partial.append(sequence)
                continue
            _validate_steps(fixture, sequence.get("steps"))
            relation = event.get("lineage")
            if (not isinstance(relation, dict) or relation.get("sequence_index") != index
                    or relation.get("executed") is not True
                    or relation.get("kind") not in {"startup_replay", "new_sequence", "mutation"}
                    or refs[-1]["medusa_hash"] != relation.get("output_hash")
                    or refs[-1]["identity_hash"] != relation.get("output_identity_hash")
                    or refs[-1]["step_count"] != len(sequence["steps"])):
                raise StudyAuditError(f"lineage/output mismatch at {path}:{line_number}")
            if relation["kind"] == "mutation":
                parents = relation.get("parent_hashes")
                identities = relation.get("parent_identity_hashes")
                if (not isinstance(parents, list) or not parents
                        or not isinstance(identities, list) or len(parents) != len(identities)
                        or any(parent not in known_prefixes for parent in parents)
                        or any(known_prefixes[parent] != identity
                               for parent, identity in zip(parents, identities))
                        or relation.get("parents_resolved") is not True
                        or relation.get("different_child") is not (
                            relation["output_identity_hash"] not in identities)):
                    raise StudyAuditError(f"invalid mutation parent evidence at {path}:{line_number}")
            charged = search_started + float(relation["completed_offset_seconds"])
            relation["audit_charged_offset_seconds"] = charged
            relation["audit_after_deadline"] = charged > budget
            if relation["audit_after_deadline"]:
                late.append(index)
            else:
                goal = any(step["observe"][3] is True for step in sequence["steps"])
                if goal and (first_goal is None or charged < first_goal["charged_offset_seconds"]):
                    first_goal = {"sequence_index": index, "charged_offset_seconds": charged,
                                  "kind": relation["kind"]}
                complete.append(sequence)
                lineage.append(relation)
            known_prefixes.update({ref["medusa_hash"]: ref["identity_hash"] for ref in refs})
    if eof is None:
        raise StudyAuditError(f"missing EOF: {path}")
    if (eof.get("sequence_count") != len(complete) + len(late)
            or eof.get("partial_count") != len(partial)
            or metadata.get("sequence_records") != len(complete) + len(late)
            or metadata.get("partial_records") != len(partial)):
        raise StudyAuditError(f"compact EOF count mismatch: {path}")
    return {
        "sequences": complete, "lineage": lineage, "partial": partial,
        "after_deadline_indices": late, "first_native_goal": first_goal,
        "metric_observation_end": max(
            (event["audit_charged_offset_seconds"] for event in lineage),
            default=search_started,
        ),
    }


def _miss_reason(record: dict, metrics: dict, augmentation: dict | None) -> str:
    goals = metrics["goal_reached"]
    if goals["warmup"]:
        return "warmup_goal_reached"
    if goals["import"]:
        return "native_import_goal_reached"
    if goals["continuation"]:
        return "native_continuation_goal_reached"
    if record["augmentation_status"] == "no_eligible_prefix":
        return "no_eligible_prefix"
    if record["augmentation_status"] in {"timeout", "invalid_model", "replay_mismatch"}:
        return f"augmentation_{record['augmentation_status']}"
    if augmentation and augmentation.get("accepted"):
        return "verified_seed_but_native_goal_not_observed"
    if record["augmentation_status"] == "no_candidate":
        return "no_candidate"
    return "native_continuation_no_goal"


def audit_study(root: Path, output: Path | None = None) -> dict:
    started = time.monotonic()
    root = Path(root).resolve()
    manifest = _read(root / "manifest.json")
    config = _read(root / "frozen-config.json")
    expected = []
    profiles = {profile["profile_id"]: profile for profile in config["profiles"]}
    for fixture in config["fixtures"]:
        if fixture not in FIXTURES:
            raise StudyAuditError(f"unsupported fixture in archive: {fixture}")
        for repeat in config["repeats"]:
            for profile_id in config["profile_orders"][str(repeat)]:
                expected.append((fixture, repeat, profile_id))
    if len(expected) != len(set(expected)):
        raise StudyAuditError("frozen matrix has duplicate slots")
    if (manifest.get("status") != "complete" or manifest.get("result_count") != len(expected)
            or manifest.get("evaluation_valid_count") != len(expected)):
        raise StudyAuditError("study manifest is incomplete")
    completed_blocks = {row["common_block_id"]: row for row in manifest["completed_blocks"]}
    if len(completed_blocks) != len(config["fixtures"]) * len(config["repeats"]):
        raise StudyAuditError("study manifest has missing or duplicate common blocks")

    rows = []
    total_sequences = 0
    total_mutations = 0
    for fixture, repeat, profile_id in expected:
        block = root / "blocks" / fixture / f"repeat-{repeat:02d}"
        profile_dir = block / "profiles" / profile_id
        record = _read(profile_dir / "campaign.json")
        profile = profiles[profile_id]
        if (record.get("evaluation_valid") is not True
                or record["spec"]["fixture_id"] != fixture
                or record["spec"]["repeat_id"] != repeat
                or record["spec"]["profile_id"] != profile_id):
            raise StudyAuditError(f"slot record differs from matrix: {fixture}/{repeat}/{profile_id}")
        common = _read(block / "common/common.json")
        common_id = f"{fixture}/repeat-{repeat:02d}"
        block_manifest = completed_blocks[common_id]
        if (common["cache_manifest"]["content_sha256"] != block_manifest["common_cache_sha256"]
                or common["corpus_manifest"]["content_sha256"]
                != block_manifest["common_corpus_sha256"]
                or record["artifacts"]["cache_copy"]["source_content_sha256"]
                != block_manifest["common_cache_sha256"]
                or record["artifacts"]["corpus_copy"]["source_content_sha256"]
                != block_manifest["common_corpus_sha256"]):
            raise StudyAuditError(f"common input mismatch: {fixture}/{repeat}/{profile_id}")
        timing = record["online_timing"]
        budget = float(profile["total_budget_seconds"])
        if not (0 <= timing["search_started"] <= timing["search_stopped"]
                <= timing["event_stream_finished"] <= timing["evidence_flush_finished"]
                <= timing["charged_end"] <= budget):
            raise StudyAuditError(f"invalid timing order: {fixture}/{repeat}/{profile_id}")
        native_report = _read(profile_dir / "native/campaign.json")
        if native_report.get("stop_reason") != "time_limit":
            raise StudyAuditError(f"formal slot did not stop by time: {fixture}/{repeat}/{profile_id}")
        decoded = _read_compact(
            profile_dir / "native/events.jsonl.gz", native_report["compact_events"], fixture,
            search_started=float(timing["search_started"]), budget=budget,
        )
        if (decoded["after_deadline_indices"]
                != timing.get("after_deadline_sequence_indices", [])
                or abs(decoded["metric_observation_end"] - timing["metric_observation_end"]) > 0.01):
            raise StudyAuditError(f"metric observation boundary mismatch: {fixture}/{repeat}/{profile_id}")
        kinds = {event["sequence_index"]: event["kind"] for event in decoded["lineage"]}
        imports = [sequence for sequence in decoded["sequences"]
                   if kinds[sequence["sequence_index"]] == "startup_replay"]
        continuation = [sequence for sequence in decoded["sequences"]
                        if kinds[sequence["sequence_index"]] in {"new_sequence", "mutation"}]
        warmup_report = _read(block / "common/warmup/campaign.json")
        warmup = [sequence for sequence in warmup_report["sequences"]
                  if sequence.get("is_complete_sequence") is True]
        independent = _metrics(fixture, warmup, imports, continuation, decoded["lineage"])
        stored_metrics = _read(profile_dir / "metrics.json")
        if independent != stored_metrics:
            raise StudyAuditError(f"independent metrics differ: {fixture}/{repeat}/{profile_id}")
        goal = any(independent["goal_reached"].values())
        if goal is not record["goal_reached"]:
            raise StudyAuditError(f"goal result differs: {fixture}/{repeat}/{profile_id}")

        augmentation_path = profile_dir / "augmentation/augmentation.json"
        augmentation = _read(augmentation_path) if augmentation_path.is_file() else None
        accepted = augmentation.get("accepted", []) if augmentation else []
        accepted_hashes = {entry["medusa_hash"] for entry in accepted}
        startup_hashes = {
            event["output_hash"] for event in decoded["lineage"]
            if event["kind"] == "startup_replay"
        }
        if not accepted_hashes <= startup_hashes:
            raise StudyAuditError(f"accepted seed was not replayed: {fixture}/{repeat}/{profile_id}")
        accepted_use = {
            parent: {"selected": 0, "different_executed_children": 0}
            for parent in accepted_hashes
        }
        for event in decoded["lineage"]:
            if event["kind"] != "mutation":
                continue
            total_mutations += 1
            for parent in set(event["parent_hashes"]) & accepted_hashes:
                accepted_use[parent]["selected"] += 1
                accepted_use[parent]["different_executed_children"] += int(
                    event["different_child"] is True and event["executed"] is True)
        total_sequences += len(decoded["sequences"])
        augmentation_stage = next(
            (stage for stage in record["stages"] if stage["name"] == "augmentation"), None)
        row = {
            "slot_id": record["spec"]["slot_id"],
            "fixture_id": fixture,
            "repeat_id": repeat,
            "profile_id": profile_id,
            "arm": profile["arm"],
            "total_budget_seconds": budget,
            "goal_invocation_limit_seconds": profile.get("goal_invocation_limit_seconds"),
            "families": profile["families"],
            "goal_reached": goal,
            "warmup_goal_reached": independent["goal_reached"]["warmup"],
            "native_import_goal_reached": independent["goal_reached"]["import"],
            "native_continuation_goal_reached": independent["goal_reached"]["continuation"],
            "auxiliary_concrete_goal_confirmed": bool(accepted),
            "auxiliary_confirmation_time_upper_bound": (
                augmentation_stage["finished_offset_seconds"] if accepted and augmentation_stage else None),
            "first_native_goal": decoded["first_native_goal"],
            "observation_end_seconds": decoded["metric_observation_end"],
            "search_started_seconds": timing["search_started"],
            "search_stopped_seconds": timing["search_stopped"],
            "evidence_flush_finished_seconds": timing["evidence_flush_finished"],
            "charged_end_seconds": timing["charged_end"],
            "unused_budget_seconds": timing["unused_budget_seconds"],
            "completed_sequences": len(decoded["sequences"]),
            "partial_sequences": len(decoded["partial"]),
            "after_deadline_sequences": len(decoded["after_deadline_indices"]),
            "augmentation_status": record["augmentation_status"],
            "accepted_seed_count": len(accepted),
            "accepted_seed_use": accepted_use,
            "miss_or_hit_reason": _miss_reason(record, independent, augmentation),
            "sequence_new_count": independent["dimensions"]["sequences"]["total"]["new_count"],
            "state_new_count": independent["dimensions"]["states"]["total"]["new_count"],
            "coverage_new_count": independent["dimensions"]["coverage"]["total"]["new_count"],
            "stage_cost_seconds": {
                stage["name"]: stage["elapsed_seconds"] for stage in record["stages"]
            },
            "event_stream_path": str(profile_dir / "native/events.jsonl.gz"),
            "event_stream_sha256": native_report["compact_events"]["sha256"],
        }
        rows.append(row)
    result = {
        "schema_version": 1,
        "status": "passed",
        "study_id": manifest["study_id"],
        "slot_count": len(rows),
        "common_block_count": len(completed_blocks),
        "goal_hit_count": sum(row["goal_reached"] for row in rows),
        "complete_sequence_count": total_sequences,
        "mutation_event_count": total_mutations,
        "elapsed_seconds": time.monotonic() - started,
        "rows": rows,
    }
    if output:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def write_observations_csv(audit: dict, path: Path) -> None:
    fields = [
        "slot_id", "fixture_id", "repeat_id", "profile_id", "arm",
        "total_budget_seconds", "goal_invocation_limit_seconds", "goal_reached",
        "warmup_goal_reached", "native_import_goal_reached",
        "native_continuation_goal_reached", "auxiliary_concrete_goal_confirmed",
        "observation_end_seconds", "charged_end_seconds", "unused_budget_seconds",
        "completed_sequences", "partial_sequences", "augmentation_status",
        "accepted_seed_count", "miss_or_hit_reason", "sequence_new_count",
        "state_new_count", "coverage_new_count", "event_stream_sha256",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in audit["rows"]:
            writer.writerow({key: row.get(key) for key in fields})
