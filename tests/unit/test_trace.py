from copy import deepcopy

import pytest

from seedbridge.trace import select_prefixes, uint, validate_prefix


def prefix():
    return {"steps": [{"from": "0x" + "11" * 20, "to": "0x" + "22" * 20,
                       "calldata": "0x12345678", "value": "0", "actual_block": "1",
                       "actual_timestamp": "2", "status": "success",
                       "observe": ["2", "3", "0", False], "invariant_holds": True}]}


def test_uint256_is_lossless():
    assert uint(str((1 << 256) - 1)) == (1 << 256) - 1
    for bad in [True, 1.2, "-1", str(1 << 256)]:
        with pytest.raises(ValueError):
            uint(bad)


@pytest.mark.parametrize("key,value", [("status", "revert"), ("value", "1"),
                                      ("calldata", "0x1"), ("invariant_holds", False)])
def test_invalid_prefix_rejected(key, value):
    case = prefix()
    case["steps"][0][key] = value
    with pytest.raises(ValueError):
        validate_prefix(case, verify_native=False)


def test_goal_already_holds_is_not_a_witness():
    case = prefix()
    case["steps"][0]["observe"][-1] = True
    with pytest.raises(ValueError, match="already holds"):
        validate_prefix(case, verify_native=False)


def test_missing_setup_is_not_ready():
    case = prefix()
    case["steps"][0]["observe"][0] = "0"
    with pytest.raises(ValueError, match="ready state"):
        validate_prefix(case, verify_native=False)


def test_distinct_contexts_have_distinct_identity():
    a = prefix()
    b = deepcopy(a)
    b["steps"][0]["actual_timestamp"] = "3"
    assert validate_prefix(a, verify_native=False)["case_id"] != validate_prefix(b, verify_native=False)["case_id"]


def test_duplicate_observations_with_distinct_file_provenance_are_selected_once(tmp_path):
    from seedbridge.io import file_hash
    import json
    observations = []
    for index, indent in enumerate((None, 2)):
        case = prefix()
        path = tmp_path / f"native-{index}.json"
        path.write_text(json.dumps(case["steps"], indent=indent))
        case.update(native_path=str(path), native_digest=file_hash(path))
        observations.append(case)
    assert observations[0]["native_digest"] != observations[1]["native_digest"]
    selected, rejected = select_prefixes({"sequences": observations})
    assert len(selected) == 1
    assert rejected == [{"native_digest": observations[1]["native_digest"], "reason": "Duplicate prefix"}]
