#!/usr/bin/env python3
"""Publish a path-safe Stage 4 extract without altering archived raw runs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
from statistics import median
from collections import Counter
import tarfile


ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reference(value: str) -> dict:
    path = Path(value).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise ValueError(f"raw evidence path is missing or outside the repository: {value}")
    return {"path": str(path.relative_to(ROOT)), "sha256": sha(path), "bytes": path.stat().st_size}


def acceptance(demo: Path) -> dict:
    report = read(demo / "report.json")
    if report.get("status") != "safety_confirmed" or report.get("confirmed_count") != 1:
        raise ValueError("demo did not confirm one safety-property violation")
    attempts = [attempt for attempt in report["attempts"] if "property_evidence" in attempt]
    if len(attempts) != 1:
        raise ValueError("demo has ambiguous confirmed attempts")
    attempt = attempts[0]
    selected = next(prefix for prefix in report["prefixes"]
                    if prefix["case_id"] == attempt["case_id"])
    flawed = read(Path(attempt["admission"]["observation"]))
    repaired = read(Path(attempt["repaired_evidence"]["native_observation"]))
    flawed_sequences = [sequence for sequence in flawed["sequences"]
                        if sequence["medusa_hash"] == attempt["admission"]["medusa_hash"]
                        and sequence.get("is_complete_sequence") is True]
    repaired_sequences = [sequence for sequence in repaired["sequences"]
                          if sequence.get("is_complete_sequence") is True]
    if len(flawed_sequences) != 1 or len(repaired_sequences) != 1:
        raise ValueError("native demo sequence was not uniquely executed")
    full = flawed_sequences[0]
    safe = repaired_sequences[0]
    call_keys = ("from", "to", "calldata", "value", "block_number", "block_timestamp")
    if (len(full["steps"]) != len(safe["steps"])
            or any(any(left[key] != right[key] for key in call_keys)
                   for left, right in zip(full["steps"], safe["steps"]))):
        raise ValueError("flawed and repaired native replays did not execute the same calls")
    if not full["steps"][-1]["observe"][3] or safe["steps"][-1]["observe"][3]:
        raise ValueError("demo's two native property outcomes disagree with the report")
    before = attempt["property_evidence"]["before_suffix"]
    after = attempt["property_evidence"]["after_suffix"]
    repaired_after = attempt["repaired_evidence"]["after_suffix"]
    if (before["allocated"] != before["spent"] + before["remaining"]
            or after["allocated"] == after["spent"] + after["remaining"]
            or repaired_after["allocated"] != repaired_after["spent"] + repaired_after["remaining"]):
        raise ValueError("independent accounting calculation contradicts demo report")
    return {
        "schema_version": 1,
        "status": "safety_confirmed",
        "property": "allocated == spent + remaining",
        "scope": "one known inert local accounting defect and its repaired variant",
        "selected_prefix": {
            "case_id": selected["case_id"],
            "native_file": reference(selected["native_path"]),
            "steps": [{key: step[key] for key in (
                "from", "to", "calldata", "value", "actual_block", "actual_timestamp",
                "status", "observe", "invariant_holds", "property_holds")}
                for step in selected["steps"]],
            "warmup_record": reference(report["warmup"]["output_path"]),
        },
        "halmos": {"argument": attempt["candidate"]["argument"],
                   "model": reference(attempt["candidate"]["model_file"]),
                   "prefix_status": attempt["prefix_check"]["status"],
                   "solve_status": attempt["solve"]["status"]},
        "flawed_replay": {
            "fresh_foundry_status": attempt["replay"]["status"],
            "fresh_foundry_record": reference(attempt["replay"]["command_result"]["log_path"]),
            "native_sequence_file": reference(attempt["admission"]["native_path"]),
            "native_record": reference(attempt["admission"]["observation"]),
            "medusa_hash": full["medusa_hash"],
            "full_sequence": [{key: step[key] for key in (
                "from", "to", "calldata", "value", "block_number", "block_timestamp",
                "status", "observe", "invariant_holds", "property_holds")}
                for step in full["steps"]],
            "first_violation_call_index": attempt["property_evidence"]["first_violation"]["call_index"],
            "before_suffix": before, "after_suffix": after,
            "admission_evidence": attempt["admission"]["evidence"],
        },
        "repaired_replay": {
            "fresh_foundry_status": attempt["repaired_replay"]["status"],
            "fresh_foundry_record": reference(attempt["repaired_replay"]["command_result"]["log_path"]),
            "native_sequence_file": reference(attempt["repaired_evidence"]["native_path"]),
            "native_record": reference(attempt["repaired_evidence"]["native_observation"]),
            "full_sequence": [{key: step[key] for key in (
                "from", "to", "calldata", "value", "block_number", "block_timestamp",
                "status", "observe", "invariant_holds", "property_holds")}
                for step in safe["steps"]],
            "after_suffix": repaired_after,
        },
        "observer_neutrality": report["observer_control"]["status"],
        "roundtrip": report["roundtrip"]["status"],
        "report_file": reference(str(demo / "report.json")),
    }


def candidate_audit(study: Path, config: dict) -> dict:
    rows = []
    for fixture in config["fixtures"]:
        for repeat in config["repeats"]:
            block = study / "blocks" / fixture / f"repeat-{repeat:02d}"
            for profile in config["profiles"]:
                arm = profile["arm"]
                path = block / "profiles" / profile["profile_id"] / "augmentation/augmentation.json"
                if not path.is_file():
                    continue
                augmentation = read(path)
                for index, attempt in enumerate(augmentation.get("attempts", [])):
                    steps = attempt.get("execution", {}).get("steps")
                    computed = None
                    if steps is not None:
                        if not isinstance(steps, list) or not steps:
                            raise ValueError("candidate execution has no steps")
                        for step in steps:
                            observed = step.get("observe")
                            if (not isinstance(observed, list) or len(observed) != 4
                                    or type(observed[3]) is not bool):
                                raise ValueError("candidate state projection is malformed")
                            allocated, spent, remaining = map(int, observed[:3])
                            holds = allocated == spent + remaining
                            if (observed[3] is holds or step.get("property_holds") is not holds
                                    or step.get("invariant_holds") is not True
                                    or step.get("observer_state_unchanged") is not True
                                    or step.get("state_root_before_observer")
                                    != step.get("state_root_after_observer")):
                                raise ValueError("candidate property or observation disagrees with raw state")
                            computed = holds
                    status = attempt.get("validation_status", "unclassified")
                    if ((status == "accepted" and computed is not False)
                            or (status == "goal_false" and computed is not True)):
                        raise ValueError("candidate classification disagrees with computed property")
                    if fixture == "accounting_repaired" and computed is False:
                        raise ValueError("repaired candidate violated the property")
                    rows.append({"slot_id": f"{fixture}/repeat-{repeat:02d}/{profile['profile_id']}",
                                 "arm": arm, "candidate_index": index,
                                 "argument": attempt.get("argument"),
                                 "validation_status": status,
                                 "concretely_executed": steps is not None,
                                 "property_holds_after": computed})
    counts = Counter((row["slot_id"].split("/")[0], row["arm"], row["validation_status"])
                     for row in rows)
    return {"schema_version": 1, "status": "passed", "candidate_count": len(rows),
            "concretely_executed_count": sum(row["concretely_executed"] for row in rows),
            "repaired_property_violations": 0,
            "counts": [{"fixture_id": fixture, "arm": arm, "validation_status": status,
                        "count": count} for (fixture, arm, status), count in sorted(counts.items())],
            "rows": rows}


def superseded_run() -> dict:
    root = ROOT / "runs/stage4-formal-v1"
    manifest = read(root / "manifest.json")
    failed = read(root / "blocks/accounting_repaired/repeat-06/profiles/safety-concrete/campaign.json")
    native = read(root / "blocks/accounting_repaired/repeat-06/profiles/safety-concrete/native/campaign.json")
    if (manifest.get("status") != "incomplete" or manifest.get("evaluation_valid_count") != 45
            or failed.get("evaluation_valid") is not False
            or failed.get("failure", {}).get("classification") != "campaign_deadline"
            or native.get("stop_reason") != "time_limit"):
        raise ValueError("superseded v1 failure record differs from the preserved raw attempt")
    return {"schema_version": 1, "status": "superseded_incomplete",
            "study_id": manifest["study_id"],
            "raw_directory": "runs/stage4-formal-v1",
            "valid_slots_before_stop": manifest["evaluation_valid_count"],
            "failed_block": "accounting_repaired/repeat-06",
            "failed_arm": "concrete_augment",
            "classification": failed["failure"]["classification"],
            "charged_wall_seconds": failed["budget"]["charged_wall_seconds"],
            "budget_seconds": failed["budget"]["budget_seconds"],
            "native_search_stop_reason": native["stop_reason"],
            "native_adapter_total_seconds": native["native_timing_seconds"]["adapter_total"],
            "native_stage_seconds_including_python_decode": next(
                stage["elapsed_seconds"] for stage in failed["stages"]
                if stage["name"] == "native_startup_and_continuation"),
            "cause": "compact event decoding consumed charged time beyond the v1 evidence reserve",
            "disposition": "v1 is excluded; v2 reserves nine seconds for native setup and evidence processing within the same 32-second budget and reruns all 60 slots"}


def transient_failure(study: Path, manifest: dict) -> dict:
    entries = manifest.get("failed_block_attempts", [])
    if len(entries) != 2 or any(
            entry.get("common_block_id") != "accounting_repaired/repeat-08"
            for entry in entries):
        raise ValueError("the preserved v2 tool-failure history differs from the manifest")
    failed = sorted((study / "failed-block-attempts/accounting_repaired/repeat-08")
                    .glob("attempt-*/profiles/safety-symbolic/campaign.json"))
    if len(failed) != 1:
        raise ValueError("the preserved v2 Medusa failure is missing or ambiguous")
    record = read(failed[0])
    log = failed[0].parent / "native/adapter.log"
    if (record.get("evaluation_valid") is not False
            or record.get("failure", {}).get("classification") != "tool_error"
            or "fatal error: concurrent map iteration and map write" not in log.read_text()):
        raise ValueError("the preserved v2 Medusa failure differs from raw evidence")
    return {"schema_version": 1, "status": "preserved_evaluation_invalid",
            "failed_block": "accounting_repaired/repeat-08",
            "failed_arm": "symbolic_augment",
            "classification": "tool_error",
            "cause": "Medusa v1.5.1 coverage-metrics goroutine crashed while iterating a concurrent map",
            "failed_campaign": reference(str(failed[0])),
            "adapter_log": reference(str(log)),
            "recovery": "the complete paired block was rerun with unchanged frozen inputs; the failed attempt remains in the raw archive",
            "completed_slot_count_excludes_failed_attempt": True}


def build(study: Path, demo: Path, output: Path) -> None:
    study, demo, output = study.resolve(), demo.resolve(), output.resolve()
    if output.exists():
        raise ValueError("evidence destination must be new")
    audit = read(study / "derived/audit.json")
    manifest = read(study / "manifest.json")
    if audit.get("status") != "passed" or audit.get("slot_count") != 60:
        raise ValueError("independent Stage 4 audit has not passed all 60 slots")
    if (manifest.get("status") != "complete" or manifest.get("result_count") != 60
            or manifest.get("evaluation_valid_count") != 60):
        raise ValueError("frozen formal manifest is incomplete")
    output.mkdir(parents=True)
    for source, name in ((study / "frozen-config.json", "formal-config.json"),
                         (study / "derived/audit.json", "audit.json"),
                         (study / "derived/observations.csv", "observations.csv"),
                         (study / "derived/summary.json", "summary.json"),
                         (study / "derived/summary.md", "summary.md")):
        shutil.copy2(source, output / name)
    (output / "freeze.json").write_text(json.dumps({
        "schema_version": 1,
        "study_id": manifest["study_id"],
        "config_sha256": manifest["config_sha256"],
        "execution_source_sha256": manifest["execution_source"]["content_sha256"],
        "execution_source_file_count": manifest["execution_source"]["file_count"],
        "adapter_sha256": manifest["medusa"]["adapter_sha256"],
        "medusa_version": manifest["medusa"]["version"],
        "lineage_patch_sha256": manifest["medusa"]["lineage_patch_sha256"],
        "completed_blocks": len(manifest["completed_blocks"]),
        "evaluation_valid_count": manifest["evaluation_valid_count"],
    }, indent=2, sort_keys=True) + "\n")
    (output / "acceptance.json").write_text(
        json.dumps(acceptance(demo), indent=2, sort_keys=True) + "\n")
    (output / "candidate-audit.json").write_text(
        json.dumps(candidate_audit(study, read(study / "frozen-config.json")),
                   indent=2, sort_keys=True) + "\n")
    (output / "superseded-run.json").write_text(
        json.dumps(superseded_run(), indent=2, sort_keys=True) + "\n")
    (output / "transient-failure.json").write_text(
        json.dumps(transient_failure(study, manifest), indent=2, sort_keys=True) + "\n")
    archive_path = ROOT / "artifacts/stage4-formal-v2.tar.gz"
    if archive_path.is_file():
        with tarfile.open(archive_path, "r:gz") as archive:
            first = archive.next()
            if first is None or first.name != "archive-manifest.json":
                raise ValueError("Stage 4 archive manifest is absent")
            stream = archive.extractfile(first)
            if stream is None:
                raise ValueError("Stage 4 archive manifest is unreadable")
            archive_manifest = json.loads(stream.read())
        (output / "archive.json").write_text(json.dumps({
            "schema_version": 1, "archive_name": archive_path.name,
            "sha256": sha(archive_path), "bytes": archive_path.stat().st_size,
            "archived_file_count": archive_manifest["file_count"],
            "archived_source_bytes": archive_manifest["total_bytes"],
            "availability": "complete raw archive saved locally under artifacts/; binary ignored by Git",
        }, indent=2, sort_keys=True) + "\n")
    groups = audit["groups"]
    flawed_hits = sum(group["confirmed_violations"] for key, group in groups.items()
                      if key.startswith("accounting_flawed:"))
    repaired_hits = sum(group["confirmed_violations"] for key, group in groups.items()
                       if key.startswith("accounting_repaired:"))
    result_lines = ["# Stage 4 result boundaries", "",
                    "This fixed 60-slot comparison tests one known, local, inert accounting defect and its repair. Every slot passed the independent raw-record audit.", "",
                    "| Version | Arm | Confirmed slots | First finding stages (warmup / augmentation / import / continuation) | Generated / concrete-executed / confirmed candidates | Median first finding (s, hits only) |",
                    "| --- | --- | ---: | ---: | ---: | ---: |"]
    for key, group in groups.items():
        fixture, arm = key.split(":")
        rows = [row for row in audit["rows"] if row["fixture_id"] == fixture and row["arm"] == arm]
        stage_counts = {stage: sum(row["first_violation_stage"] == stage for row in rows)
                        for stage in ("warmup", "augmentation", "native_import", "native_continuation")}
        first_times = [row["first_violation_seconds"] for row in rows
                       if row["first_violation_seconds"] is not None]
        first_text = f"{median(first_times):.3f}" if first_times else "—"
        result_lines.append(
            f"| {fixture} | {arm} | {group['confirmed_violations']}/{group['slots']} | "
            f"{stage_counts['warmup']} / {stage_counts['augmentation']} / "
            f"{stage_counts['native_import']} / {stage_counts['native_continuation']} | "
            f"{group['generated_candidates']} / {group['concrete_executed_candidates']} / "
            f"{group['confirmed_candidates']} | {first_text} |")
    result_lines.extend(["", "Each arm in a version/repeat block starts from the same executed Medusa warmup corpus. First findings and misses use charged time; a miss is censored at the actual search observation end, while 32 seconds is only the budget ceiling.", "",
                         "| Version | Arm | No prefix | No candidate | Bounded timeout | Invalid model | Replay mismatch | Other statuses | Total augmentation / solver / replay seconds |",
                         "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |"])
    for key, group in groups.items():
        fixture, arm = key.split(":")
        rows = [row for row in audit["rows"] if row["fixture_id"] == fixture and row["arm"] == arm]
        statuses = group["augmentation_statuses"]
        known = {"not_applicable", "completed", "no_eligible_prefix", "no_candidate", "timeout",
                 "invalid_model", "replay_mismatch"}
        other = {name: count for name, count in statuses.items() if name not in known}
        result_lines.append(
            f"| {fixture} | {arm} | {statuses.get('no_eligible_prefix', 0)} | "
            f"{statuses.get('no_candidate', 0)} | {statuses.get('timeout', 0)} | "
            f"{statuses.get('invalid_model', 0)} | {statuses.get('replay_mismatch', 0)} | "
            f"{other or '—'} | {sum(row['augmentation_seconds'] for row in rows):.3f} / "
            f"{sum(row['solver_seconds'] for row in rows):.3f} / "
            f"{sum(row['replay_seconds'] for row in rows):.3f} |")
    result_lines.extend(["", "Rejected candidates remain recorded in each audited observation. A bounded timeout is an augmentation outcome, never proof that the repaired contract is safe. Tool or evidence failures are evaluation-invalid and cannot be included in the 60 audited slots.", "",
                         "The v2 run encountered one Medusa coverage-metrics crash in a repaired symbolic slot. The failed paired block is preserved separately; its three arms were rerun under identical frozen inputs and only the completed block enters the 60-slot matrix. The earlier v1 budget-overrun attempt is also excluded.", "",
                         "The native control restarts Medusa from the paired warmup corpus. Medusa's internal corpus chooser and mutation strategy chooser remain clock-seeded, so paired arms do not have identical continuation trajectories. Any difference is descriptive for this one case; it is not a general performance claim.", "",
                         "The only supported conclusion is that symbolic-assisted input generation and concrete safety-violation confirmation work for one known local teaching regression, with a corresponding repaired comparison. This does not identify a new real-world vulnerability or prove the repaired version globally safe.", ""])
    (output / "RESULTS.md").write_text("\n".join(result_lines))
    lines = ["# Stage 4 evidence index", "", "Owner: Edison Li", "",
             "This bundle is a path-safe extract from real local Medusa, Halmos, and Foundry runs.",
             "The full raw run remains in the local `runs/` directory and is identified by checksums.", "",
             f"Independent audit: **{audit['slot_count']}/60 slots passed**.",
             f"Confirmed flawed-version slot findings: **{flawed_hits}/30**.",
             f"Repaired-version slot findings: **{repaired_hits}/30**.", "",
             "- [Arithmetic property and defect](../../fixtures/ACCOUNTING_PROPERTY.md)",
             "- [First-use demo](../../STAGE4_DEMO.md)",
             "- [Technical plan](../../STAGE4_TECH_PLAN.md)",
             "- [Stage 4 acceptance record](../../STAGE4_ACCEPTANCE.md)",
             "- [Real acceptance extract](acceptance.json)",
             "- [All generated and rejected candidate outcomes](candidate-audit.json)",
             "- [Preserved incomplete v1 attempt](superseded-run.json)",
             "- [Preserved v2 Medusa tool failure](transient-failure.json)",
             "- [Frozen formal config](formal-config.json)",
             "- [Execution freeze hashes](freeze.json)",
             "- [Independent raw-record audit](audit.json)",
             "- [60 slot observations](observations.csv)",
             "- [Result summary](summary.md)",
             "- [Interpretation and negative outcomes](RESULTS.md)",
             "- [Machine-readable summary](summary.json)",
             "- [Local raw archive metadata](archive.json)",
             "- [Checksums](checksums.sha256)", "",
             "The comparison concerns one known teaching defect. It does not establish a new real-world finding or prove the repaired contract globally safe.", ""]
    (output / "INDEX.md").write_text("\n".join(lines))
    files = sorted(path for path in output.rglob("*") if path.is_file()
                   and path.name != "checksums.sha256")
    (output / "checksums.sha256").write_text(
        "".join(f"{sha(path)}  {path.relative_to(output)}\n" for path in files))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--study", type=Path, default=ROOT / "runs/stage4-formal-v2")
    parser.add_argument("--demo", type=Path, default=ROOT / "runs/stage4-demo-smoke-01")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/stage4")
    args = parser.parse_args()
    build(args.study, args.demo, args.output)
    print(args.output / "INDEX.md")


if __name__ == "__main__":
    main()
