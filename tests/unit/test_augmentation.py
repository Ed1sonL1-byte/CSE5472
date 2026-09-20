from pathlib import Path

import pytest

from seedbridge.augmentation import (
    DEFAULT_BOUNDARY_VALUES,
    _checked_result_status,
    _unsuccessful_symbolic_status,
    concrete_values,
    prune_incomplete_native_candidates,
    symbolic_augment,
)
from seedbridge.io import write_json
from seedbridge.process import EvidenceMismatchError, ToolExecutionError


def test_concrete_policy_uses_frozen_boundaries_then_seeded_random_values():
    first = concrete_values(7, len(DEFAULT_BOUNDARY_VALUES) + 3)
    second = concrete_values(7, len(DEFAULT_BOUNDARY_VALUES) + 3)
    other = concrete_values(8, len(DEFAULT_BOUNDARY_VALUES) + 3)
    assert first[:len(DEFAULT_BOUNDARY_VALUES)] == list(DEFAULT_BOUNDARY_VALUES)
    assert first == second
    assert first != other
    assert len(first) == len(set(first))


def test_symbolic_result_classifier_keeps_domain_misses_separate():
    allowed = {"candidate", "no_witness_within_bounds", "timeout", "invalid_model"}
    assert _checked_result_status(
        {"status": "no_witness_within_bounds", "reason": "none"},
        stage="symbolic goal solve", allowed=allowed,
    ) == "no_witness_within_bounds"
    assert _unsuccessful_symbolic_status(["no_witness_within_bounds", "invalid_model"]) == "invalid_model"
    assert _unsuccessful_symbolic_status(["replay_mismatch", "timeout"]) == "timeout"


def test_symbolic_result_classifier_does_not_hide_tool_errors():
    with pytest.raises(ToolExecutionError) as raised:
        _checked_result_status(
            {"status": "tool_error", "reason": "solver process failed"},
            stage="symbolic goal solve", allowed={"candidate"},
        )
    assert raised.value.status == "tool_error"


@pytest.mark.parametrize("status", ["result_mismatch", "decode_error", "unknown"])
def test_symbolic_result_classifier_does_not_hide_bad_results(status):
    with pytest.raises(EvidenceMismatchError) as raised:
        _checked_result_status(
            {"status": status, "reason": "bad result"},
            stage="symbolic goal solve", allowed={"candidate"},
        )
    assert raised.value.status == "result_mismatch"


def test_symbolic_prefix_mismatch_is_state_evidence_failure():
    with pytest.raises(EvidenceMismatchError) as raised:
        _checked_result_status(
            {"status": "prefix_mismatch", "reason": "different state"},
            stage="symbolic prefix check", allowed={"prefix_confirmed"},
        )
    assert raised.value.status == "state_mismatch"


def test_symbolic_augmentation_keeps_fixture_workspace_separate_from_harness(
        tmp_path, monkeypatch):
    fixture_project = tmp_path / "isolated-fixture"
    fixture_project.mkdir()
    codec_projects = []
    validation_projects = []
    baseline = {
        "source_sha256": "source", "abi_sha256": "abi",
        "init_sha256": "init", "runtime_sha256": "runtime",
    }

    def generate(_fixture, _prefix, destination, argument=None):
        project = Path(destination) / "project"
        project.mkdir(parents=True)
        return {"project_path": str(project), "argument": argument}

    def halmos(_project, function, directory, _timeout, _solver, _executable):
        directory.mkdir(parents=True)
        if function == "check_prefix()":
            return {"status": "prefix_confirmed"}
        return {"status": "candidate", "candidates": ["123"],
                "output_path": str(directory / "result.json")}

    def codec(_fixture, operation, _source, output, _timeout, argument=None, project=None):
        codec_projects.append(project)
        if operation == "decode-corpus":
            write_json(output, {"medusa_hash": "0x1", "steps": [{
                "from": "0x10000", "to": "0x20000", "value": "0", "calldata": "0x01",
            }]})
        return {}

    def validate(*_args, project=None, **_kwargs):
        validation_projects.append(project)
        return {"status": "completed", "attempts": [], "accepted": [{"ok": True}]}

    monkeypatch.setattr("seedbridge.augmentation.generate_harness", generate)
    monkeypatch.setattr("seedbridge.augmentation.run_halmos", halmos)
    monkeypatch.setattr("seedbridge.augmentation.build_manifest", lambda *_args, **_kwargs: baseline)
    monkeypatch.setattr("seedbridge.augmentation.concrete_replay",
                        lambda *_args, **_kwargs: {"status": "reachable_confirmed"})
    monkeypatch.setattr("seedbridge.augmentation.codec", codec)
    monkeypatch.setattr("seedbridge.augmentation.validate_native_batch", validate)

    result = symbolic_augment(
        "phase_counter", [{"case_id": "case", "native_path": str(tmp_path / "seed.json")}],
        {"sequences": []}, tmp_path / "augmentation", seed=1, max_candidates=1,
        prefix_query_timeout=1, goal_query_timeout=1, process_timeout=5, total_timeout=5,
        solver="z3", executable="halmos", baseline_build=baseline,
        project=fixture_project,
    )
    assert result["status"] == "completed"
    assert codec_projects == [fixture_project, fixture_project]
    assert validation_projects == [fixture_project]


def test_incomplete_symbolic_codec_output_is_removed_before_batch_validation(tmp_path):
    corpus = tmp_path / "native-validation/corpus/call_sequences"
    corpus.mkdir(parents=True)
    committed = corpus / "p00.json"
    incomplete = corpus / "p01.json"
    committed.write_text("committed")
    incomplete.write_text("timed out before decode")
    removed = prune_incomplete_native_candidates(
        [{"native_path": str(committed)}], corpus)
    assert removed == [str(incomplete)]
    assert committed.read_text() == "committed"
    assert not incomplete.exists()
