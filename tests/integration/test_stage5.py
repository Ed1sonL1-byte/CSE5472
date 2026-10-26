"""Real joint Halmos queries and fresh dual-engine safety confirmation."""

import os
from pathlib import Path

import pytest

from seedbridge.config import RunConfig
from seedbridge.io import read_json
from seedbridge.stage5_pipeline import run_stage5_mechanism


pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("SEEDBRIDGE_INTEGRATION") != "1",
    reason="set SEEDBRIDGE_INTEGRATION=1 to run native tools")]


@pytest.mark.parametrize("fixture", ["reservation_flawed", "request_flawed"])
def test_joint_two_call_model_replays_on_both_engines_and_repair(
        tmp_path: Path, fixture: str):
    report = run_stage5_mechanism(
        RunConfig(fixture, seed=1, warmup_tests=100, max_prefixes=5,
                  process_timeout=60, total_solve_timeout=180),
        tmp_path / "mechanism", suffix_length=2)
    assert report["status"] == "safety_confirmed", report.get("error")
    confirmed = report["confirmed"]
    assert confirmed["two_step_only"] is True
    assert confirmed["classification"] == "two_step_only_counterexample"
    assert set(confirmed["assignments"]) == {"arg0", "arg1"}
    assert Path(confirmed["flawed_foundry_record"]).is_file()
    assert Path(confirmed["repaired_foundry_record"]).is_file()
    flawed = read_json(Path(confirmed["flawed_native_record"]))
    repaired = read_json(Path(confirmed["repaired_native_record"]))
    assert any(sequence.get("admitted_for_mutation") is True
               and sequence["steps"][-2]["property_holds"] is True
               and sequence["steps"][-1]["property_holds"] is False
               for sequence in flawed["sequences"])
    assert any(sequence.get("admitted_for_mutation") is True
               and all(step["property_holds"] is True for step in sequence["steps"])
               for sequence in repaired["sequences"])
