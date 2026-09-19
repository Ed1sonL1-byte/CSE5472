from copy import deepcopy

import pytest

from seedbridge.build import assert_medusa_build, assert_same_target
from seedbridge.pipeline import summarize_unsuccessful
from seedbridge.pipeline import run_pipeline
from seedbridge.config import RunConfig
from seedbridge.process import EvidenceMismatchError, ToolExecutionError


def test_changed_compilation_is_rejected_between_stages():
    baseline = {key: key for key in ["source_sha256", "abi_sha256", "init_sha256", "runtime_sha256"]}
    for field in baseline:
        changed = {**baseline, field: "different"}
        with pytest.raises(ValueError, match="mismatch"):
            assert_same_target(baseline, changed)
    native = {"build": {"medusa_build_matches_forge": True, "source_sha256": "source_sha256",
                        "init_bytecode_sha256": "init_sha256", "runtime_bytecode_sha256": "runtime_sha256"}}
    assert_medusa_build(baseline, native)
    for field in ("source_sha256", "init_bytecode_sha256", "runtime_bytecode_sha256"):
        changed = deepcopy(native)
        changed["build"][field] = "different"
        with pytest.raises(ValueError):
            assert_medusa_build(baseline, changed)


@pytest.mark.parametrize("failure,expected", [("timeout", "timeout"), ("tool_error", "tool_error"),
                                            ("decode_error", "tool_error"), ("prefix_incomplete", "inconclusive"),
                                            ("invalid_model", "validation_failed"),
                                            ("no_witness_within_bounds", "no_witness_within_bounds")])
def test_tool_failures_are_not_reported_as_a_normal_search(failure, expected):
    assert summarize_unsuccessful([{"prefix_check": {"status": "prefix_confirmed"},
                                    "solve": {"status": failure}}]) == expected


@pytest.mark.parametrize("status", ["timeout", "tool_error"])
def test_pipeline_preserves_native_tool_failure_classification(tmp_path, monkeypatch, status):
    monkeypatch.setattr("seedbridge.pipeline._execute", lambda *args: (_ for _ in ()).throw(
        ToolExecutionError("native failure", status=status)))
    report, _ = run_pipeline(RunConfig("phase_counter"), tmp_path / status)
    assert report["status"] == status


@pytest.mark.parametrize("status", ["state_mismatch", "observer_mismatch"])
def test_pipeline_does_not_report_evidence_mismatch_as_tool_failure(tmp_path, monkeypatch, status):
    monkeypatch.setattr("seedbridge.pipeline._execute", lambda *args: (_ for _ in ()).throw(
        EvidenceMismatchError("evidence differs", status=status)))
    report, _ = run_pipeline(RunConfig("phase_counter"), tmp_path / status)
    assert report["status"] == status
