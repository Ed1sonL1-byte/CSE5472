"""Stage 4 audit from raw native events, candidate records, and concrete replays."""

from __future__ import annotations

from collections import Counter
import csv
import json
from pathlib import Path

from .io import file_hash, read_json, write_json
from .study_audit import StudyAuditError, _state, _validate_steps, audit_study


def _inside(root: Path, value: str) -> Path:
    path = Path(value).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise StudyAuditError(f"evidence path is missing or outside the study: {value}")
    return path


def _forge_success(path: Path) -> bool:
    data = read_json(path)
    tests = [test for key, contract in data.items()
             if key.endswith(":BridgeHarnessTest") and isinstance(contract, dict)
             for name, test in contract.get("test_results", {}).items()
             if name == "test_replay()"]
    return len(tests) == 1 and tests[0].get("status") == "Success"


def _model_contains(path: Path, argument: str) -> bool:
    data = read_json(path)
    if data.get("exitcode") != 1:
        return False
    tests = [test for group in data.get("test_results", {}).values()
             if isinstance(group, list) for test in group
             if isinstance(test, dict) and test.get("name") == "check_goal(uint256)"]
    if len(tests) != 1:
        return False
    for candidate in tests[0].get("models", []):
        if candidate.get("is_valid") is not True:
            continue
        model = candidate.get("model")
        if not isinstance(model, dict) or len(model) != 1:
            continue
        variable = next(iter(model.values()))
        if (isinstance(variable, dict) and variable.get("variable_name") == "arg0"
                and variable.get("solidity_type") == "uint256"
                and variable.get("value") == int(argument)):
            return True
    return False


def _selected_prefixes(root: Path, block: Path, fixture: str) -> list[dict]:
    warmup = read_json(block / "common/warmup/campaign.json")
    source = {(sequence.get("native_path"), sequence.get("native_digest")): sequence
              for sequence in warmup.get("sequences", [])}
    pool = read_json(block / "common/prefix-pool.json")
    selected = pool.get("selected", [])
    if not isinstance(selected, list):
        raise StudyAuditError("common prefix pool is malformed")
    for prefix in selected:
        path = _inside(root, prefix["native_path"])
        if file_hash(path) != prefix["native_digest"]:
            raise StudyAuditError("selected native prefix digest changed")
        origin = source.get((prefix["native_path"], prefix["native_digest"]))
        expected = [dict(step, actual_block=str(step["block_number"]),
                         actual_timestamp=str(step["block_timestamp"]))
                    for step in origin["steps"]] if origin else None
        if expected != prefix["steps"]:
            raise StudyAuditError("selected prefix is absent from Medusa warmup evidence")
        _validate_steps(fixture, prefix["steps"])
        if _state(fixture, prefix["steps"][-1]["observe"])["violation"]:
            raise StudyAuditError("selected safety prefix already violates the property")
    return selected


def _candidate_evidence(root: Path, fixture: str, arm: str, profile_dir: Path,
                        prefixes: list[dict]) -> dict:
    path = profile_dir / "augmentation/augmentation.json"
    if arm == "native_resume":
        if path.exists():
            raise StudyAuditError("native control unexpectedly has an augmentation record")
        return {"generated": 0, "concrete_executed": 0, "confirmed": 0,
                "solver_candidates": 0, "solver_seconds": 0.0, "replay_seconds": 0.0,
                "rejections": {}}
    if not path.is_file():
        # An empty prefix pool records a skipped augmentation in the slot record.
        return {"generated": 0, "concrete_executed": 0, "confirmed": 0,
                "solver_candidates": 0, "solver_seconds": 0.0, "replay_seconds": 0.0,
                "rejections": {}}
    augmentation = read_json(path)
    attempts = augmentation.get("attempts", [])
    accepted = augmentation.get("accepted", [])
    if not isinstance(attempts, list) or not isinstance(accepted, list):
        raise StudyAuditError("augmentation attempt list is malformed")
    accepted_keys = {(entry["native_path"], entry["argument"]) for entry in accepted}
    if len(accepted_keys) != len(accepted):
        raise StudyAuditError("duplicate accepted candidate")
    for entry in accepted:
        if (entry.get("validation_status") != "accepted"
                or not 0 <= entry.get("prefix_index", -1) < len(prefixes)
                or (entry["native_path"], entry["argument"]) not in {
                    (item.get("native_path"), item.get("argument")) for item in attempts}):
            raise StudyAuditError("accepted candidate lacks a matching generated attempt")
        native = _inside(root, entry["accepted_native_path"])
        original = _inside(root, entry["native_path"])
        if file_hash(native) != file_hash(original):
            raise StudyAuditError("accepted native seed differs from validated candidate")
        executed = entry.get("execution", {})
        steps = executed.get("steps")
        if (executed.get("complete") is not True or executed.get("admitted") is not True
                or not isinstance(steps, list)):
            raise StudyAuditError("accepted candidate lacks actual Medusa execution")
        _validate_steps(fixture, steps)
        prefix = prefixes[entry["prefix_index"]]["steps"]
        keys = ("from", "to", "calldata", "value", "actual_block", "actual_timestamp",
                "status", "observe", "invariant_holds", "property_holds")
        if (len(steps) != len(prefix) + 1
                or any(any(actual.get(field) != expected.get(field) for field in keys)
                       for actual, expected in zip(steps, prefix))):
            raise StudyAuditError("accepted candidate did not replay its traced prefix")
        if not _state(fixture, steps[-1]["observe"])["violation"]:
            raise StudyAuditError("accepted candidate does not violate the arithmetic property")
    symbolic_attempts = augmentation.get("symbolic_attempts", [])
    solver_candidates = 0
    solver_seconds = replay_seconds = 0.0
    for attempt in symbolic_attempts:
        for name in ("prefix_check", "solve"):
            command = attempt.get(name, {}).get("command_result", {})
            solver_seconds += float(command.get("elapsed_seconds", 0.0))
        replay_seconds += float(attempt.get("replay", {}).get("command_result", {}).get("elapsed_seconds", 0.0))
        if attempt.get("solve", {}).get("status") != "candidate":
            continue
        solver_candidates += 1
        candidate = attempt.get("candidate")
        if candidate is None:
            continue
        model = _inside(root, candidate["model_file"])
        if not _model_contains(model, candidate["argument"]):
            raise StudyAuditError("accepted symbolic argument is absent from raw Halmos model")
        replay = attempt.get("replay", {})
        if replay.get("status") == "violation_confirmed":
            log = _inside(root, replay["command_result"]["log_path"])
            if not _forge_success(log):
                raise StudyAuditError("symbolic candidate lacks a successful Foundry replay")
    if arm == "symbolic_augment" and accepted and solver_candidates == 0:
        raise StudyAuditError("accepted symbolic seed lacks a Halmos model")
    if arm == "concrete_augment" and symbolic_attempts:
        raise StudyAuditError("concrete arm has symbolic attempts")
    rejections = Counter(entry.get("validation_status", "unclassified") for entry in attempts
                         if entry.get("validation_status") != "accepted")
    return {"generated": len(attempts),
            "concrete_executed": sum("execution" in entry for entry in attempts),
            "confirmed": len(accepted), "solver_candidates": solver_candidates,
            "solver_seconds": solver_seconds, "replay_seconds": replay_seconds,
            "rejections": dict(sorted(rejections.items()))}


def audit_safety_study(root: Path, output: Path | None = None) -> dict:
    root = Path(root).resolve()
    config = read_json(root / "frozen-config.json")
    if config.get("mode") != "safety_formal" or config.get("study_id") != "stage4-safety-formal-v2":
        raise StudyAuditError("not the frozen Stage 4 safety study")
    base = audit_study(root)
    if base["slot_count"] != 60 or base["common_block_count"] != 20:
        raise StudyAuditError("Stage 4 matrix is incomplete")
    rows = []
    selected_cache: dict[tuple[str, int], list[dict]] = {}
    for raw in base["rows"]:
        fixture, repeat, profile_id = raw["fixture_id"], raw["repeat_id"], raw["profile_id"]
        block = root / "blocks" / fixture / f"repeat-{repeat:02d}"
        profile_dir = block / "profiles" / profile_id
        record = read_json(profile_dir / "campaign.json")
        key = (fixture, repeat)
        if key not in selected_cache:
            selected_cache[key] = _selected_prefixes(root, block, fixture)
        prefixes = selected_cache[key]
        if (record.get("target_kind") != "safety_property"
                or record.get("property_id") != "allocation_conservation"
                or record.get("property_violation_confirmed") is not raw["goal_reached"]
                or record["spec"]["seed"] != config["seeds"][f"{fixture}:{repeat}"]):
            raise StudyAuditError("safety slot classification or paired seed differs")
        candidate = _candidate_evidence(root, fixture, raw["arm"], profile_dir, prefixes)
        if candidate["confirmed"] != raw["accepted_seed_count"]:
            raise StudyAuditError("raw candidate confirmations differ from campaign report")
        common = read_json(block / "common/common.json")
        warmup = read_json(block / "common/warmup/campaign.json")
        common_elapsed = float(common["elapsed_seconds"])
        warmup_timing = warmup.get("native_timing_seconds", {})
        pre_warmup = max(0.0, common_elapsed - float(warmup_timing.get("adapter_total", 0.0)))
        hits = []
        for event in warmup.get("lineage", []):
            if event.get("goal_reached") is True:
                hits.append((pre_warmup + float(warmup_timing.get("setup_before_fuzz", 0.0))
                             + float(event["completed_offset_seconds"]), "warmup"))
        augmentation_stage = next((stage for stage in record["stages"]
                                   if stage["name"] == "augmentation"), None)
        if candidate["confirmed"] and augmentation_stage:
            hits.append((float(augmentation_stage["finished_offset_seconds"]), "augmentation"))
        if raw["first_native_goal"]:
            stage = ("native_import" if raw["first_native_goal"]["kind"] == "startup_replay"
                     else "native_continuation")
            hits.append((float(raw["first_native_goal"]["charged_offset_seconds"]), stage))
        first = min(hits) if hits else None
        if bool(first) is not raw["goal_reached"]:
            raise StudyAuditError("first violation evidence disagrees with raw property observations")
        if first and first[0] > 32:
            raise StudyAuditError("reported violation is after the chargeable budget")
        rows.append({
            "slot_id": raw["slot_id"], "fixture_id": fixture, "repeat_id": repeat,
            "arm": raw["arm"], "evaluation_valid": True,
            "violation_confirmed": raw["goal_reached"],
            "first_violation_seconds": first[0] if first else None,
            "first_violation_stage": first[1] if first else "right_censored",
            "right_censored": first is None,
            "censor_seconds": None if first else raw["search_stopped_seconds"],
            "observation_end_seconds": raw["search_stopped_seconds"],
            "budget_limit_seconds": 32.0,
            "warmup_violation": raw["warmup_goal_reached"],
            "augmentation_violation": bool(candidate["confirmed"]),
            "continuation_violation": raw["native_continuation_goal_reached"],
            "generated_candidates": candidate["generated"],
            "concrete_executed_candidates": candidate["concrete_executed"],
            "confirmed_candidates": candidate["confirmed"],
            "solver_candidates": candidate["solver_candidates"],
            "solver_seconds": candidate["solver_seconds"],
            "replay_seconds": candidate["replay_seconds"],
            "rejections": candidate["rejections"],
            "augmentation_status": raw["augmentation_status"],
            "augmentation_seconds": raw["stage_cost_seconds"].get("augmentation", 0.0),
            "charged_end_seconds": raw["charged_end_seconds"],
            "completed_sequences": raw["completed_sequences"],
            "partial_sequences": raw["partial_sequences"],
            "event_stream_sha256": raw["event_stream_sha256"],
        })
    groups = {}
    for fixture in config["fixtures"]:
        for arm in ("native_resume", "concrete_augment", "symbolic_augment"):
            group_rows = [row for row in rows if row["fixture_id"] == fixture and row["arm"] == arm]
            groups[f"{fixture}:{arm}"] = {
                "slots": len(group_rows),
                "confirmed_violations": sum(row["violation_confirmed"] for row in group_rows),
                "warmup_violations": sum(row["warmup_violation"] for row in group_rows),
                "augmentation_violations": sum(row["augmentation_violation"] for row in group_rows),
                "continuation_violations": sum(row["continuation_violation"] for row in group_rows),
                "generated_candidates": sum(row["generated_candidates"] for row in group_rows),
                "concrete_executed_candidates": sum(row["concrete_executed_candidates"] for row in group_rows),
                "confirmed_candidates": sum(row["confirmed_candidates"] for row in group_rows),
                "augmentation_statuses": dict(Counter(row["augmentation_status"] for row in group_rows)),
            }
    result = {"schema_version": 1, "status": "passed", "study_id": config["study_id"],
              "slot_count": len(rows), "common_block_count": len(selected_cache),
              "complete_sequence_count": base["complete_sequence_count"],
              "mutation_event_count": base["mutation_event_count"],
              "groups": groups, "rows": rows,
              "method": "recomputed from raw Medusa events, native prefix files, Halmos models, and Foundry test records"}
    if output:
        write_json(output, result)
    return result


def write_safety_report(audit: dict, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / "summary.json", {
        key: audit[key] for key in ("schema_version", "status", "study_id", "slot_count",
                               "common_block_count", "complete_sequence_count",
                               "mutation_event_count", "groups")
    })
    fields = [key for key in audit["rows"][0] if key != "rejections"]
    with (directory / "observations.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows({key: row[key] for key in fields} for row in audit["rows"])
    lines = ["# Stage 4 controlled safety regression", "",
             "One known local accounting defect, one repaired version, and one arithmetic property.", "",
             f"Independent audit: **{audit['status']}**, {audit['slot_count']}/60 slots.", "",
             "| Version | Arm | Confirmed violations | Generated / confirmed candidates |",
             "| --- | --- | ---: | ---: |"]
    for key, group in audit["groups"].items():
        fixture, arm = key.split(":")
        lines.append(f"| {fixture} | {arm} | {group['confirmed_violations']}/{group['slots']} | "
                     f"{group['generated_candidates']} / {group['confirmed_candidates']} |")
    lines.extend(["", "Misses are censored at each actual search observation end; 32 seconds is the budget ceiling.",
                  "Native controls are restarted from the paired warmup corpus. Medusa's internal corpus and mutation choosers retain clock-seeded randomness.",
                  "A repaired-version miss is finite testing evidence, not a proof of global safety.", ""])
    (directory / "summary.md").write_text("\n".join(lines))
