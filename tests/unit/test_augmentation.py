from seedbridge.augmentation import DEFAULT_BOUNDARY_VALUES, concrete_values


def test_concrete_policy_uses_frozen_boundaries_then_seeded_random_values():
    first = concrete_values(7, len(DEFAULT_BOUNDARY_VALUES) + 3)
    second = concrete_values(7, len(DEFAULT_BOUNDARY_VALUES) + 3)
    other = concrete_values(8, len(DEFAULT_BOUNDARY_VALUES) + 3)
    assert first[:len(DEFAULT_BOUNDARY_VALUES)] == list(DEFAULT_BOUNDARY_VALUES)
    assert first == second
    assert first != other
    assert len(first) == len(set(first))
