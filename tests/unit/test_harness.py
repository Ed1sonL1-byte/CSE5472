from copy import deepcopy
from pathlib import Path

from eth_hash.auto import keccak
import pytest

from seedbridge.config import UINT256_MAX, get_scenario
from seedbridge.harness import generate_harness
from seedbridge.io import file_hash, read_json


def calldata(signature: str, value: int | None = None) -> str:
    encoded = keccak(signature.encode())[:4]
    if value is not None:
        encoded += value.to_bytes(32, "big")
    return "0x" + encoded.hex()


def phase_prefix() -> dict:
    common = {"from": "0x0000000000000000000000000000000000010000", "to": "0x" + "22" * 20,
              "value": "0", "actual_block": "12", "actual_timestamp": "100",
              "status": "success", "invariant_holds": True}
    return {"deployer": "0x0000000000000000000000000000000000030000", "steps": [
        {**common, "calldata": calldata("begin()"), "observe": ["1", "0", "0", False]},
        {**common, "calldata": calldata("advance(uint256)", 5), "observe": ["2", "8", "0", False]},
    ]}


def test_manifest_binds_source_prefix_and_compiler(tmp_path: Path):
    manifest = generate_harness("phase_counter", phase_prefix(), tmp_path / "project", argument=67)
    assert read_json(Path(manifest["manifest_path"])) == manifest
    assert manifest["fixture_source_sha256"] == file_hash(get_scenario("phase_counter").source_file)
    assert manifest["foundry_sha256"] == file_hash(get_scenario("phase_counter").root / "foundry.toml")
    assert manifest["prefix_sha256"] == file_hash(Path(manifest["prefix_path"]))
    assert manifest["suffix_context"]["from"] == "0x0000000000000000000000000000000000010000"
    assert manifest["suffix_context"]["actual_timestamp"] == "100"
    assert manifest["argument"] == "67"
    assert "test_replay()" in manifest["expected_test_signatures"]
    source = Path(manifest["harness_path"]).read_text()
    goal_body = source.split("function check_goal", 1)[1].split("function test_replay", 1)[0]
    assert goal_body.count("assert(") == 1
    assert "assert(!goal);" in goal_body
    assert "vm.store" not in source


@pytest.mark.parametrize("field,value", [
    ("from", "0x123"), ("to", "0xzz" + "11" * 19),
    ("calldata", "0xabc"), ("calldata", "0xdeadbeef"),
    ("value", "1"), ("value", True), ("actual_block", "-1"),
    ("actual_timestamp", str(UINT256_MAX + 1)), ("status", "revert"),
    ("invariant_holds", False), ("observe", ["1", "0", "0", "false"]),
    ("observe", ["3", "8", "0", True]),
])
def test_rejects_unsupported_prefix_before_writing(tmp_path: Path, field: str, value):
    prefix = phase_prefix()
    prefix["steps"][0][field] = value
    destination = tmp_path / "project"
    with pytest.raises(ValueError):
        generate_harness("phase_counter", prefix, destination)
    assert not destination.exists()


def test_rejects_mixed_targets_and_backwards_context(tmp_path: Path):
    for field, value in (("to", "0x" + "44" * 20), ("actual_timestamp", "99"),
                         ("actual_block", "11")):
        prefix = phase_prefix()
        prefix["steps"][1][field] = value
        with pytest.raises(ValueError):
            generate_harness("phase_counter", prefix, tmp_path / field)


def test_rejects_actor_or_deployer_outside_scenario(tmp_path: Path):
    for field, value in (("from", "0x" + "44" * 20), ("deployer", "0x" + "55" * 20)):
        prefix = phase_prefix()
        if field == "from":
            prefix["steps"][1][field] = value
        else:
            prefix[field] = value
        with pytest.raises(ValueError):
            generate_harness("phase_counter", prefix, tmp_path / field)


def test_rejects_wrong_builtin_selector_and_unbounded_prefix(tmp_path: Path):
    with pytest.raises(ValueError):
        generate_harness("bounded_ledger", phase_prefix(), tmp_path / "wrong")
    prefix = phase_prefix()
    prefix["steps"] *= 2
    with pytest.raises(ValueError):
        generate_harness("phase_counter", prefix, tmp_path / "long")
    with pytest.raises(ValueError):
        generate_harness("external_contract", {}, tmp_path / "foreign")


def test_does_not_overwrite_existing_project(tmp_path: Path):
    destination = tmp_path / "project"
    generate_harness("phase_counter", phase_prefix(), destination)
    first_manifest = (destination / "manifest.json").read_text()
    with pytest.raises(ValueError):
        generate_harness("phase_counter", phase_prefix(), destination, 67)
    assert (destination / "manifest.json").read_text() == first_manifest


def test_optional_deployer_is_validated_and_input_not_mutated(tmp_path: Path):
    prefix = phase_prefix()
    original = deepcopy(prefix)
    generate_harness("phase_counter", prefix, tmp_path / "valid")
    assert prefix == original
    prefix["deployer"] = "not an address"
    with pytest.raises(ValueError):
        generate_harness("phase_counter", prefix, tmp_path / "invalid")


@pytest.mark.parametrize("fixture", ["phase_counter", "bounded_ledger"])
def test_scenario_manifest_captures_stage1_constraints(fixture):
    scenario = get_scenario(fixture).to_dict()
    assert scenario["schema_version"] == 1
    assert scenario["target_call"] in scenario["allowed_calls"]
    assert scenario["symbolic_parameter"] == {
        "name": "arg0", "type": "uint256", "minimum": "0", "maximum": str(UINT256_MAX),
    }
    assert scenario["execution"] == {
        "prefix_steps": {"minimum": 1, "maximum": 3},
        "worker_count": 1, "call_value": "0", "reinsertion_rounds": 1,
    }
