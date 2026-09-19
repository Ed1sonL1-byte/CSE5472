from pathlib import Path

import pytest

from seedbridge.benchmark import _write_goal_hits_chart, load_benchmark_config
from seedbridge.config import ROOT


def test_frozen_benchmark_declares_exact_formal_matrix_and_rotated_order():
    config = load_benchmark_config(ROOT / "configs/stage2-benchmark.json")
    assert len(config.fixtures) * len(config.repeats) * len(config.arms) == 60
    assert config.repeats == (1, 2, 3, 4, 5)
    assert len(set(config.arm_orders.values())) > 1
    assert all(set(order) == set(config.arms) for order in config.arm_orders.values())
    assert config.max_prefixes <= 4 and config.max_candidates <= 4
    assert config.concrete_attempts_per_prefix <= 64


def test_frozen_budget_reserves_native_work_after_augmentation():
    config = load_benchmark_config(ROOT / "configs/stage2-benchmark.json")
    budget = config.budget
    assert budget.augmentation_limit_seconds + budget.startup_reserve_seconds + budget.continuation_reserve_seconds < budget.total_seconds
    assert budget.common_limit_seconds < budget.total_seconds


def test_missing_seed_is_rejected(tmp_path: Path):
    import json
    source = json.loads((ROOT / "configs/stage2-benchmark.json").read_text())
    source["seeds"].pop("workflow_gate:5")
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError, match="missing valid seed"):
        load_benchmark_config(path)


def test_goal_hit_chart_is_generated_from_group_counts(tmp_path: Path):
    groups = {}
    for fixture in ("phase_counter", "bounded_ledger", "range_gate", "workflow_gate"):
        for arm in ("native_resume", "concrete_augment", "symbolic_augment"):
            groups[f"{fixture}:{arm}"] = {"goal_hits": 3}
    output = tmp_path / "goal-hits.svg"
    _write_goal_hits_chart({"groups": groups}, output)
    svg = output.read_text()
    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"')
    assert "Stage 2 goal hits" in svg
    assert svg.count(">3/5</text>") == 12
