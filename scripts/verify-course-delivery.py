#!/usr/bin/env python3
"""Verify an extracted course package using only Python's standard library.

This checks package integrity and public CSV/summary consistency. It does not
read native event streams or replace the independent Stage 3/4 raw audits.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys


MANIFEST = "COURSE_MANIFEST.json"
HEX256 = re.compile(r"[0-9a-f]{64}")
ARMS = {"native_resume", "concrete_augment", "symbolic_augment"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    require(isinstance(value, dict), f"JSON object required: {path.name}")
    return value


def safe_relative(value: object) -> str:
    require(isinstance(value, str) and bool(value), "empty or non-string relative path")
    require("\\" not in value and ":" not in value and "\x00" not in value,
            f"unsafe relative path: {value!r}")
    parts = value.split("/")
    require(not PurePosixPath(value).is_absolute() and
            all(part not in {"", ".", ".."} for part in parts),
            f"unsafe relative path: {value!r}")
    return value


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def regular_files(root: Path) -> set[str]:
    files = set()

    def walk_error(error: OSError) -> None:
        raise error

    for directory, dirs, names in os.walk(root, followlinks=False, onerror=walk_error):
        for name in dirs + names:
            path = Path(directory) / name
            relative = safe_relative(path.relative_to(root).as_posix())
            mode = path.lstat().st_mode
            require(not stat.S_ISLNK(mode), f"symbolic link is not allowed: {relative}")
            require(stat.S_ISDIR(mode) or stat.S_ISREG(mode),
                    f"non-regular entry is not allowed: {relative}")
            if stat.S_ISREG(mode):
                files.add(relative)
    return files


def verify_manifest(root: Path) -> dict:
    actual = regular_files(root)
    require(MANIFEST in actual, f"missing {MANIFEST}")
    manifest = read_json(root / MANIFEST)
    require(type(manifest.get("schema_version")) is int and manifest["schema_version"] == 1,
            "unsupported course manifest schema")
    require(isinstance(manifest.get("base_git_commit"), str) and
            bool(manifest["base_git_commit"].strip()), "missing base_git_commit")
    rows = manifest.get("files")
    require(isinstance(rows, list) and bool(rows), "manifest files must be a nonempty list")
    expected = set()
    total_bytes = 0
    for row in rows:
        require(isinstance(row, dict), "manifest file entry must be an object")
        relative = safe_relative(row.get("path"))
        require(relative != MANIFEST, "manifest must exclude itself")
        require(relative not in expected, f"duplicate manifest path: {relative}")
        expected.add(relative)
        size, checksum = row.get("size_bytes"), row.get("sha256")
        require(type(size) is int and size >= 0, f"invalid size: {relative}")
        require(isinstance(checksum, str) and HEX256.fullmatch(checksum) is not None,
                f"invalid SHA-256: {relative}")
        total_bytes += size
    missing = sorted(expected - actual)
    extra = sorted(actual - expected - {MANIFEST})
    require(not missing, f"missing package files: {missing}")
    require(not extra, f"unlisted package files: {extra}")
    for row in rows:
        path = root / row["path"]
        require(path.stat().st_size == row["size_bytes"], f"size mismatch: {row['path']}")
        require(digest(path) == row["sha256"], f"SHA-256 mismatch: {row['path']}")
    return {"status": "passed", "base_git_commit": manifest["base_git_commit"],
            "file_count": len(rows), "total_bytes": total_bytes}


def verify_original_checksums(root: Path, stage: str) -> dict:
    directory = root / "evidence" / stage
    expected = set()
    for line in (directory / "checksums.sha256").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        require(match is not None, f"malformed original checksum line in {stage}")
        checksum, relative = match.groups()
        relative = safe_relative(relative)
        require(relative not in expected and relative != "checksums.sha256",
                f"duplicate or self-referential checksum in {stage}: {relative}")
        expected.add(relative)
        path = directory / relative
        require(path.is_file(), f"missing {stage} evidence: {relative}")
        require(digest(path) == checksum, f"original {stage} checksum differs: {relative}")
    require(expected == regular_files(directory) - {"checksums.sha256"},
            f"original {stage} checksum list does not cover exactly its evidence files")
    return {"status": "passed", "checked_files": len(expected)}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        require(bool(reader.fieldnames) and len(set(reader.fieldnames)) == len(reader.fieldnames),
                f"missing or duplicate CSV columns: {path}")
        rows = list(reader)
    require(all(None not in row and all(value is not None for value in row.values())
                for row in rows), f"malformed CSV row: {path}")
    require(len({row["slot_id"] for row in rows}) == len(rows), f"duplicate CSV slots: {path}")
    return rows


def boolean(row: dict, key: str) -> bool:
    require(row[key] in {"True", "False"}, f"invalid CSV boolean {key}: {row[key]!r}")
    return row[key] == "True"


def count(row: dict, key: str) -> int:
    require(re.fullmatch(r"0|[1-9][0-9]*", row[key]) is not None,
            f"invalid CSV count {key}: {row[key]!r}")
    return int(row[key])


def number(row: dict, key: str) -> float:
    value = float(row[key])
    require(math.isfinite(value) and value >= 0, f"invalid CSV number {key}")
    return value


def compare(actual: object, expected: object, label: str) -> None:
    require(actual == expected, f"{label} differs: calculated {actual!r}, published/expected {expected!r}")


def verify_stage3(root: Path) -> dict:
    directory = root / "evidence/stage3"
    rows = read_csv(directory / "observations.csv")
    summary = read_json(directory / "summary.json")
    fixtures = {"phase_counter", "bounded_ledger", "range_gate", "workflow_gate"}
    profiles = {
        "b08-native": ("native_resume", 8.0, ""),
        "b08-concrete": ("concrete_augment", 8.0, ""),
        "b08-symbolic-q075": ("symbolic_augment", 8.0, "0.75"),
        "b32-native": ("native_resume", 32.0, ""),
        "b32-concrete": ("concrete_augment", 32.0, ""),
        "b32-symbolic-q050": ("symbolic_augment", 32.0, "0.5"),
        "b32-symbolic-q075": ("symbolic_augment", 32.0, "0.75"),
        "b32-symbolic-q150": ("symbolic_augment", 32.0, "1.5"),
    }
    expected_ids = {f"{fixture}/repeat-{repeat:02d}/{profile}"
                    for fixture in fixtures for repeat in range(1, 11) for profile in profiles}
    compare({row["slot_id"] for row in rows}, expected_ids, "Stage 3 frozen matrix")
    groups, aggregate = defaultdict(list), defaultdict(list)
    for row in rows:
        profile = row["profile_id"]
        arm, budget, limit = profiles[profile]
        compare((row["arm"], number(row, "total_budget_seconds"),
                 row["goal_invocation_limit_seconds"]), (arm, budget, limit), "Stage 3 profile")
        compare(row["slot_id"], f"{row['fixture_id']}/repeat-{count(row, 'repeat_id'):02d}/{profile}",
                "Stage 3 slot identity")
        require(number(row, "observation_end_seconds") <= number(row, "charged_end_seconds") <= budget,
                "Stage 3 observation/charge exceeds declared boundary")
        groups[(row["fixture_id"], profile)].append(row)
        aggregate[profile].append(row)
    published = {(item["fixture_id"], item["profile_id"]): item for item in summary["profiles"]}
    compare(len(published), len(summary["profiles"]), "Stage 3 unique summary profiles")
    compare(set(groups), set(published), "Stage 3 summary profile keys")
    for key, records in groups.items():
        item = published[key]
        compare(len(records), item["runs"], f"Stage 3 {key} runs")
        compare(sum(boolean(row, "goal_reached") for row in records), item["goal_hits"],
                f"Stage 3 {key} goal hits")
        compare(dict(Counter(row["miss_or_hit_reason"] for row in records)),
                item["miss_or_hit_reasons"], f"Stage 3 {key} reasons")
    blocks = {(row["fixture_id"], row["repeat_id"]) for row in rows}
    counts = {"slot_count": len(rows), "common_block_count": len(blocks),
              "goal_hit_count": sum(boolean(row, "goal_reached") for row in rows),
              "complete_sequence_count": sum(count(row, "completed_sequences") for row in rows)}
    for key, value in counts.items():
        compare(value, summary[key], f"Stage 3 summary {key}")
    compare(counts, {"slot_count": 320, "common_block_count": 40,
                     "goal_hit_count": 243, "complete_sequence_count": 791282}, "Stage 3 frozen counts")
    by_profile = {key: {"hits": sum(boolean(row, "goal_reached") for row in records),
                        "slots": len(records)} for key, records in sorted(aggregate.items())}
    expected_hits = {"b08-native": 17, "b08-concrete": 22, "b08-symbolic-q075": 39,
                     "b32-native": 20, "b32-concrete": 25, "b32-symbolic-q050": 40,
                     "b32-symbolic-q075": 40, "b32-symbolic-q150": 40}
    compare(by_profile, {key: {"hits": value, "slots": 40} for key, value in expected_hits.items()},
            "Stage 3 aggregate hits")
    manifest = read_json(directory / "formal-manifest.json")
    compare((manifest["status"], manifest["evaluation_valid_count"]), ("complete", 320),
            "Stage 3 published completion record")
    compare(summary["audit_status"], "passed", "Stage 3 published audit status")
    return {**counts, "profile_hits": by_profile,
            "evaluation_validity": "published completion/audit status; not re-audited from raw events"}


def verify_stage4(root: Path) -> dict:
    directory = root / "evidence/stage4"
    rows = read_csv(directory / "observations.csv")
    summary = read_json(directory / "summary.json")
    groups, blocks = defaultdict(list), defaultdict(list)
    versions = {"accounting_flawed", "accounting_repaired"}
    identities = {(row["fixture_id"], count(row, "repeat_id"), row["arm"]) for row in rows}
    compare(identities, {(version, repeat, arm) for version in versions
                         for repeat in range(1, 11) for arm in ARMS}, "Stage 4 frozen matrix")
    require(len(rows) == 60 and all(boolean(row, "evaluation_valid") for row in rows),
            "Stage 4 must contain 60 evaluation-valid public observations")
    censored = []
    for row in rows:
        compare(number(row, "budget_limit_seconds"), 32.0, "Stage 4 budget")
        require(number(row, "observation_end_seconds") <= number(row, "charged_end_seconds") <= 32.0,
                "Stage 4 observation/charge exceeds declared boundary")
        hit = boolean(row, "violation_confirmed")
        compare(boolean(row, "right_censored"), not hit, "Stage 4 censor flag")
        if hit:
            compare(row["first_violation_stage"], "warmup", "Stage 4 first finding stage")
            require(number(row, "first_violation_seconds") <= number(row, "observation_end_seconds"),
                    "Stage 4 first finding falls outside observation window")
            compare(row["censor_seconds"], "", "Stage 4 hit censor value")
        else:
            compare(row["first_violation_seconds"], "", "Stage 4 miss has a finding time")
            compare(number(row, "censor_seconds"), number(row, "observation_end_seconds"),
                    "Stage 4 actual censor time")
            censored.append(number(row, "censor_seconds"))
        groups[f"{row['fixture_id']}:{row['arm']}"].append(row)
        blocks[(row["fixture_id"], row["repeat_id"])].append(row)
    calculated = {}
    for key, records in groups.items():
        calculated[key] = {
            "slots": len(records),
            "confirmed_violations": sum(boolean(row, "violation_confirmed") for row in records),
            "warmup_violations": sum(boolean(row, "warmup_violation") for row in records),
            "augmentation_violations": sum(boolean(row, "augmentation_violation") for row in records),
            "continuation_violations": sum(boolean(row, "continuation_violation") for row in records),
            "augmentation_statuses": dict(Counter(row["augmentation_status"] for row in records)),
            **{field: sum(count(row, field) for row in records) for field in
               ("generated_candidates", "concrete_executed_candidates", "confirmed_candidates")},
        }
    compare(calculated, summary["groups"], "Stage 4 published groups")
    warmup_blocks = 0
    for key, records in blocks.items():
        flags = {boolean(row, "warmup_violation") for row in records}
        require(len(records) == 3 and len(flags) == 1, f"Stage 4 shared warmup differs: {key}")
        if flags == {True}:
            warmup_blocks += 1
            compare(len({row["first_violation_seconds"] for row in records}), 1,
                    "Stage 4 shared warmup first-finding times")
    counts = {"slot_count": len(rows), "common_block_count": len(blocks),
              "complete_sequence_count": sum(count(row, "completed_sequences") for row in rows)}
    for key, value in counts.items():
        compare(value, summary[key], f"Stage 4 summary {key}")
    compare(counts, {"slot_count": 60, "common_block_count": 20,
                    "complete_sequence_count": 179244}, "Stage 4 frozen counts")
    compare(warmup_blocks, 10, "Stage 4 distinct positive warmup blocks")
    compare(sum(boolean(row, "violation_confirmed") for row in rows), 30, "Stage 4 positive arm slots")
    for key, group in calculated.items():
        compare(group["confirmed_violations"], 10 if key.startswith("accounting_flawed:") else 0,
                f"Stage 4 {key} violation count")
    later_candidates = calculated["accounting_flawed:symbolic_augment"]["confirmed_candidates"]
    compare(later_candidates, 9, "Stage 4 later symbolic confirmations")
    repaired_timeouts = calculated["accounting_repaired:symbolic_augment"]["augmentation_statuses"]
    compare(repaired_timeouts, {"timeout": 10}, "Stage 4 repaired symbolic augmentation outcomes")
    compare(summary["status"], "passed", "Stage 4 published status")
    return {**counts, "confirmed_violation_slots": 30, "distinct_positive_warmup_blocks": warmup_blocks,
            "later_symbolic_confirmed_candidates": later_candidates,
            "repaired_symbolic_augmentation_timeouts": 10, "right_censored_slots": len(censored),
            "actual_censor_seconds": {"minimum": min(censored), "maximum": max(censored)},
            "groups": calculated}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd(),
                        help="extracted package root (default: current directory)")
    args = parser.parse_args()
    result = {"schema_version": 1, "verification_kind": "public_evidence_consistency",
              "raw_record_audit_performed": False}
    try:
        root = args.root.resolve(strict=True)
        require(root.is_dir(), "package root must be a directory")
        result["package_integrity"] = verify_manifest(root)
        result["original_evidence_checksums"] = {
            stage: verify_original_checksums(root, stage) for stage in ("stage3", "stage4")}
        result["stage3"] = verify_stage3(root)
        result["stage4"] = verify_stage4(root)
        result["status"] = "passed"
        result["limitations"] = [
            "CSV aggregates and published summaries are checked; raw execution records are not bundled here.",
            "Mutation counts and cross-tool correctness require the separate full raw-record audits.",
            "Checksums detect changes relative to the supplied manifests; they are not a digital signature.",
        ]
    except (OSError, ValueError, KeyError, TypeError, csv.Error) as error:
        result["status"] = "failed"
        result["error"] = str(error)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
