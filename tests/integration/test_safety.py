"""Real Medusa → Halmos → Foundry → Medusa accounting-property acceptance."""

import os
from pathlib import Path

import pytest

from seedbridge.config import RunConfig
from seedbridge.pipeline import run_pipeline
from seedbridge.safety import accounting_state


pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("SEEDBRIDGE_INTEGRATION") != "1",
    reason="set SEEDBRIDGE_INTEGRATION=1 to run native tools")]


def test_known_local_defect_is_confirmed_and_repaired_with_real_tools(tmp_path: Path):
    report, directory = run_pipeline(
        RunConfig("accounting_flawed", seed=1, warmup_tests=100, max_prefixes=5),
        tmp_path / "safety-demo")
    assert report["status"] == "safety_confirmed", (directory, report.get("error"))
    assert report["roundtrip"]["status"] == "passed"
    assert report["observer_control"]["status"] == "passed"
    accepted = [attempt for attempt in report["attempts"] if "property_evidence" in attempt]
    assert len(accepted) == 1
    attempt = accepted[0]
    assert attempt["prefix_check"]["status"] == "prefix_confirmed"
    assert attempt["solve"]["status"] == "candidate"
    assert Path(attempt["candidate"]["model_file"]).is_file()
    assert attempt["replay"]["status"] == "violation_confirmed"
    assert attempt["admission"]["replayed_by_medusa"] is True
    assert attempt["property_evidence"]["first_violation"]["call_index"] == len(
        next(prefix for prefix in report["prefixes"] if prefix["case_id"] == attempt["case_id"])["steps"])
    before = attempt["property_evidence"]["before_suffix"]
    after = attempt["property_evidence"]["after_suffix"]
    repaired = attempt["repaired_evidence"]["after_suffix"]
    assert before["property_holds"] is True
    assert after["property_holds"] is False
    assert repaired["property_holds"] is True
    assert attempt["repaired_replay"]["status"] == "property_preserved"
    assert accounting_state([str(after[key]) for key in ("allocated", "spent", "remaining")]
                            + [True])["violation"] is True
