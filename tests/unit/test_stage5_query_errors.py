"""Synthetic failure injection; the real mechanism tests use all native tools."""

from pathlib import Path
import time

from seedbridge import stage5_augment
from seedbridge.suffix import make_plan


def test_repair_regression_cannot_become_an_ordinary_candidate_miss(
        tmp_path: Path, monkeypatch):
    prefix = {"native_digest": "f" * 64,
              "native_path": str(tmp_path / "prefix.json"),
              "deployer": "0x" + "03" * 20,
              "steps": [{"from": "0x" + "01" * 20,
                         "to": "0x" + "02" * 20,
                         "calldata": "0x819b25ba", "value": "0",
                         "actual_block": "2", "actual_timestamp": "2",
                         "status": "success", "observe": ["100", "0", "0", False],
                         "property_holds": True, "invariant_holds": True,
                         "state_root_before_observer": "0x01",
                         "state_root_after_observer": "0x01",
                         "observer_state_unchanged": True}]}
    plan = make_plan("reservation_flawed", prefix,
                     ("reserve(uint256)", "settle(uint256)"))
    prefix["stage5_prefix_id"] = plan.prefix_id
    monkeypatch.setattr(stage5_augment, "generate_suffix_harness",
                        lambda fixture, source, selected, directory, **options: {
                            "project_path": str(directory),
                            "manifest_path": str(directory / "manifest.json")})
    results = iter([{"status": "prefix_confirmed"},
                    {"status": "candidate", "candidates": [
                        {"arg0": "36", "arg1": "36"}],
                     "output_path": str(tmp_path / "model.json")}])
    monkeypatch.setattr(stage5_augment, "run_halmos", lambda *a, **k: next(results))
    monkeypatch.setattr(stage5_augment, "build_manifest", lambda *a, **k: {})
    monkeypatch.setattr(stage5_augment, "assert_same_target", lambda *a, **k: None)
    replays = iter([{"status": "violation_confirmed", "steps": [{}, {}]},
                    {"status": "violation_confirmed"}])
    monkeypatch.setattr(stage5_augment, "concrete_replay_suffix",
                        lambda *a, **k: next(replays))
    monkeypatch.setattr(stage5_augment, "codec", lambda *a, **k: None)
    monkeypatch.setattr(stage5_augment, "read_json",
                        lambda *a, **k: {"medusa_hash": "new"})
    monkeypatch.setattr(stage5_augment, "observe",
                        lambda *a, **k: {"output_path": str(tmp_path / "native.json")})
    monkeypatch.setattr(stage5_augment, "validate_native_suffix",
                        lambda *a, **k: {"steps": [], "first_violation_call_index": 2,
                                           "two_step_only": True})
    result = stage5_augment.execute_query(
        "reservation_flawed", prefix, plan, tmp_path / "query",
        deadline=time.monotonic() + 30, per_process_limit=5,
        prefix_limit=1, solver_limit=1, solver="/bin/true", halmos="halmos",
        baseline_build={}, seed=1, warmup_hashes=set())
    assert result["status"] == "repaired_regression_failure", result.get("error")
    assert result["candidates"][0]["status"] == "violation_confirmed"
