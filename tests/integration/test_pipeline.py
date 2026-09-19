"""Opt-in native integration, including exact repeated-run provenance checks."""

import os
from pathlib import Path
import subprocess

import pytest

from seedbridge.config import ROOT, RunConfig
from seedbridge.doctor import tool_environment
from seedbridge.io import read_json
from seedbridge.pipeline import run_pipeline

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("SEEDBRIDGE_INTEGRATION") != "1", reason="set SEEDBRIDGE_INTEGRATION=1 to run native tools")]


@pytest.mark.parametrize("fixture", ["phase_counter", "bounded_ledger"])
def test_native_pipeline(fixture):
    report, directory = run_pipeline(RunConfig(fixture, warmup_tests=40, max_prefixes=2))
    assert report["status"] == "stage1_confirmed", (directory, report.get("error"))
    assert report["confirmed_count"] == 1
    assert report["roundtrip"]["status"] == "passed"
    assert report["observer_control"]["status"] == "passed"
    assert set(report["stage_elapsed_seconds"]) == {
        "s0_environment_build", "s1_scenario_config", "s2_native_warmup",
        "s2_roundtrip_observer_control", "s3_prefix_selection",
        "s3_harness_prefix_replay", "s4_halmos_solve", "s5_replay_reinsert", "s6_report",
    }
    scenario = read_json(directory / "scenario.json")
    assert scenario["scenario"]["fixture_id"] == fixture
    assert scenario["scenario"]["execution"] == {
        "prefix_steps": {"minimum": 1, "maximum": 3},
        "worker_count": 1, "call_value": "0", "reinsertion_rounds": 1,
    }
    successful = [case for case in report["attempts"] if case.get("admission", {}).get("status") == "admitted_for_mutation"]
    assert len(successful) == 1
    case = successful[0]
    assert case["prefix_check"]["status"] == "prefix_confirmed"
    assert case["solve"]["status"] == "candidate"
    assert case["replay"]["status"] == "reachable_confirmed"
    assert case["novelty"]["status"] == "new_sequence"
    assert Path(case["novelty"]["evidence_path"]).is_file()
    assert case["admission"]["replayed_by_medusa"] is True
    assert case["admission"]["complete_sequence"] is True
    assert case["admission"]["goal_before_suffix"] is False
    assert case["admission"]["goal_after_suffix"] is True
    assert case["admission"]["final_state"][-1] is True
    assert Path(case["candidate"]["model_file"]).is_file()
    assert Path(case["admission"]["native_path"]).is_file()


def test_native_corpus_roundtrip_observer_and_determinism():
    result = subprocess.run(["go", "test", "-mod=readonly", "-count=1", "-v",
                             "-run", "TestNativeRestartObserverAndDeterminism", "./..."],
                            cwd=ROOT / "adapters/medusa", env=tool_environment(),
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "--- PASS: TestNativeRestartObserverAndDeterminism" in result.stdout
