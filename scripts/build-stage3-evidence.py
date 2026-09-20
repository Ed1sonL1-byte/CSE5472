#!/usr/bin/env python3
"""Build the small, path-sanitized Stage 3 evidence bundle."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
RUN = ROOT / "runs/stage3-formal-02"
DERIVED = RUN / "derived"
VERIFY = ROOT / "runs/stage3-formal-offline-verify-01"
ARCHIVE = ROOT / "artifacts/stage3-formal-v1.tar.gz"
DESTINATION = ROOT / "evidence/stage3"

COPIED = (
    "summary.json",
    "summary.md",
    "observations.csv",
    "goal-limit-hits.svg",
    "charged-cost.svg",
    "total-budget-goal-hits.svg",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sanitize(value: object) -> object:
    if isinstance(value, str):
        return value.replace(f"{ROOT}/", "").replace(str(HOME), "~")
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize(item) for key, item in value.items()}
    return value


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def logical_summary_sha256(path: Path) -> str:
    value = read_json(path)
    value.pop("content_sha256", None)
    for row in value.get("workflow_gate", []):
        row.pop("event_stream_path", None)
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def build() -> None:
    required = [RUN / "manifest.json", DERIVED / "audit.json", ARCHIVE,
                VERIFY / "archive-manifest.json"]
    required.extend(DERIVED / name for name in COPIED)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ValueError(f"missing Stage 3 evidence inputs: {missing}")

    DESTINATION.mkdir(parents=True, exist_ok=True)
    for name in ("baseline.json", "protocol-audit.json"):
        path = DESTINATION / name
        write_json(path, sanitize(read_json(path)))
    shutil.copy2(ROOT / "configs/stage3-study.json", DESTINATION / "formal-config.json")
    for name in COPIED:
        source = DERIVED / name
        if name.endswith(".json"):
            write_json(DESTINATION / name, sanitize(read_json(source)))
        else:
            shutil.copy2(source, DESTINATION / name)

    manifest = read_json(RUN / "manifest.json")
    manifest.get("host", {}).pop("hostname", None)
    write_json(DESTINATION / "formal-manifest.json", sanitize(manifest))
    write_json(DESTINATION / "audit.json", sanitize(read_json(DERIVED / "audit.json")))

    failed = read_json(ROOT / "runs/stage3-formal-01/manifest.json")
    write_json(DESTINATION / "superseded-run.json", sanitize({
        "schema_version": 1,
        "run": "runs/stage3-formal-01",
        "status": "superseded",
        "selected_for_results": False,
        "completed_blocks": len(failed["completed_blocks"]),
        "valid_results": failed["evaluation_valid_count"],
        "planned_results": failed["plan"]["distinct_slot_count"],
        "failed_block_attempts": failed["failed_block_attempts"],
        "reason": (
            "A symbolic augmentation timeout left a newly encoded native candidate that had not "
            "been committed to the accepted-entry list. Restart validation correctly rejected "
            "the entry/corpus count mismatch. The incomplete attempt was preserved, the fresh "
            "orphan was pruned with a regression test, and the complete 320-slot matrix was rerun "
            "from a new frozen execution snapshot as stage3-formal-02."
        ),
        "replacement": "runs/stage3-formal-02",
    }))

    archive_manifest = read_json(VERIFY / "archive-manifest.json")
    rebuilds = []
    for attempt in (1, 2):
        rebuilt = VERIFY / f"rebuilt-{attempt}"
        rebuilds.append({
            "attempt": attempt,
            "summary_sha256": sha256(rebuilt / "summary.json"),
            "logical_summary_sha256": logical_summary_sha256(rebuilt / "summary.json"),
            "observations_sha256": sha256(rebuilt / "observations.csv"),
            "markdown_sha256": sha256(rebuilt / "summary.md"),
        })
    if rebuilds[0] != {**rebuilds[1], "attempt": 1}:
        raise ValueError("offline archive rebuild outputs differ")
    archive = {
        "schema_version": 1,
        "status": "passed",
        "archive_path": "artifacts/stage3-formal-v1.tar.gz",
        "archive_bytes": ARCHIVE.stat().st_size,
        "archive_sha256": sha256(ARCHIVE),
        "archived_study_file_count": archive_manifest["file_count"],
        "archived_study_bytes": archive_manifest["total_bytes"],
        "study_manifest_sha256": archive_manifest["study_manifest_sha256"],
        "original_logical_summary_sha256": logical_summary_sha256(DERIVED / "summary.json"),
        "offline_rebuilds": rebuilds,
        "distribution": (
            "The complete archive is retained locally because its single-file size exceeds the "
            "GitHub release per-asset limit. This public evidence bundle contains its checksum, "
            "manifest summary, all 320 observations, and independently rebuilt reports."
        ),
    }
    if any(row["logical_summary_sha256"] != archive["original_logical_summary_sha256"]
           for row in rebuilds):
        raise ValueError("offline archive rebuild differs from the original logical summary")
    write_json(DESTINATION / "archive.json", archive)

    index = """# Stage 3 evidence index

This path-sanitized bundle summarizes the complete frozen Stage 3 study. The full 3.1 GB offline
archive remains at `artifacts/stage3-formal-v1.tar.gz`; its identity and offline verification are
recorded in `archive.json`.

| File | Evidence |
| --- | --- |
| `formal-config.json` | Frozen 320-slot matrix, seeds, budgets, query limits, and profile order |
| `formal-manifest.json` | Complete 40-block manifest, source/tool hashes, cache protocol, and no failed attempts |
| `audit.json` | Independent raw-event audit for all 320 slots |
| `summary.{json,md}` / `observations.csv` | Full descriptive results and every slot-level observation |
| `total-budget-goal-hits.svg` | Paired 8-second versus 32-second goal results |
| `goal-limit-hits.svg` | 0.50/0.75/1.50-second symbolic goal-invocation comparison |
| `charged-cost.svg` | Online charged-cost decomposition by profile |
| `protocol-audit.json` | Compact-format, timing, sequence-limit, codec, conversion, and storage smoke evidence |
| `baseline.json` | Stage 3 starting source, fixture, lockfile, patch, and Stage 2 evidence inventory |
| `superseded-run.json` | Preserved first formal attempt and the execution fix that required a full rerun |
| `archive.json` | Complete archive hash/size/file count and two independent offline rebuild hashes |
| `checksums.sha256` | SHA-256 for every other official file in this directory |

The study contains 320 valid slots in 40 shared-warmup blocks, 791,282 complete sequences, and
553,708 mutation events. It covers four repository-owned teaching state machines. Goal reachability
is not a vulnerability finding, and these descriptive results do not establish performance on
third-party contracts.
"""
    (DESTINATION / "INDEX.md").write_text(index)

    lines = []
    for path in sorted(DESTINATION.iterdir()):
        if path.is_file() and path.name != "checksums.sha256":
            lines.append(f"{sha256(path)}  {path.name}")
    (DESTINATION / "checksums.sha256").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    build()
    print(DESTINATION)
