"""Independent Stage 5 audit based on native events, model JSON, and replay logs."""

from __future__ import annotations

import csv
from collections import Counter
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from eth_hash.auto import keccak

from .compact import read_compact_events
from .config import get_scenario
from .io import file_hash, read_json, write_json
from .stage5_study import ARMS, FIXTURES, validate_config


class Stage5AuditError(ValueError):
    pass


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


@lru_cache(maxsize=8)
def _original_root(root: Path) -> str:
    return (read_json(root / "path-map.json")["original_root"]
            if (root / "path-map.json").is_file() else str(root))


def _path(root: Path, value: str) -> Path:
    original = _original_root(root)
    source = Path(value)
    try:
        relative = source.relative_to(original) if source.is_absolute() else source
    except ValueError as error:
        raise Stage5AuditError(f"raw reference escapes study: {value}") from error
    result = (root / relative).resolve()
    if not result.is_relative_to(root.resolve()) or not result.is_file():
        raise Stage5AuditError(f"raw evidence file is missing: {value}")
    return result


def _property(fixture_id: str, state: list) -> bool:
    if not isinstance(state, list) or len(state) != 4 or type(state[3]) is not bool:
        raise Stage5AuditError("malformed state observation")
    try:
        a, b, c = (int(item) for item in state[:3])
    except (TypeError, ValueError) as error:
        raise Stage5AuditError("noninteger observed state") from error
    if any(number < 0 or number >= 1 << 256 for number in (a, b, c)):
        raise Stage5AuditError("observed state is outside uint256")
    property_id = get_scenario(fixture_id).property_id
    if property_id == "allocation_conservation":
        holds = a == b + c
    elif property_id == "reservation_conservation":
        holds = a + b + c == 100
    elif property_id == "approval_bound":
        holds = c <= b
    else:
        raise Stage5AuditError("unknown frozen safety property")
    if state[3] is holds:
        raise Stage5AuditError("contract violation marker disagrees with independent arithmetic")
    return holds


def _steps(fixture_id: str, steps: list[dict]) -> int | None:
    if not isinstance(steps, list) or not steps or len(steps) > 5:
        raise Stage5AuditError("native sequence has unsupported length")
    first = None
    actor = None
    target = None
    for index, step in enumerate(steps):
        holds = _property(fixture_id, step.get("observe"))
        if (step.get("property_holds") is not holds
                or step.get("invariant_holds") is not True
                or step.get("observer_state_unchanged") is not True
                or step.get("state_root_before_observer")
                != step.get("state_root_after_observer")
                or str(step.get("value")) != "0"):
            raise Stage5AuditError("native property, invariant, context, or observer differs")
        actor = actor or step.get("from")
        target = target or step.get("to")
        if step.get("from") != actor or step.get("to") != target:
            raise Stage5AuditError("native sequence actor or target changed")
        if not holds and first is None:
            first = index
    return first


def _raw_model(path: Path, signature: str, assignments: dict) -> bool:
    raw = read_json(path)
    if raw.get("exitcode") != 1:
        return False
    tests = [test for collection in raw.get("test_results", {}).values()
             if isinstance(collection, list) for test in collection
             if isinstance(test, dict) and test.get("name") == signature]
    if len(tests) != 1 or tests[0].get("exitcode") != 1:
        return False
    for candidate in tests[0].get("models", []):
        if candidate.get("is_valid") is not True:
            continue
        raw_vars = candidate.get("model")
        if not isinstance(raw_vars, dict) or len(raw_vars) != len(assignments):
            continue
        parsed = {}
        for fullname, value in raw_vars.items():
            if (not isinstance(value, dict) or value.get("full_name") != fullname
                    or value.get("solidity_type") != "uint256"
                    or value.get("smt_type") != "BitVec 256"
                    or value.get("size_bits") != 256
                    or type(value.get("value")) is not int
                    or not 0 <= value["value"] < 1 << 256):
                break
            name = value.get("variable_name")
            if name in parsed or name not in assignments:
                break
            parsed[name] = str(value["value"])
        if parsed == assignments:
            return True
    return False


def _forge_steps(path: Path, expected_count: int) -> list[dict]:
    raw = read_json(path)
    tests = [test for name, contract in raw.items()
             if name.endswith(":BridgeHarnessTest") and isinstance(contract, dict)
             for test_name, test in contract.get("test_results", {}).items()
             if test_name == "test_replay()"]
    if len(tests) != 1 or tests[0].get("status") != "Success":
        raise Stage5AuditError("fresh Foundry replay did not pass")
    topic = "0x" + keccak(
        b"BridgeStep(uint256,bool,uint256,uint256,uint256,bool,bool,uint256,uint256)").hex()
    result = []
    for log in tests[0].get("logs", []):
        if log.get("topics") != [topic]:
            continue
        data = log.get("data", "")
        if not isinstance(data, str) or not data.startswith("0x") or len(data) != 2 + 9 * 64:
            raise Stage5AuditError("malformed Foundry per-call evidence")
        words = [int(data[2 + i * 64:2 + (i + 1) * 64], 16) for i in range(9)]
        if any(words[i] not in (0, 1) for i in (1, 5, 6)):
            raise Stage5AuditError("Foundry boolean evidence is malformed")
        result.append({"index": words[0], "success": bool(words[1]),
                       "observe": [str(words[2]), str(words[3]), str(words[4]),
                                   bool(words[5])],
                       "property_holds": bool(words[6]),
                       "block": str(words[7]), "timestamp": str(words[8])})
    if len(result) != expected_count or [item["index"] for item in result] != list(range(expected_count)):
        raise Stage5AuditError("Foundry replay lacks ordered intermediate states")
    return result


def _native_candidate(root: Path, fixture_id: str, candidate: dict, plan: dict,
                      prefix: dict, *, repaired: bool = False) -> dict:
    record_key = "repaired_native_record" if repaired else "native_record"
    input_key = "repaired_native_input" if repaired else "native_input"
    observed = read_json(_path(root, candidate[record_key]))
    native_input = read_json(_path(root, candidate[input_key]))
    if not isinstance(native_input, list) or len(native_input) != len(prefix["steps"]) + len(plan["calls"]):
        raise Stage5AuditError("candidate native input has wrong length")
    matching = [seq for seq in observed.get("sequences", [])
                if seq.get("is_complete_sequence") is True
                and seq.get("replayed_by_medusa") is True
                and seq.get("admitted_for_mutation") is True
                and len(seq.get("steps", [])) == len(native_input)]
    if len(matching) != 1:
        raise Stage5AuditError("candidate was not uniquely executed/admitted by Medusa")
    seq = matching[0]
    admission = seq.get("admission_evidence", {})
    if (admission.get("event") != "FuzzerWorker.CallSequenceTested"
            or admission.get("full_sequence_executed") is not True
            or admission.get("native_input_hash_matched") is not True):
        raise Stage5AuditError("Medusa native candidate lacks admission event")
    for index, (actual, encoded) in enumerate(zip(seq["steps"], native_input)):
        call = encoded.get("call") if isinstance(encoded, dict) else None
        if (not isinstance(call, dict)
                or actual.get("from", "").lower() != str(call.get("from", "")).lower()
                or actual.get("to", "").lower() != str(call.get("to", "")).lower()
                or actual.get("calldata", "").lower() != str(call.get("data", "")).lower()
                or int(actual.get("value", -1)) != int(str(call.get("value", "-1")), 0)):
            raise Stage5AuditError(f"candidate native call {index} differs from input")
    assignments = candidate.get("assignments", {})
    for position, declared in enumerate(plan["calls"]):
        native_call = native_input[len(prefix["steps"]) + position]["call"]
        actual_step = seq["steps"][len(prefix["steps"]) + position]
        signature = declared["signature"]
        variable = declared.get("variable")
        selector = "0x" + keccak(signature.encode())[:4].hex()
        if variable is None:
            calldata = selector
        else:
            value = int(assignments[variable])
            if not 0 <= value < 1 << 256:
                raise Stage5AuditError("model assignment is outside uint256")
            calldata = selector + value.to_bytes(32, "big").hex()
        if (str(native_call.get("data", "")).lower() != calldata
                or str(native_call.get("from", "")).lower() != declared["actor"].lower()
                or str(native_call.get("to", "")).lower() != declared["target"].lower()
                or int(str(native_call.get("value", "-1")), 0) != 0
                or str(actual_step.get("block_number")) != declared["actual_block"]
                or str(actual_step.get("block_timestamp")) != declared["actual_timestamp"]):
            raise Stage5AuditError("native suffix calldata or context differs from typed plan")
    for index, (actual, expected) in enumerate(zip(seq["steps"], prefix["steps"])):
        fields = ("from", "to", "calldata", "value", "status", "observe",
                  "property_holds", "block_number", "block_timestamp")
        if any(actual.get(key) != expected.get(key) for key in fields):
            raise Stage5AuditError(f"native candidate prefix step {index} changed")
    first = _steps(fixture_id, seq["steps"])
    if repaired and first is not None:
        raise Stage5AuditError("same candidate violates repaired property")
    if not repaired and first is None:
        raise Stage5AuditError("native candidate did not violate flawed property")
    return {"first_violation_index": first, "steps": seq["steps"]}


def audit_stage5(root: Path, output: Path | None = None,
                 *, require_complete: bool = True) -> dict:
    root = Path(root).resolve()
    config = validate_config(read_json(root / "frozen-config.json"))
    manifest = read_json(root / "manifest.json")
    if manifest.get("config_sha256") != file_hash(root / "frozen-config.json"):
        raise Stage5AuditError("frozen configuration checksum differs")
    source_manifest = read_json(root / "source/source-manifest.json")
    if (manifest.get("execution_source", {}).get("content_sha256")
            != source_manifest.get("content_sha256")):
        raise Stage5AuditError("formal execution source identity differs")
    for item in source_manifest.get("files", []):
        frozen = root / "source" / item["path"]
        if (not frozen.is_file() or frozen.stat().st_size != item["bytes"]
                or file_hash(frozen) != item["sha256"]):
            raise Stage5AuditError(f"frozen execution source changed: {item['path']}")
    rows = []
    blocks = 0
    for fixture_id in config["fixtures"]:
        for repeat in config["repeats"]:
            block = root / "blocks" / fixture_id / f"repeat-{repeat:02d}"
            if not (block / "common/common.json").is_file():
                if require_complete:
                    raise Stage5AuditError("formal common block is missing")
                continue
            blocks += 1
            common = read_json(block / "common/common.json")
            warmup = read_json(block / "common/warmup/campaign.json")
            if warmup.get("max_steps") != 5 or warmup.get("worker_count") != 1:
                raise Stage5AuditError("warmup execution boundary differs")
            if common["seed"] != 91000 + FIXTURES.index(fixture_id) * 100 + repeat:
                raise Stage5AuditError("paired warmup seed differs from frozen protocol")
            if not common["within_common_limit"] or common["elapsed_seconds"] > config["common_limit_seconds"]:
                raise Stage5AuditError("common build/warmup exceeded the charged limit")
            complete_warmup = [seq for seq in warmup["sequences"]
                               if seq.get("is_complete_sequence") is True]
            warmup_first = {seq.get("sequence_index"): _steps(fixture_id, seq["steps"])
                            for seq in complete_warmup}
            if len(warmup_first) != len(complete_warmup) or any(
                    event["goal_reached"] is not (
                        warmup_first[event["sequence_index"]] is not None)
                    for event in warmup["lineage"]):
                raise Stage5AuditError("warmup lineage goal differs from independent state")
            warmup_hits = [index for index in warmup_first.values() if index is not None]
            if bool(warmup_hits) != bool(common["warmup_violations"]):
                raise Stage5AuditError("warmup safety finding differs from raw calls")
            selected = read_json(block / "common/prefix-pool.json")["selected"]
            by_digest = {(seq["native_path"], seq["native_digest"]): seq
                         for seq in warmup["sequences"]}
            for prefix in selected:
                source = by_digest.get((prefix["native_path"], prefix["native_digest"]))
                if source is None or file_hash(_path(root, prefix["native_path"])) != prefix["native_digest"]:
                    raise Stage5AuditError("selected prefix has no real Medusa source")
                observed_steps = [dict(step, actual_block=str(step["block_number"]),
                                       actual_timestamp=str(step["block_timestamp"]))
                                  for step in source["steps"]]
                if observed_steps != prefix["steps"] or _steps(fixture_id, prefix["steps"]) is not None:
                    raise Stage5AuditError("selected prefix state differs from executed source")
                source_file = root / "source/fixtures" / fixture_id / "src" / (get_scenario(fixture_id).contract + ".sol")
                if not source_file.is_file() or prefix.get("deployer") != warmup["deployment"]["deployer"]:
                    raise Stage5AuditError("frozen fixture or deployment provenance is missing")
                fields = ("from", "to", "calldata", "value", "actual_block",
                          "actual_timestamp", "status", "observe", "property_holds",
                          "invariant_holds", "state_root_before_observer",
                          "state_root_after_observer")
                expected_id = _digest({"fixture_id": fixture_id,
                                       "fixture_source_sha256": file_hash(source_file),
                                       "deployer": prefix["deployer"],
                                       "native_digest": prefix["native_digest"],
                                       "steps": [{key: step[key] for key in fields}
                                                 for step in prefix["steps"]]})
                if prefix.get("stage5_prefix_id") != expected_id:
                    raise Stage5AuditError("selected prefix full-context identity differs")
            for arm in config["arms"]:
                path = block / "arms" / arm / "slot.json"
                if not path.is_file():
                    if require_complete:
                        raise Stage5AuditError("formal arm is missing")
                    continue
                slot = read_json(path)
                if (slot.get("fixture_id") != fixture_id or slot.get("repeat") != repeat
                        or slot.get("arm") != arm or slot.get("seed") != common["seed"]):
                    raise Stage5AuditError("slot is not paired to its common warmup")
                if not slot.get("evaluation_valid"):
                    if require_complete:
                        raise Stage5AuditError(f"invalid formal slot: {fixture_id}/{repeat}/{arm}")
                    rows.append({"fixture_id": fixture_id, "repeat": repeat, "arm": arm,
                                 "evaluation_valid": False, "status": slot.get("status")})
                    continue
                stages = slot["stages"]
                if (slot["status"] != "completed" or any(item.get("after_deadline") for item in stages)
                        or slot["budget"]["charged_wall_seconds"] > config["total_budget_seconds"]):
                    raise Stage5AuditError("slot exceeded the total charged budget")
                confirmed = []
                generated_candidates = 0
                concrete_candidates = 0
                solver_seconds = 0.0
                replay_seconds = 0.0
                query_statuses = Counter()
                candidate_statuses = Counter()
                scheduled = [item["query_id"] for item in slot.get("scheduler_decisions", [])
                             if item.get("query_id") is not None]
                if scheduled != [item["query_id"] for item in slot["queries"]]:
                    raise Stage5AuditError("query execution order differs from scheduler decisions")
                for query_ref in slot["queries"]:
                    query = read_json(_path(root, query_ref["record"]))
                    if query["status"] != query_ref["status"]:
                        raise Stage5AuditError("query result differs from slot feedback")
                    query_statuses[query["status"]] += 1
                    generated_candidates += len(query.get("candidates", []))
                    solver_seconds += sum(float(query.get(name, {}).get(
                        "command_result", {}).get("elapsed_seconds", 0))
                        for name in ("prefix_check", "solve"))
                    plan = query["plan"]
                    prefix = next((item for item in selected
                                   if item["stage5_prefix_id"] == plan["prefix_id"]), None)
                    if prefix is None or plan["query_id"] != query_ref["query_id"]:
                        raise Stage5AuditError("query lacks an executed selected prefix")
                    expected_query = _digest({"prefix_id": prefix["stage5_prefix_id"],
                                              "calls": plan["calls"],
                                              "solver_test": "check_suffix",
                                              "schema_version": 1})
                    if plan["query_id"] != expected_query:
                        raise Stage5AuditError("ordered full-context query identity differs")
                    if len(plan["calls"]) != query_ref["suffix_length"]:
                        raise Stage5AuditError("suffix length differs from scheduler record")
                    for candidate in query.get("candidates", []):
                        candidate_statuses[candidate["status"]] += 1
                        if "foundry" in candidate:
                            concrete_candidates += 1
                            replay_seconds += float(candidate["foundry"].get(
                                "command_result", {}).get("elapsed_seconds", 0))
                        if "repaired_foundry" in candidate:
                            replay_seconds += float(candidate["repaired_foundry"].get(
                                "command_result", {}).get("elapsed_seconds", 0))
                        if not _raw_model(_path(root, candidate["model_file"]),
                                          plan["test_signature"], candidate["assignments"]):
                            raise Stage5AuditError("candidate assignments differ from raw typed Halmos model")
                        if candidate["status"] != "confirmed":
                            continue
                        foundry = _forge_steps(_path(root, candidate["foundry"]["command_result"]["log_path"]),
                                               len(plan["calls"]))
                        native = _native_candidate(root, fixture_id, candidate,
                                                   plan, prefix)
                        suffix = native["steps"][len(prefix["steps"]):]
                        for position, (fstep, nstep) in enumerate(zip(foundry, suffix)):
                            if (fstep["success"] is not nstep["success"]
                                    or fstep["observe"] != nstep["observe"]
                                    or fstep["property_holds"] is not nstep["property_holds"]
                                    or fstep["block"] != str(nstep["block_number"])
                                    or fstep["timestamp"] != str(nstep["block_timestamp"])):
                                raise Stage5AuditError(f"Foundry/native intermediate step {position} differs")
                        repaired_id = get_scenario(fixture_id).stage5_repaired_fixture
                        if repaired_id and repaired_id != fixture_id:
                            repaired_foundry = _forge_steps(
                                _path(root, candidate["repaired_foundry"]["command_result"]["log_path"]),
                                len(plan["calls"]))
                            repaired = _native_candidate(root, repaired_id, candidate,
                                                         plan, prefix, repaired=True)
                            if any(f["observe"] != n["observe"] for f, n in
                                   zip(repaired_foundry, repaired["steps"][len(prefix["steps"]):])):
                                raise Stage5AuditError("repaired Foundry/native state differs")
                        confirmed.append({"query_id": query["query_id"],
                                          "first_violation_call_index": native["first_violation_index"],
                                          "two_step_only": (native["first_violation_index"]
                                                            == len(prefix["steps"]) + 1)})
                if len(confirmed) != len(slot["candidate_confirmations"]):
                    raise Stage5AuditError("confirmed candidate count differs from raw queries")
                native_report = read_json(_path(root, slot["native_record"]))
                if (native_report.get("max_steps") != 5
                        or native_report.get("worker_count") != 1):
                    raise Stage5AuditError("arm execution boundary differs")
                event_file = _path(root, slot["native_event_stream"])
                events = read_compact_events(event_file, native_report["compact_events"])
                if len(events["lineage"]) != native_report["completed_sequences"]:
                    raise Stage5AuditError("native event count differs from report")
                for recorded, rebuilt in zip(slot["candidate_confirmations"], confirmed):
                    if (recorded["query_id"] != rebuilt["query_id"]
                            or recorded["first_violation_call_index"]
                            != rebuilt["first_violation_call_index"]
                            or recorded["two_step_only"] != rebuilt["two_step_only"]):
                        raise Stage5AuditError("slot confirmation differs from raw candidate")
                    imported = _path(root, recorded["imported_input"])
                    if file_hash(imported) != file_hash(_path(root, recorded["native_input"])):
                        raise Stage5AuditError("imported candidate differs from validated native input")
                    replayed = [(seq, event) for seq, event in
                                zip(events["sequences"], events["lineage"])
                                if seq.get("native_digest") == file_hash(imported)
                                and event.get("kind") == "startup_replay"]
                    if len(replayed) != 1 or _steps(fixture_id, replayed[0][0]["steps"]) != rebuilt["first_violation_call_index"]:
                        raise Stage5AuditError("confirmed candidate was not replayed on continuation startup")
                continuation_hits = []
                for seq, event in zip(events["sequences"], events["lineage"]):
                    first = _steps(fixture_id, seq["steps"])
                    if first is not None:
                        continuation_hits.append({"kind": event["kind"],
                                                  "offset": event["completed_offset_seconds"],
                                                  "call_index": first})
                    if event["goal_reached"] is not (first is not None):
                        raise Stage5AuditError("native goal flag differs from independent safety state")
                native_stage = next(item for item in stages
                                    if item["name"] == "native_startup_and_continuation")
                timing = read_json(_path(root, slot["native_completion_timing"]))
                observation_end = (native_stage["started_offset_seconds"]
                                   + timing["search_stopped"])
                if observation_end > config["total_budget_seconds"] + config["cleanup_tolerance_seconds"]:
                    raise Stage5AuditError("native observation ended after protocol budget")
                warmup_timing = warmup["native_timing_seconds"]
                pre = max(0.0, common["elapsed_seconds"] - warmup_timing["adapter_total"])
                hits = [(pre + warmup_timing["setup_before_fuzz"]
                         + event["completed_offset_seconds"], "warmup",
                         warmup_first[event["sequence_index"]])
                        for event in warmup["lineage"] if event["goal_reached"]]
                aug_stage = next((item for item in stages
                                  if item["name"] == "symbolic_augmentation"), None)
                if confirmed and aug_stage:
                    hits.append((aug_stage["finished_offset_seconds"], "augmentation",
                                 confirmed[0]["first_violation_call_index"]))
                hits.extend((native_stage["started_offset_seconds"]
                             + timing["search_started"] + hit["offset"],
                             "native_import" if hit["kind"] == "startup_replay"
                             else "native_continuation", hit["call_index"])
                            for hit in continuation_hits)
                first_hit = min(hits) if hits else None
                if first_hit and first_hit[0] > config["total_budget_seconds"]:
                    raise Stage5AuditError("property finding occurred after chargeable budget")
                rows.append({"fixture_id": fixture_id, "repeat": repeat, "arm": arm,
                             "evaluation_valid": True, "status": "completed",
                             "confirmed_violation": first_hit is not None,
                             "first_violation_seconds": first_hit[0] if first_hit else None,
                             "first_violation_stage": first_hit[1] if first_hit else "right_censored",
                             "first_violation_call_index": first_hit[2] if first_hit else None,
                             "observation_end_seconds": observation_end,
                             "censor_seconds": None if first_hit else observation_end,
                             "warmup_violation": bool(warmup_hits),
                             "augmentation_confirmations": len(confirmed),
                             "generated_candidates": generated_candidates,
                             "concrete_executed_candidates": concrete_candidates,
                             "solver_seconds": solver_seconds,
                             "replay_seconds": replay_seconds,
                             "query_statuses": dict(query_statuses),
                             "candidate_statuses": dict(candidate_statuses),
                             "two_step_only_confirmations": sum(item["two_step_only"] for item in confirmed),
                             "one_queries": sum(q["suffix_length"] == 1 for q in slot["queries"]),
                             "two_queries": sum(q["suffix_length"] == 2 for q in slot["queries"]),
                             "native_sequences": len(events["sequences"]),
                             "native_mutations": sum(e["kind"] == "mutation" for e in events["lineage"]),
                             "charged_seconds": slot["budget"]["charged_wall_seconds"]})
    expected = len(config["fixtures"]) * len(config["repeats"]) * len(config["arms"])
    manifest_slots = manifest.get("slots", [])
    keys = [(item.get("fixture_id"), item.get("repeat"), item.get("arm"))
            for item in manifest_slots]
    if len(keys) != len(set(keys)) or set(keys) != {
            (row["fixture_id"], row["repeat"], row["arm"]) for row in rows}:
        raise Stage5AuditError("formal manifest slots differ from raw block records")
    for failed in manifest.get("failed_block_attempts", []):
        reference = Path(failed.get("record", ""))
        if "failed-attempts" not in reference.parts or "blocks" in reference.parts:
            raise Stage5AuditError("failed attempt is not isolated from official blocks")
    if require_complete and (len(rows) != 240 or blocks != 60 or expected != 240):
        raise Stage5AuditError("formal 240-slot matrix is incomplete")
    groups = {}
    for fixture_id in config["fixtures"]:
        for arm in config["arms"]:
            subset = [row for row in rows if row["fixture_id"] == fixture_id
                      and row["arm"] == arm and row["evaluation_valid"]]
            groups[f"{fixture_id}:{arm}"] = {
                "valid_slots": len(subset),
                "confirmed_violations": sum(row["confirmed_violation"] for row in subset),
                "warmup_violations": sum(row["warmup_violation"] for row in subset),
                "augmentation_confirmations": sum(row["augmentation_confirmations"] for row in subset),
                "generated_candidates": sum(row["generated_candidates"] for row in subset),
                "concrete_executed_candidates": sum(row["concrete_executed_candidates"] for row in subset),
                "solver_seconds": sum(row["solver_seconds"] for row in subset),
                "replay_seconds": sum(row["replay_seconds"] for row in subset),
                "query_statuses": dict(sum((Counter(row["query_statuses"]) for row in subset), Counter())),
                "two_step_only_confirmations": sum(row["two_step_only_confirmations"] for row in subset),
                "one_queries": sum(row["one_queries"] for row in subset),
                "two_queries": sum(row["two_queries"] for row in subset),
            }
    result = {"schema_version": 1,
              "status": "passed" if all(row["evaluation_valid"] for row in rows)
              and (not require_complete or len(rows) == expected) else "incomplete",
              "study_id": config["study_id"], "slot_count": len(rows),
              "common_block_count": blocks, "groups": groups, "rows": rows,
              "method": "raw Medusa campaign/events, typed Halmos model, Foundry logs, native candidate replay, independent arithmetic"}
    if output:
        write_json(output, result)
    return result


def write_stage5_results(audit: dict, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / "summary.json", {key: audit[key] for key in
               ("schema_version", "status", "study_id", "slot_count",
                "common_block_count", "groups")})
    valid = [row for row in audit["rows"] if row["evaluation_valid"]]
    if valid:
        fields = list(valid[0])
        with (directory / "observations.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(valid)
    lines = ["# Stage 5 bounded suffix comparison", "",
             f"Independent raw audit: {audit['status']} ({audit['slot_count']} slots).", "",
             "| Fixture | Arm | Valid | Confirmed violations | Two-step-only confirmations |",
             "| --- | --- | ---: | ---: | ---: |"]
    for key, item in audit["groups"].items():
        fixture, arm = key.split(":")
        lines.append(f"| {fixture} | {arm} | {item['valid_slots']} | "
                     f"{item['confirmed_violations']} | {item['two_step_only_confirmations']} |")
    lines += ["", "Candidate confirmations are not separate vulnerabilities. Repaired-version misses are finite test outcomes, not proofs of global safety. Different arms use a shared warmup but later Medusa mutation RNG remains uncontrolled.", ""]
    (directory / "summary.md").write_text("\n".join(lines))
