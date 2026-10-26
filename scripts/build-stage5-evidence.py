#!/usr/bin/env python3
"""Rebuild compact Stage 5 evidence only from a passing raw audit."""

from __future__ import annotations

import argparse
from collections import Counter
import os
from pathlib import Path
import shutil
import statistics

from seedbridge.io import file_hash, read_json, write_json
from seedbridge.stage5_audit import audit_stage5, write_stage5_results


def _median(values: list[float]) -> str:
    return f"{statistics.median(values):.3f}" if values else "—"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--verification", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("evidence/stage5"))
    args = parser.parse_args()
    study, archive, verification, output = (
        args.study.resolve(), args.archive.resolve(),
        args.verification.resolve(), args.output.resolve())
    audited = audit_stage5(study)
    verified = read_json(verification / "verification.json")
    if (verified["status"] != "passed" or verified["slot_count"] != 240
            or verified["archive_sha256"] != file_hash(archive)):
        raise ValueError("relocated full archive verification is missing or inconsistent")
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "audit.json", audited)
    write_stage5_results(audited, output)
    write_json(output / "archive-verification.json", verified)
    shutil.copy2(study / "manifest.json", output / "formal-manifest.json")
    rows = audited["rows"]
    groups = audited["groups"]
    lines = ["# Stage 5 controlled comparison", "",
             "All 240 slots and 60 shared-warmup blocks passed the independent raw-record audit. The full archive was extracted into a new directory, checksummed, and audited again.", "",
             "The cases are local, self-authored teaching regressions. A candidate confirmation is one execution of a known property defect, not a new vulnerability.", "",
             "| Version | Strategy | Confirmed / 10 | Warmup | Augment confirmations | One / two queries | Median first confirmation (s) | Median censor (s) |",
             "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for key, group in groups.items():
        fixture, arm = key.split(":")
        selected = [row for row in rows if row["fixture_id"] == fixture
                    and row["arm"] == arm]
        first = [row["first_violation_seconds"] for row in selected
                 if row["confirmed_violation"]]
        censored = [row["censor_seconds"] for row in selected
                    if not row["confirmed_violation"]]
        lines.append(f"| {fixture} | {arm} | {group['confirmed_violations']}/10 | "
                     f"{group['warmup_violations']} | {group['augmentation_confirmations']} | "
                     f"{group['one_queries']} / {group['two_queries']} | "
                     f"{_median(first)} | {_median(censored)} |")
    lines += ["", "First-confirmation medians use confirmed slots only; censor medians use misses only. A higher hit proportion can coexist with a slower conditional median.", "",
             "## Discovery stage and query costs", "",
             "| Version | Strategy | Warmup / augment / native import / continuation first findings | Generated / concretely executed / confirmed candidates | Augment / solver / replay seconds | Query outcomes |",
             "| --- | --- | ---: | ---: | ---: | --- |"]
    for key, group in groups.items():
        fixture, arm = key.split(":")
        selected = [row for row in rows if row["fixture_id"] == fixture
                    and row["arm"] == arm]
        stages = Counter(row["first_violation_stage"] for row in selected)
        stage_text = " / ".join(str(stages[name]) for name in
                                ("warmup", "augmentation", "native_import",
                                 "native_continuation"))
        outcomes = ", ".join(f"{name}:{count}" for name, count in
                             sorted(group["query_statuses"].items())) or "none"
        augmentation_seconds = 0.0
        for row in selected:
            slot = read_json(study / "blocks" / fixture / f"repeat-{row['repeat']:02d}" /
                             "arms" / arm / "slot.json")
            augmentation_seconds += sum(float(stage["elapsed_seconds"])
                                        for stage in slot["stages"]
                                        if stage["name"] == "symbolic_augmentation")
        lines.append(f"| {fixture} | {arm} | {stage_text} | "
                     f"{group['generated_candidates']} / "
                     f"{group['concrete_executed_candidates']} / "
                     f"{group['augmentation_confirmations']} | "
                     f"{augmentation_seconds:.2f} / {group['solver_seconds']:.2f} / "
                     f"{group['replay_seconds']:.2f} | "
                     f"{outcomes} |")
    lines += ["", "## Interpretation boundaries", "",
             "Fixed-prefix mechanism tests independently confirm a two-call state dependency in each new flawed case. They do not prove that a one-call method cannot discover the same property failure after Medusa supplies a longer concrete prefix.",
             "A finding on suffix call two in the accounting control need not involve two symbolic inputs: a planned `open()` call has no argument. Only the two new mechanism cases demonstrate jointly solved, state-dependent `uint256` inputs.",
             "All arms received the same five-call cap, allowed function set, version/repeat warmup corpus, and charged total budget. The native control is a restart from that corpus. Later Medusa corpus and mutation chooser randomness remains uncontrolled; paired warmups do not imply paired continuation trajectories.",
             "A repaired-version miss is right-censored at the actual observation end and is finite testing evidence, not a global proof of safety. Timeouts, complete no-model results, missing prefixes, and tool or evidence errors have different meanings. Superseded v1 records were excluded from all v2 counts.", ""]
    (output / "RESULTS.md").write_text("\n".join(lines))
    evidence_files = ["FREEZE.json", "FREEZE-v1.json", "formal-config.json",
                      "formal-config-v1.json", "SMOKE.json", "INDEX.md",
                      "audit.json", "summary.json", "summary.md", "observations.csv",
                      "formal-manifest.json", "archive-verification.json",
                      "RESULTS.md", "python-tests.log", "go-tests.log",
                      "foundry-tests.log"]
    hashes = [f"{file_hash(output / name)}  {name}" for name in evidence_files]
    project = output.parents[1]
    for name in ("STAGE5_TECH_PLAN.md", "STAGE5_ACCEPTANCE.md",
                 "README.md", "fixtures/STAGE5_PROPERTIES.md"):
        target = project / name
        hashes.append(f"{file_hash(target)}  {os.path.relpath(target, output)}")
    hashes.append(f"{file_hash(archive)}  {os.path.relpath(archive, output)}")
    (output / "checksums.sha256").write_text("\n".join(hashes) + "\n")
    print(f"{audited['slot_count']} audited slots; results at {output / 'RESULTS.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
