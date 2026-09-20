"""Fail-closed reader for Stage 3 gzip JSONL native evidence."""

from __future__ import annotations

import base64
import binascii
import gzip
import hashlib
import json
from pathlib import Path

from .io import file_hash
from .process import EvidenceMismatchError


def _error(message: str) -> EvidenceMismatchError:
    return EvidenceMismatchError(message, status="evidence_error")


def read_compact_events(path: Path, metadata: dict) -> dict:
    path = Path(path)
    if not path.is_file():
        raise _error("compact event stream is missing")
    if (metadata.get("schema_version") != 2
            or metadata.get("encoding") != "gzip-jsonl"
            or metadata.get("eof_record") is not True):
        raise _error("compact event metadata is incompatible")
    if metadata.get("sha256") != file_hash(path):
        raise _error("compact event checksum differs from its report")
    if metadata.get("compressed_bytes") != path.stat().st_size:
        raise _error("compact event byte count differs from its report")

    sequences: list[dict] = []
    lineage: list[dict] = []
    partial: list[dict] = []
    seen_indices: set[int] = set()
    known_prefix_hashes: set[str] = set()
    eof: dict | None = None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    raise _error(f"compact event stream has a blank line at {line_number}")
                try:
                    event = json.loads(line)
                except (TypeError, ValueError) as error:
                    raise _error(f"compact event line {line_number} is not JSON: {error}") from error
                if not isinstance(event, dict) or event.get("schema_version") != 2:
                    raise _error(f"compact event line {line_number} has an incompatible schema")
                if eof is not None:
                    raise _error("compact event stream contains records after EOF")
                kind = event.get("record_type")
                if kind == "eof":
                    eof = event
                    continue
                if kind not in {"sequence", "partial"}:
                    raise _error(f"compact event line {line_number} has an unknown record type")
                sequence = event.get("sequence")
                if not isinstance(sequence, dict) or type(sequence.get("sequence_index")) is not int:
                    raise _error(f"compact event line {line_number} has no sequence identity")
                index = sequence["sequence_index"]
                if index in seen_indices:
                    raise _error(f"compact event stream repeats sequence index {index}")
                seen_indices.add(index)
                encoded = event.get("native_payload_base64")
                try:
                    payload = base64.b64decode(encoded, validate=True)
                except (binascii.Error, TypeError, ValueError) as error:
                    raise _error(f"compact event {index} has invalid native payload encoding") from error
                if hashlib.sha256(payload).hexdigest() != sequence.get("native_digest"):
                    raise _error(f"compact event {index} native payload checksum differs")
                try:
                    native = json.loads(payload)
                except (UnicodeDecodeError, ValueError) as error:
                    raise _error(f"compact event {index} native payload is not JSON") from error
                if not isinstance(native, list) or not 1 <= len(native) <= 4:
                    raise _error(f"compact event {index} native payload is not a short call sequence")
                sequence["native_payload_verified"] = True
                references = event.get("prefix_references")
                if (not isinstance(references, list) or not references
                        or any(not isinstance(reference, dict) for reference in references)):
                    raise _error(f"compact event {index} has no prefix reference dictionary")
                reference_hashes = [reference.get("medusa_hash") for reference in references]
                if (any(not isinstance(value, str) or not value for value in reference_hashes)
                        or len(set(reference_hashes)) != len(reference_hashes)):
                    raise _error(f"compact event {index} has invalid prefix references")
                for position, reference in enumerate(references, 1):
                    if (type(reference.get("step_count")) is not int
                            or reference["step_count"] != position
                            or not isinstance(reference.get("identity_hash"), str)):
                        raise _error(f"compact event {index} has an invalid prefix reference")
                if kind == "partial":
                    if sequence.get("is_complete_sequence") is True or event.get("lineage") is not None:
                        raise _error(f"partial compact event {index} claims completion")
                    partial.append(sequence)
                    continue
                if sequence.get("is_complete_sequence") is not True:
                    raise _error(f"compact event {index} is not marked complete")
                event_lineage = event.get("lineage")
                if not isinstance(event_lineage, dict) or event_lineage.get("sequence_index") != index:
                    raise _error(f"compact event {index} has no matching lineage event")
                if (references[-1]["step_count"] != len(sequence.get("steps", []))
                        or references[-1]["medusa_hash"] != event_lineage.get("output_hash")
                        or references[-1]["identity_hash"]
                        != event_lineage.get("output_identity_hash")):
                    raise _error(f"compact event {index} final prefix differs from lineage")
                if event_lineage.get("kind") == "mutation":
                    parent_hashes = event_lineage.get("parent_hashes")
                    if (not isinstance(parent_hashes, list) or not parent_hashes
                            or any(parent not in known_prefix_hashes for parent in parent_hashes)):
                        raise _error(f"compact event {index} refers to an absent mutation parent")
                sequences.append(sequence)
                lineage.append(event_lineage)
                known_prefix_hashes.update(reference_hashes)
    except (OSError, EOFError, gzip.BadGzipFile) as error:
        raise _error(f"compact event stream is truncated or unreadable: {error}") from error

    if eof is None:
        raise _error("compact event stream has no EOF record")
    if eof.get("sequence_count") != len(sequences) or eof.get("partial_count", 0) != len(partial):
        raise _error("compact EOF counts differ from decoded records")
    if metadata.get("sequence_records") != len(sequences):
        raise _error("compact metadata sequence count differs")
    if metadata.get("partial_records") != len(partial):
        raise _error("compact metadata partial count differs")
    return {"sequences": sequences, "lineage": lineage, "partial_sequences": partial}
