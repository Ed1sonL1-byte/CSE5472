import base64
import gzip
import hashlib
import json

import pytest

from seedbridge.compact import read_compact_events
from seedbridge.legacy_compact import convert_legacy_campaign, _identity
from seedbridge.process import EvidenceMismatchError


def sequence(index=1, complete=True):
    native = json.dumps([{"Call": {"data": "0x1234"}}], indent=2).encode() + b"\n"
    value = {
        "sequence_index": index,
        "native_digest": hashlib.sha256(native).hexdigest(),
        "is_complete_sequence": complete,
        "steps": [{"status": "success"}],
    }
    lineage = {
        "sequence_index": index, "generation_id": index, "kind": "new_sequence",
        "output_hash": f"hash-{index}", "output_identity_hash": f"identity-{index}",
        "parent_hashes": [],
    }
    return native, value, lineage


def write_stream(path, events):
    with gzip.open(path, "wt", encoding="utf-8") as output:
        for event in events:
            output.write(json.dumps(event) + "\n")
    return {
        "schema_version": 2,
        "encoding": "gzip-jsonl",
        "eof_record": True,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "compressed_bytes": path.stat().st_size,
        "sequence_records": sum(event["record_type"] == "sequence" for event in events),
        "partial_records": sum(event["record_type"] == "partial" for event in events),
    }


def event(kind="sequence", index=1):
    native, value, lineage = sequence(index, complete=kind == "sequence")
    return {
        "schema_version": 2,
        "record_type": kind,
        "sequence": value,
        "lineage": lineage if kind == "sequence" else None,
        "prefix_references": [{
            "medusa_hash": f"hash-{index}",
            "identity_hash": f"identity-{index}",
            "step_count": 1,
        }],
        "native_payload_base64": base64.b64encode(native).decode(),
    }


def test_compact_stream_roundtrip_preserves_complete_and_partial_records(tmp_path):
    events = [event(index=1), event("partial", 2), {
        "schema_version": 2, "record_type": "eof", "sequence_count": 1, "partial_count": 1,
    }]
    path = tmp_path / "events.jsonl.gz"
    decoded = read_compact_events(path, write_stream(path, events))
    assert [row["sequence_index"] for row in decoded["sequences"]] == [1]
    assert [row["sequence_index"] for row in decoded["partial_sequences"]] == [2]
    assert decoded["lineage"][0]["generation_id"] == 1
    assert decoded["sequences"][0]["native_payload_verified"] is True


@pytest.mark.parametrize(
    "failure",
    ["checksum", "missing_eof", "duplicate", "bad_payload", "bad_dictionary", "absent_parent"],
)
def test_compact_stream_rejects_corruption_and_truncation(tmp_path, failure):
    events = [event(index=1), {
        "schema_version": 2, "record_type": "eof", "sequence_count": 1, "partial_count": 0,
    }]
    if failure == "missing_eof":
        events.pop()
    elif failure == "duplicate":
        events.insert(1, event(index=1))
        events[-1]["sequence_count"] = 2
    elif failure == "bad_payload":
        events[0]["native_payload_base64"] = "not-base64"
    elif failure == "bad_dictionary":
        events[0]["prefix_references"][0]["step_count"] = 2
    elif failure == "absent_parent":
        child = event(index=2)
        child["lineage"]["kind"] = "mutation"
        child["lineage"]["parent_hashes"] = ["missing-parent"]
        events.insert(1, child)
        events[-1]["sequence_count"] = 2
    path = tmp_path / "events.jsonl.gz"
    metadata = write_stream(path, events)
    if failure == "checksum":
        metadata["sha256"] = "0" * 64
    with pytest.raises(EvidenceMismatchError):
        read_compact_events(path, metadata)


def test_stage2_converter_keeps_each_complete_sequence_once(tmp_path):
    payload = tmp_path / "native.json"
    payload.write_text('[{"Call":{"data":"0x1234"}}]\n')
    steps = [{
        "from": "0x10000", "to": "0x20000", "value": "0", "calldata": "0x1234",
        "status": "success",
    }]
    sequence = {
        "sequence_index": 1,
        "native_path": str(payload),
        "native_digest": hashlib.sha256(payload.read_bytes()).hexdigest(),
        "medusa_hash": "hash-1",
        "steps": steps,
        "is_complete_sequence": True,
    }
    source = tmp_path / "campaign.json"
    source.write_text(json.dumps({
        "schema_version": 2,
        "lineage_enabled": True,
        "completed_sequences": 1,
        "sequences": [sequence],
        "lineage": [{
            "sequence_index": 1,
            "kind": "new_sequence",
            "parent_hashes": [],
            "output_hash": "hash-1",
            "output_identity_hash": _identity(steps),
        }],
    }))
    result = convert_legacy_campaign(source, tmp_path / "converted.jsonl.gz")
    assert result["metadata"]["sequence_records"] == 1
    assert result["decoded"]["sequences"][0]["native_payload_verified"] is True
