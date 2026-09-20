from copy import deepcopy

import pytest

from seedbridge.metrics import (
    mutation_parent_events,
    normalized_sequence_identity,
    projected_state,
    set_delta,
    snapshot,
)


def step(calldata="0x12345678", observation=None, markers=None, nonce=1, timestamp=2):
    markers = markers or ["runtime:0x01"]
    return {
        "from": "0x" + "11" * 20,
        "to": "0x" + "22" * 20,
        "value": "0",
        "calldata": calldata,
        "nonce": nonce,
        "actual_timestamp": str(timestamp),
        "observe": observation or ["2", "3", "0", False],
        "coverage_markers": markers,
        "coverage_marker_hits": {marker: 1 for marker in markers},
    }


def test_sequence_identity_ignores_nonce_and_time_but_tracks_calldata():
    first = [step()]
    changed_context = [step(nonce=999, timestamp=55)]
    changed_call = [step(calldata="0x87654321")]
    assert normalized_sequence_identity(first) == normalized_sequence_identity(changed_context)
    assert normalized_sequence_identity(first) != normalized_sequence_identity(changed_call)


def test_state_projection_enforces_declared_finite_domain():
    assert projected_state("phase_counter", ["2", "19", "0", False]) == {
        "phase": 2, "counter": 19, "unused": 0, "goal": False,
    }
    with pytest.raises(ValueError, match="finite domain"):
        projected_state("phase_counter", ["2", "20", "0", False])


def test_union_difference_is_independent_of_hit_count():
    delta = set_delta(["a", "b"], ["b", "c", "c"])
    assert delta == {
        "base_count": 2, "segment_count": 2, "new_count": 1,
        "new_items": ["c"], "union_count": 3,
    }


def test_replaying_same_seed_adds_hits_without_new_sequence_state_or_coverage():
    sequence = {"steps": [step()]}
    once = snapshot("phase_counter", [sequence])
    twice = snapshot("phase_counter", [sequence, deepcopy(sequence)])
    assert once["sequence_ids"] == twice["sequence_ids"]
    assert once["states"] == twice["states"]
    assert once["coverage_markers"] == twice["coverage_markers"]
    assert twice["coverage_marker_hits"]["runtime:0x01"] == 2


def test_seed_parent_selection_excludes_startup_replay():
    lineage = [
        {"kind": "startup_replay", "parent_hashes": ["seed"]},
        {"kind": "mutation", "parent_hashes": ["other"]},
        {"kind": "mutation", "parent_hashes": ["seed"]},
    ]
    assert mutation_parent_events(lineage, {"seed"}) == [lineage[2]]
