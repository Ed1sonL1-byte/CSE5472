"""Lossless Stage 2 campaign conversion into the Stage 3 compact event format."""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import time

from .compact import read_compact_events
from .io import file_hash, read_json, write_json
from .metrics import segmented_metrics
from .process import EvidenceMismatchError


def _error(message: str) -> EvidenceMismatchError:
    return EvidenceMismatchError(message, status="evidence_error")


def _identity(steps: list[dict]) -> str:
    projection = [
        {key: step[key] for key in ("from", "to", "value", "calldata")}
        for step in steps
    ]
    encoded = json.dumps(projection, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _event(sequence: dict, lineage: dict, prefixes: list[dict]) -> dict:
    native_path = Path(sequence["native_path"])
    if not native_path.is_file():
        raise _error(f"legacy native payload is missing: {native_path}")
    payload = native_path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != sequence.get("native_digest"):
        raise _error(f"legacy native payload checksum differs: {native_path}")
    references = [
        {
            "medusa_hash": prefix["medusa_hash"],
            "identity_hash": _identity(prefix["steps"]),
            "step_count": len(prefix["steps"]),
        }
        for prefix in prefixes
    ]
    if ([reference["step_count"] for reference in references]
            != list(range(1, len(sequence["steps"]) + 1))):
        raise _error(f"legacy sequence {sequence['sequence_index']} has incomplete prefix evidence")
    if (references[-1]["medusa_hash"] != lineage.get("output_hash")
            or references[-1]["identity_hash"] != lineage.get("output_identity_hash")):
        raise _error(f"legacy sequence {sequence['sequence_index']} differs from lineage")
    converted = dict(sequence)
    converted["native_path"] = f"compact-events://sequence/{sequence['sequence_index']}"
    return {
        "schema_version": 2,
        "record_type": "sequence",
        "sequence": converted,
        "lineage": lineage,
        "prefix_references": references,
        "native_payload_base64": base64.b64encode(payload).decode(),
    }


def convert_legacy_campaign(source: Path, destination: Path) -> dict:
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("legacy compact destination must be new")
    report = read_json(source)
    if (report.get("schema_version") != 2 or report.get("lineage_enabled") is not True
            or report.get("completed_sequences") != len(report.get("lineage", []))):
        raise _error("legacy campaign does not contain complete Stage 2 lineage")
    grouped: dict[int, list[dict]] = {}
    complete = []
    for sequence in report.get("sequences", []):
        grouped.setdefault(sequence["sequence_index"], []).append(sequence)
        if sequence.get("is_complete_sequence") is True:
            complete.append(sequence)
    lineage = {event["sequence_index"]: event for event in report["lineage"]}
    if len(lineage) != len(report["lineage"]) or len(complete) != report["completed_sequences"]:
        raise _error("legacy campaign has duplicate or missing completed sequence identities")

    destination.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with destination.open("xb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=6, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8") as output:
                for sequence in complete:
                    index = sequence["sequence_index"]
                    prefixes = sorted(grouped[index], key=lambda item: len(item["steps"]))
                    value = _event(sequence, lineage[index], prefixes)
                    output.write(json.dumps(value, separators=(",", ":")) + "\n")
                output.write(json.dumps({
                    "schema_version": 2,
                    "record_type": "eof",
                    "sequence_count": len(complete),
                    "partial_count": 0,
                }, separators=(",", ":")) + "\n")
        raw.flush()
        os.fsync(raw.fileno())
    metadata = {
        "schema_version": 2,
        "path": str(destination),
        "encoding": "gzip-jsonl",
        "sequence_records": len(complete),
        "partial_records": 0,
        "eof_record": True,
        "compressed_bytes": destination.stat().st_size,
        "sha256": file_hash(destination),
    }
    decoded = read_compact_events(destination, metadata)
    if len(decoded["sequences"]) != report["completed_sequences"]:
        raise _error("converted campaign did not decode to the legacy sequence count")
    return {
        "metadata": metadata,
        "decoded": decoded,
        "elapsed_seconds": time.monotonic() - started,
        "source_sha256": file_hash(source),
        "source_bytes": source.stat().st_size,
    }


def convert_stage2_study(source: Path, destination: Path) -> dict:
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("Stage 2 conversion destination must be new")
    reports = sorted(source.glob("blocks/*/repeat-*/arms/*/native/campaign.json"))
    if len(reports) != 60:
        raise ValueError(f"Stage 2 source must contain 60 native campaign reports, found {len(reports)}")
    destination.mkdir(parents=True)
    started = time.monotonic()
    rows = []
    for report_path in reports:
        fixture = report_path.parents[4].name
        repeat = report_path.parents[3].name
        arm = report_path.parents[1].name
        target = destination / "blocks" / fixture / repeat / arm / "events.jsonl.gz"
        converted = convert_legacy_campaign(report_path, target)
        legacy = read_json(report_path)
        campaign = {
            **legacy,
            "sequences": converted["decoded"]["sequences"],
            "lineage": converted["decoded"]["lineage"],
            "completed_sequences": len(converted["decoded"]["sequences"]),
        }
        warmup_path = report_path.parents[3] / "warmup/warmup/campaign.json"
        expected_path = report_path.parents[1] / "metrics.json"
        recomputed = segmented_metrics(fixture, read_json(warmup_path), campaign)
        expected = read_json(expected_path)
        if recomputed != expected:
            raise _error(f"converted Stage 2 metrics differ for {fixture}/{repeat}/{arm}")
        counts = {
            kind: sum(event["kind"] == kind for event in converted["decoded"]["lineage"])
            for kind in ("startup_replay", "new_sequence", "mutation")
        }
        if (counts["startup_replay"] != legacy["startup_replays"]
                or counts["new_sequence"] != legacy["new_sequences"]
                or counts["mutation"] != legacy["mutation_sequences"]):
            raise _error(f"converted Stage 2 lineage counts differ for {fixture}/{repeat}/{arm}")
        summary_path = target.with_name("conversion.json")
        row = {
            "fixture_id": fixture,
            "repeat": repeat,
            "arm": arm,
            "source_report": str(report_path),
            "source_report_sha256": converted["source_sha256"],
            "source_report_bytes": converted["source_bytes"],
            "event_stream": str(target),
            "event_stream_sha256": converted["metadata"]["sha256"],
            "event_stream_bytes": converted["metadata"]["compressed_bytes"],
            "completed_sequences": campaign["completed_sequences"],
            "lineage_counts": counts,
            "metrics_equal": True,
            "conversion_elapsed_seconds": converted["elapsed_seconds"],
        }
        write_json(summary_path, row)
        rows.append(row)
    result = {
        "schema_version": 1,
        "status": "passed",
        "source": str(source),
        "campaign_count": len(rows),
        "sequence_count": sum(row["completed_sequences"] for row in rows),
        "lineage_counts": {
            kind: sum(row["lineage_counts"][kind] for row in rows)
            for kind in ("startup_replay", "new_sequence", "mutation")
        },
        "source_report_bytes": sum(row["source_report_bytes"] for row in rows),
        "compact_event_bytes": sum(row["event_stream_bytes"] for row in rows),
        "elapsed_seconds": time.monotonic() - started,
        "campaigns": rows,
    }
    write_json(destination / "conversion-audit.json", result)
    return result
