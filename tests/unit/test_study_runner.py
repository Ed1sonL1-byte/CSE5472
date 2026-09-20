from pathlib import Path

import pytest

from seedbridge.cache import copy_isolated_workspace, storage_preflight, tree_manifest
from seedbridge.process import EvidenceMismatchError
from seedbridge.study_runner import project_native_to_budget
from seedbridge.study_runner import run_study_slot
from seedbridge.study import load_study_spec
from seedbridge.config import ROOT


def native_record():
    return {
        "completion_timing": {
            "search_started": 0.5,
            "search_stopped": 4.0,
            "last_observed_event": 3.5,
            "event_stream_finished": 4.2,
            "evidence_flush_finished": 4.3,
        },
        "completed_sequences": 2,
        "sequences": [
            {"sequence_index": 1, "is_complete_sequence": True},
            {"sequence_index": 2, "is_complete_sequence": True},
        ],
        "lineage": [
            {"sequence_index": 1, "completed_offset_seconds": 1.0},
            {"sequence_index": 2, "completed_offset_seconds": 3.0},
        ],
    }


def test_native_projection_retains_late_evidence_but_excludes_it_from_metrics():
    native = native_record()
    projected, timing = project_native_to_budget(
        native, native_stage_start=2.0, budget_deadline=5.0)
    assert projected["completed_sequences"] == 1
    assert [row["sequence_index"] for row in projected["lineage"]] == [1]
    assert timing["after_deadline_sequence_indices"] == [2]
    assert timing["metric_observation_end"] == pytest.approx(3.5)
    assert native["sequences"][1]["after_deadline"] is True


def test_native_projection_rejects_lineage_without_sequence():
    native = native_record()
    native["sequences"].pop()
    with pytest.raises(EvidenceMismatchError, match="absent sequence") as raised:
        project_native_to_budget(native, native_stage_start=0, budget_deadline=10)
    assert raised.value.status == "evidence_error"


def test_isolated_workspace_copy_starts_byte_identical_and_then_diverges(tmp_path):
    source = tmp_path / "source"
    (source / "cache").mkdir(parents=True)
    (source / "cache" / "entry.json").write_text("one")
    before = tree_manifest(source)
    copied = copy_isolated_workspace(source, tmp_path / "copy")
    assert copied["source_content_sha256"] == before["content_sha256"]
    assert copied["destination_content_sha256"] == before["content_sha256"]
    (tmp_path / "copy/cache/entry.json").write_text("two")
    assert tree_manifest(tmp_path / "copy")["content_sha256"] != before["content_sha256"]
    assert (source / "cache/entry.json").read_text() == "one"


def test_storage_preflight_fails_closed_when_configured_study_exceeds_disk(tmp_path):
    result = storage_preflight(
        Path(tmp_path) / "new-study", minimum_free_bytes=1,
        maximum_study_bytes=1 << 100,
    )
    assert result["ok"] is False
    assert result["reason"]


def _slot_common(tmp_path):
    cache = tmp_path / "common-cache"
    corpus = tmp_path / "common-corpus"
    cache.mkdir()
    corpus.mkdir()
    (cache / "source").write_text("fixed")
    (corpus / "seed").write_text("fixed")
    return {
        "elapsed_seconds": 0.1,
        "cache_base_path": str(cache),
        "cache_manifest": tree_manifest(cache),
        "corpus_path": str(corpus),
        "corpus_manifest": tree_manifest(corpus),
        "prefixes": [],
        "warmup": {"sequences": []},
        "warmup_goal_reached": False,
        "within_common_limit": True,
        "warmup_path": str(tmp_path / "common/warmup/campaign.json"),
        "toolchain": {"tools": {}},
        "build": {},
    }


def _native_result(stop_reason="time_limit"):
    return {
        "stop_reason": stop_reason,
        "completed_sequences": 1,
        "lineage": [{
            "sequence_index": 1, "kind": "new_sequence", "parents_resolved": False,
            "completed_offset_seconds": 0.5,
        }],
        "sequences": [{"sequence_index": 1, "is_complete_sequence": True}],
        "completion_timing": {
            "search_started": 0.1, "search_stopped": 1.0,
            "last_observed_event": 0.6, "event_stream_finished": 1.1,
            "evidence_flush_finished": 1.2,
        },
        "partial_sequences": [],
        "startup_replays": 0,
        "new_sequences": 1,
        "mutation_sequences": 0,
        "status": "timeout" if stop_reason == "time_limit" else "complete",
        "native_timing_seconds": {},
        "output_path": "/tmp/native-campaign.json",
        "compact_events": {"path": "/tmp/events.jsonl.gz"},
        "completion_path": "/tmp/completion.json",
    }


def test_no_prefix_is_valid_negative_and_still_runs_native_continuation(tmp_path, monkeypatch):
    spec = load_study_spec(ROOT / "configs/stage3-smoke.json")
    slot = next(slot for slot in spec.slots() if slot.arm == "symbolic_augment")
    monkeypatch.setattr("seedbridge.study_runner.campaign", lambda *_args, **_kwargs: _native_result())
    monkeypatch.setattr("seedbridge.study_runner.segmented_metrics", lambda *_args, **_kwargs: {
        "goal_reached": {"warmup": False, "import": False, "continuation": False},
        "dimensions": {},
    })
    monkeypatch.setattr("seedbridge.study_runner.save_segmented_metrics", lambda *_args: None)
    record = run_study_slot(spec, slot, _slot_common(tmp_path), tmp_path / "slot")
    assert record["evaluation_valid"] is True
    assert record["augmentation_status"] == "no_eligible_prefix"
    assert record["outcomes"]["completed_sequences"] == 1


def test_sequence_safety_limit_is_evidence_invalid_for_formal_protocol(tmp_path, monkeypatch):
    spec = load_study_spec(ROOT / "configs/stage3-smoke.json")
    slot = next(slot for slot in spec.slots() if slot.arm == "native_resume")
    monkeypatch.setattr(
        "seedbridge.study_runner.campaign",
        lambda *_args, **_kwargs: _native_result("sequence_limit"),
    )
    record = run_study_slot(spec, slot, _slot_common(tmp_path), tmp_path / "slot")
    assert record["evaluation_valid"] is False
    assert record["execution_status"] == "evidence_error"
    assert record["failure"]["classification"] == "evidence_error"
