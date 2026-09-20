#!/usr/bin/env python3
"""Audit the Stage 3 timing, cache, compact-format, and storage smoke evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
sys.path.insert(0, str(ROOT / "src"))

from seedbridge.compact import read_compact_events  # noqa: E402
from seedbridge.io import file_hash, read_json, write_json  # noqa: E402
from seedbridge.study import load_study_spec  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sanitize(value: object) -> object:
    """Remove machine-specific repository and home-directory prefixes."""
    if isinstance(value, str):
        return value.replace(f"{ROOT}/", "").replace(str(HOME), "~")
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize(item) for key, item in value.items()}
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", type=Path, default=ROOT / "runs/stage3-protocol-smoke-06")
    parser.add_argument("--timing", type=Path, default=ROOT / "runs/stage3-timing-smoke-02")
    parser.add_argument("--sequence-limit", type=Path, default=ROOT / "runs/stage3-sequence-limit-smoke-01")
    parser.add_argument("--conversion", type=Path, default=ROOT / "runs/stage3-stage2-compact-01")
    parser.add_argument("--native-hash", type=Path, default=ROOT / "runs/stage3-p3-native-hash-smoke-04")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/stage3/protocol-audit.json")
    args = parser.parse_args()

    smoke = args.smoke.resolve()
    manifest_path = smoke / "manifest.json"
    manifest = read_json(manifest_path)
    require(manifest["status"] == "complete", "protocol smoke is incomplete")
    require(manifest["result_count"] == manifest["evaluation_valid_count"] == 3,
            "protocol smoke does not contain three valid arms")
    campaigns = []
    cache_sources = set()
    corpus_sources = set()
    compact_bytes = 0
    compact_sequences = 0
    for path in sorted(smoke.glob("blocks/*/repeat-*/profiles/*/campaign.json")):
        record = read_json(path)
        require(record["evaluation_valid"] is True, f"invalid smoke profile: {path}")
        require(record["outcomes"]["stop_reason"] == "time_limit", "smoke did not stop by time")
        require(record["outcomes"]["after_deadline_sequences"] == 0,
                "smoke contains metric events after its deadline")
        timing = record["online_timing"]
        require(
            timing["search_started"] <= timing["metric_observation_end"]
            <= timing["search_stopped"] <= timing["event_stream_finished"]
            <= timing["evidence_flush_finished"] <= timing["charged_end"],
            "smoke timing boundaries are not monotonic",
        )
        cache_sources.add(record["artifacts"]["cache_copy"]["source_content_sha256"])
        corpus_sources.add(record["artifacts"]["corpus_copy"]["source_content_sha256"])
        event_path = Path(record["artifacts"]["event_stream"])
        report = read_json(Path(record["artifacts"]["native_report"]))
        decoded = read_compact_events(event_path, report["compact_events"])
        require(len(decoded["sequences"]) == record["outcomes"]["completed_sequences"],
                "decoded smoke sequence count differs")
        compact_bytes += event_path.stat().st_size
        compact_sequences += len(decoded["sequences"])
        campaigns.append({
            "profile_id": record["spec"]["profile_id"],
            "goal_reached": record["goal_reached"],
            "completed_sequences": len(decoded["sequences"]),
            "compact_bytes": event_path.stat().st_size,
            "timing": timing,
            "cache_start_sha256": record["artifacts"]["cache_copy"]["source_content_sha256"],
            "corpus_start_sha256": record["artifacts"]["corpus_copy"]["source_content_sha256"],
        })
    require(len(cache_sources) == len(corpus_sources) == 1,
            "smoke arms did not share identical cache and corpus starts")

    timing_audit = read_json(args.timing / "audit.json")
    sequence_limit = read_json(args.sequence_limit / "audit.json")
    conversion = read_json(args.conversion / "conversion-audit.json")
    native_hash = read_json(args.native_hash / "audit.json")
    require(timing_audit["status"] == "passed" and all(timing_audit["checks"].values()),
            "controlled flush-delay check failed")
    require(sequence_limit["status"] == "passed"
            and sequence_limit["stop_reason"] == "sequence_limit",
            "sequence-limit classification check failed")
    require(conversion["status"] == "passed" and conversion["campaign_count"] == 60
            and all(row["metrics_equal"] for row in conversion["campaigns"]),
            "Stage 2 compact conversion did not reproduce all metrics")
    require(native_hash["status"] == "passed"
            and all(row["match"] for row in native_hash["samples"]),
            "native payload hash spot-check failed")

    smoke_files = [path for path in smoke.rglob("*") if path.is_file()]
    smoke_bytes = sum(path.stat().st_size for path in smoke_files)
    formal = load_study_spec(ROOT / "configs/stage3-study.json")
    conservative_formal_bytes = smoke_bytes * ((formal.plan()["distinct_slot_count"] + 2) // 3) * 4
    require(conservative_formal_bytes < formal.storage_max_study_bytes,
            "conservative smoke storage projection exceeds the configured study cap")
    result = {
        "schema_version": 1,
        "status": "passed",
        "inputs": {
            "smoke_manifest": {"path": str(manifest_path), "sha256": file_hash(manifest_path)},
            "timing_audit": {"path": str(args.timing / "audit.json"),
                             "sha256": file_hash(args.timing / "audit.json")},
            "sequence_limit_audit": {"path": str(args.sequence_limit / "audit.json"),
                                     "sha256": file_hash(args.sequence_limit / "audit.json")},
            "conversion_audit": {"path": str(args.conversion / "conversion-audit.json"),
                                 "sha256": file_hash(args.conversion / "conversion-audit.json")},
            "native_hash_audit": {"path": str(args.native_hash / "audit.json"),
                                  "sha256": file_hash(args.native_hash / "audit.json")},
        },
        "study_plan": formal.plan(),
        "smoke": {
            "valid_profiles": len(campaigns),
            "campaigns": campaigns,
            "compact_sequences": compact_sequences,
            "compact_event_bytes": compact_bytes,
            "total_file_count": len(smoke_files),
            "total_bytes": smoke_bytes,
            "common_cache_sha256": next(iter(cache_sources)),
            "common_corpus_sha256": next(iter(corpus_sources)),
        },
        "controlled_flush_delay": timing_audit,
        "sequence_limit": sequence_limit,
        "stage2_conversion": {
            key: conversion[key] for key in (
                "campaign_count", "sequence_count", "lineage_counts",
                "source_report_bytes", "compact_event_bytes", "elapsed_seconds",
            )
        },
        "native_hash_spot_check": native_hash,
        "storage": {
            "preflight": manifest["storage_preflight"],
            "configured_maximum_study_bytes": formal.storage_max_study_bytes,
            "conservative_projection_bytes": conservative_formal_bytes,
            "projection_method": "entire three-profile smoke bytes scaled to 320 profiles and multiplied by four",
        },
    }
    write_json(args.output, sanitize(result))
    print(json.dumps({
        "status": result["status"],
        "smoke_profiles": len(campaigns),
        "stage2_campaigns": conversion["campaign_count"],
        "stage2_sequences": conversion["sequence_count"],
        "conservative_projection_bytes": conservative_formal_bytes,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
