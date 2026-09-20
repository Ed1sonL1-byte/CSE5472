import pytest

from seedbridge.augmentation import (
    DEFAULT_BOUNDARY_VALUES,
    _checked_result_status,
    _unsuccessful_symbolic_status,
    concrete_values,
)
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
