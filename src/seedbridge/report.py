from pathlib import Path

from .io import read_json, write_json


def save_report(directory: Path, report: dict) -> Path:
    write_json(directory / "report.json", report)
    lines = ["# Stage 1 run report", "", f"Fixture: `{report['fixture_id']}`",
             f"Status: **{report['status']}**", "",
             "This is a reachability integration result for a local teaching fixture.",
             "It is not a vulnerability finding or a performance comparison.", ""]
    if report.get("error"):
        lines.extend([f"Failure: {report['error']}", ""])
    lines.extend(["| Check | Result |", "| --- | --- |",
                  f"| Selected prefixes | {len(report.get('prefixes', []))} |",
                  f"| Native round-trip | {report.get('roundtrip', {}).get('status', 'not_run')} |",
                  f"| Observer control | {report.get('observer_control', {}).get('status', 'not_run')} |",
                  f"| Confirmed candidates | {report.get('confirmed_count', 0)} |", "",
                  "| Candidate | Prefix check | Solver | Concrete replay | Novelty | Native admission |",
                  "| --- | --- | --- | --- | --- | --- |"])
    for i, attempt in enumerate(report.get("attempts", [])):
        lines.append(f"| {i} | {attempt.get('prefix_check', {}).get('status', 'not_run')} | "
                     f"{attempt.get('solve', {}).get('status', 'not_run')} | "
                     f"{attempt.get('replay', {}).get('status', 'not_run')} | "
                     f"{attempt.get('novelty', {}).get('status', 'not_run')} | "
                     f"{attempt.get('admission', {}).get('status', 'not_run')} |")
    stages = report.get("stage_elapsed_seconds", {})
    if stages:
        lines.extend(["", "| Stage | Elapsed seconds |", "| --- | ---: |"])
        for name, elapsed in stages.items():
            lines.append(f"| `{name}` | {elapsed:.6f} |")
    lines.extend(["", "Full provenance, versions, paths and process logs: `report.json`.", ""])
    path = directory / "report.md"
    path.write_text("\n".join(lines))
    return path


def regenerate(path: Path) -> Path:
    directory = path if path.is_dir() else path.parent
    return save_report(directory, read_json(directory / "report.json"))
