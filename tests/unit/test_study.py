from copy import deepcopy
import json
from pathlib import Path

import pytest

from seedbridge.benchmark import load_benchmark_config
from seedbridge.config import ROOT
from seedbridge.study import StudySpec, load_study_spec, write_study_plan
from seedbridge.study_audit import write_observations_csv


CONFIG = ROOT / "configs/stage3-study.json"


def source() -> dict:
    return json.loads(CONFIG.read_text())


def test_formal_study_expands_frozen_distinct_matrix():
    spec = load_study_spec(CONFIG)
    plan = spec.plan()
    assert plan["distinct_slot_count"] == 320
    assert plan["common_block_count"] == 40
    assert plan["total_budget_slot_count"] == 240
    assert plan["goal_limit_comparison_slot_count"] == 120
    assert plan["goal_limit_reused_slot_count"] == 40
    assert plan["goal_limit_new_slot_count"] == 80
    assert len({slot["slot_id"] for slot in plan["slots"]}) == 320
    assert len({(slot["fixture_id"], slot["repeat_id"]) for slot in plan["slots"]}) == 40


def test_goal_limit_reuses_main_q075_slot_instead_of_duplicating_it():
    spec = load_study_spec(CONFIG)
    matching = [
        slot for slot in spec.slots()
        if slot.fixture_id == "phase_counter" and slot.repeat_id == 1
        and slot.arm == "symbolic_augment" and slot.total_budget_seconds == 32
    ]
    assert {slot.goal_invocation_limit_seconds for slot in matching} == {0.5, 0.75, 1.5}
    reused = next(slot for slot in matching if slot.goal_invocation_limit_seconds == 0.75)
    assert set(reused.families) == {"total_budget", "goal_invocation_limit"}


@pytest.mark.parametrize("mutation,match", [
    (lambda value: value["fixtures"].append("unknown"), "unknown fixture"),
    (lambda value: value["profiles"].append(deepcopy(value["profiles"][0])), "profile ids"),
    (lambda value: value["profiles"][2].update(goal_invocation_limit_seconds=0), "positive goal"),
    (lambda value: value["profile_orders"]["1"].pop(), "profile order"),
    (lambda value: value["seeds"].pop("phase_counter:10"), "missing valid seed"),
])
def test_formal_study_rejects_invalid_or_incomplete_matrix(mutation, match):
    value = source()
    mutation(value)
    with pytest.raises(ValueError, match=match):
        StudySpec.from_dict(value)


def test_smoke_mode_accepts_builtin_subsets_but_not_external_targets():
    value = source()
    value["mode"] = "smoke"
    value["study_id"] = "stage3-smoke"
    value["fixtures"] = ["phase_counter"]
    value["repeats"] = [1]
    value["profiles"] = value["profiles"][:3]
    value["profile_orders"] = {"1": [profile["profile_id"] for profile in value["profiles"]]}
    assert len(StudySpec.from_dict(value).slots()) == 3
    value["fixtures"] = ["external_contract"]
    with pytest.raises(ValueError, match="unknown fixture"):
        StudySpec.from_dict(value)


def test_study_plan_can_be_written_without_running_native_tools(tmp_path: Path):
    output = tmp_path / "plan.json"
    plan = write_study_plan(CONFIG, output)
    assert json.loads(output.read_text()) == plan
    assert plan["distinct_slot_count"] == 320


def test_stage2_frozen_config_remains_compatible():
    config = load_benchmark_config(ROOT / "configs/stage2-benchmark.json")
    assert len(config.fixtures) * len(config.repeats) * len(config.arms) == 60


def test_stage3_observation_csv_uses_repository_line_endings(tmp_path: Path):
    output = tmp_path / "observations.csv"
    write_observations_csv({"rows": [{"slot_id": "fixture/repeat-01/profile"}]}, output)
    assert b"\r" not in output.read_bytes()
