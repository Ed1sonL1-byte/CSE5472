"""Offline Stage 3 descriptive reports built from the independent audit rows."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import html
import json
from pathlib import Path
import statistics

from .study_audit import audit_study, write_observations_csv


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _profile_summary(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["fixture_id"], row["profile_id"])].append(row)
    result = []
    for (fixture, profile), values in sorted(grouped.items()):
        values.sort(key=lambda item: item["repeat_id"])
        result.append({
            "fixture_id": fixture,
            "profile_id": profile,
            "arm": values[0]["arm"],
            "total_budget_seconds": values[0]["total_budget_seconds"],
            "goal_invocation_limit_seconds": values[0]["goal_invocation_limit_seconds"],
            "runs": len(values),
            "goal_hits": sum(row["goal_reached"] for row in values),
            "goal_rate": _mean([float(row["goal_reached"]) for row in values]),
            "auxiliary_confirmations": sum(
                row["auxiliary_concrete_goal_confirmed"] for row in values),
            "mean_observation_end_seconds": _mean(
                [row["observation_end_seconds"] for row in values]),
            "mean_charged_end_seconds": _mean([row["charged_end_seconds"] for row in values]),
            "mean_completed_sequences": _mean([row["completed_sequences"] for row in values]),
            "mean_new_sequences": _mean([row["sequence_new_count"] for row in values]),
            "mean_new_states": _mean([row["state_new_count"] for row in values]),
            "mean_new_coverage": _mean([row["coverage_new_count"] for row in values]),
            "miss_or_hit_reasons": dict(sorted(Counter(
                row["miss_or_hit_reason"] for row in values).items())),
            "trials": [{
                key: row[key] for key in (
                    "repeat_id", "goal_reached", "miss_or_hit_reason",
                    "observation_end_seconds", "charged_end_seconds",
                    "completed_sequences", "sequence_new_count", "state_new_count",
                    "coverage_new_count", "augmentation_status", "accepted_seed_count",
                )
            } for row in values],
        })
    return result


def _paired(rows: list[dict], config: dict) -> dict:
    lookup = {(row["fixture_id"], row["repeat_id"], row["profile_id"]): row for row in rows}
    profiles = config["profiles"]
    by_arm_budget = {
        (profile["arm"], float(profile["total_budget_seconds"])): profile["profile_id"]
        for profile in profiles if "total_budget" in profile["families"]
    }
    budget_pairs = []
    required_budget = {
        (arm, budget) for arm in ("native_resume", "concrete_augment", "symbolic_augment")
        for budget in (8.0, 32.0)
    }
    if required_budget <= set(by_arm_budget):
        for fixture in config["fixtures"]:
            for repeat in config["repeats"]:
                for arm in ("native_resume", "concrete_augment", "symbolic_augment"):
                    short = lookup[(fixture, repeat, by_arm_budget[(arm, 8.0)])]
                    long = lookup[(fixture, repeat, by_arm_budget[(arm, 32.0)])]
                    budget_pairs.append({
                        "fixture_id": fixture, "repeat_id": repeat, "arm": arm,
                        "goal_delta_32_minus_8": int(long["goal_reached"]) - int(short["goal_reached"]),
                        "state_delta_32_minus_8": long["state_new_count"] - short["state_new_count"],
                        "coverage_delta_32_minus_8": long["coverage_new_count"] - short["coverage_new_count"],
                        "sequence_delta_32_minus_8": long["sequence_new_count"] - short["sequence_new_count"],
                    })
    symbolic = {
        float(profile["goal_invocation_limit_seconds"]): profile["profile_id"]
        for profile in profiles
        if (profile["arm"] == "symbolic_augment"
            and float(profile["total_budget_seconds"]) == 32.0
            and "goal_invocation_limit" in profile["families"])
    }
    goal_pairs = []
    if {0.5, 0.75, 1.5} <= set(symbolic):
        for fixture in config["fixtures"]:
            for repeat in config["repeats"]:
                baseline = lookup[(fixture, repeat, symbolic[0.75])]
                for limit in (0.5, 1.5):
                    other = lookup[(fixture, repeat, symbolic[limit])]
                    goal_pairs.append({
                        "fixture_id": fixture, "repeat_id": repeat,
                        "goal_invocation_limit_seconds": limit,
                        "goal_delta_vs_075": int(other["goal_reached"]) - int(baseline["goal_reached"]),
                        "accepted_seed_delta_vs_075": (
                            other["accepted_seed_count"] - baseline["accepted_seed_count"]),
                        "state_delta_vs_075": other["state_new_count"] - baseline["state_new_count"],
                        "coverage_delta_vs_075": (
                            other["coverage_new_count"] - baseline["coverage_new_count"]),
                    })
    return {"total_budget": budget_pairs, "goal_invocation_limit": goal_pairs}


def _svg_bars(path: Path, title: str, rows: list[dict], label, value, maximum: int) -> None:
    width = 1100
    row_height = 24
    top = 55
    height = top + row_height * len(rows) + 35
    bar_left = 360
    bar_width = width - bar_left - 70
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="20" y="30" font-family="sans-serif" font-size="18" font-weight="bold">{html.escape(title)}</text>',
    ]
    for index, row in enumerate(rows):
        y = top + index * row_height
        amount = value(row)
        length = 0 if maximum == 0 else bar_width * amount / maximum
        lines.extend([
            f'<text x="20" y="{y + 15}" font-family="monospace" font-size="12">{html.escape(label(row))}</text>',
            f'<rect x="{bar_left}" y="{y + 3}" width="{length:.2f}" height="15" fill="#3366cc"/>',
            f'<text x="{bar_left + length + 6:.2f}" y="{y + 15}" font-family="sans-serif" font-size="12">{amount}/{maximum}</text>',
        ])
    lines.append("</svg>\n")
    path.write_text("\n".join(lines))


def _cost_rows(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["profile_id"]].append(row)
    result = []
    for profile, values in sorted(grouped.items()):
        stages = sorted({name for row in values for name in row["stage_cost_seconds"]})
        result.append({
            "profile_id": profile,
            "mean_charged_seconds": _mean([row["charged_end_seconds"] for row in values]),
            "median_charged_seconds": statistics.median(
                [row["charged_end_seconds"] for row in values]),
            "mean_stage_seconds": {
                stage: _mean([row["stage_cost_seconds"].get(stage, 0.0) for row in values])
                for stage in stages
            },
        })
    return result


def _markdown(summary: dict) -> str:
    lines = [
        "# Stage 3 Study Results", "",
        f"Independent audit: **{summary['audit_status']}**. "
        f"The study contains {summary['slot_count']} distinct slots in "
        f"{summary['common_block_count']} shared-warmup blocks.", "",
        "These are descriptive results for four repository-owned teaching fixtures. "
        "Shared warmups and Medusa's disclosed clock-seeded chooser randomness mean the slots "
        "are not independent samples. Goal reachability is not a claim about a production vulnerability.", "",
        "## Per-fixture profile results", "",
        "| Fixture | Profile | Goal hits | Runs | Mean observed end (s) | Mean charged end (s) | Reasons |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in summary["profiles"]:
        reasons = ", ".join(f"{key}: {value}" for key, value in row["miss_or_hit_reasons"].items())
        lines.append(
            f"| {row['fixture_id']} | {row['profile_id']} | {row['goal_hits']} | {row['runs']} | "
            f"{row['mean_observation_end_seconds']:.3f} | {row['mean_charged_end_seconds']:.3f} | {reasons} |"
        )
    lines.extend([
        "", "## Interpretation boundary", "",
        "The 8-second and 32-second settings support a paired two-level comparison only. "
        "The 0.50, 0.75, and 1.50 second values are whole Halmos goal-invocation process limits, "
        "not isolated SMT CPU time. Auxiliary concrete confirmations and goals observed by the "
        "subsequent native campaign are reported separately.", "",
        "WorkflowGate rows retain no-prefix, timeout, no-candidate, and continuation-miss reasons "
        "separately. A negative row is not automatically attributed to symbolic solving cost.", "",
    ])
    return "\n".join(lines)


def build_study_report(root: Path, output: Path | None = None) -> dict:
    root = Path(root).resolve()
    output = Path(output or root / "derived").resolve()
    output.mkdir(parents=True, exist_ok=True)
    audit = audit_study(root, output / "audit.json")
    config = json.loads((root / "frozen-config.json").read_text())
    profiles = _profile_summary(audit["rows"])
    summary = {
        "schema_version": 1,
        "study_id": audit["study_id"],
        "audit_status": audit["status"],
        "slot_count": audit["slot_count"],
        "common_block_count": audit["common_block_count"],
        "goal_hit_count": audit["goal_hit_count"],
        "complete_sequence_count": audit["complete_sequence_count"],
        "mutation_event_count": audit["mutation_event_count"],
        "profiles": profiles,
        "paired_comparisons": _paired(audit["rows"], config),
        "costs": _cost_rows(audit["rows"]),
        "workflow_gate": [row for row in audit["rows"] if row["fixture_id"] == "workflow_gate"],
    }
    canonical = json.dumps(summary, sort_keys=True, separators=(",", ":")).encode()
    summary["content_sha256"] = hashlib.sha256(canonical).hexdigest()
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    (output / "summary.md").write_text(_markdown(summary))
    write_observations_csv(audit, output / "observations.csv")
    main = [row for row in profiles if row["profile_id"].startswith(("b08-", "b32-"))
            and "q050" not in row["profile_id"] and "q150" not in row["profile_id"]]
    goal = [row for row in profiles if row["profile_id"].startswith("b32-symbolic-q")]
    if main:
        _svg_bars(
            output / "total-budget-goal-hits.svg", "Goal hits by total-budget profile",
            main, lambda row: f"{row['fixture_id']} / {row['profile_id']}",
            lambda row: row["goal_hits"], max(row["runs"] for row in main),
        )
    if goal:
        _svg_bars(
            output / "goal-limit-hits.svg", "Goal hits by Halmos goal-invocation limit",
            goal, lambda row: f"{row['fixture_id']} / {row['profile_id']}",
            lambda row: row["goal_hits"], max(row["runs"] for row in goal),
        )
    cost_chart = [{"profile_id": row["profile_id"], "goal_hits": round(row["mean_charged_seconds"], 3)}
                  for row in summary["costs"]]
    if cost_chart:
        _svg_bars(
            output / "charged-cost.svg", "Mean charged wall time by profile",
            cost_chart, lambda row: row["profile_id"], lambda row: row["goal_hits"],
            max(1, int(max(row["goal_hits"] for row in cost_chart) + 1)),
        )
    return summary
