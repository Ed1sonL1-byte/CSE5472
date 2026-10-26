"""Independent arithmetic for the owned, inert safety-property fixtures."""

from .config import get_scenario


SOLIDITY_EXPRESSIONS = {
    "allocation_conservation": "p == q + r",
    "reservation_conservation": "p + q + r == 100",
    "approval_bound": "r <= q",
}


def _numbers(observation: object, bounds: tuple[tuple[int, int], ...]) -> list[int]:
    if not isinstance(observation, list) or len(observation) != 4:
        raise ValueError("safety observation must have four fields")
    values = []
    for item, (minimum, maximum) in zip(observation[:3], bounds):
        if isinstance(item, bool) or not isinstance(item, (str, int)):
            raise ValueError("safety state field is not an integer")
        if isinstance(item, str) and (not item.isdecimal() or (len(item) > 1 and item[0] == "0")):
            raise ValueError("safety state field is not a canonical decimal")
        value = int(item)
        if not minimum <= value <= maximum:
            raise ValueError("safety state field exceeds declared bound")
        values.append(value)
    if type(observation[3]) is not bool:
        raise ValueError("safety violation marker must be boolean")
    return values


def external_count_property(property_id: str, count: int, *, success: bool,
                            signature: str) -> bool:
    """Independent read of one public counter. The target has no observe()."""
    if type(count) is not int or count < 0 or count.bit_length() > 256:
        raise ValueError("external count is outside uint256")
    if property_id == "count_after_subtraction_at_most_initial":
        return not (success and signature == "run(uint256)" and count > 1)
    if property_id == "local_arithmetic_preserves_count":
        return not (success and signature == "run(uint256)" and count != 1)
    raise ValueError(f"unsupported external property: {property_id}")


def compute_property(property_id: str, values: list[int]) -> bool:
    if len(values) != 3:
        raise ValueError("a safety property requires three concrete integers")
    p, q, r = values
    if property_id == "allocation_conservation":
        return p == q + r
    if property_id == "reservation_conservation":
        return p + q + r == 100
    if property_id == "approval_bound":
        return r <= q
    raise ValueError(f"unsupported local property: {property_id}")


def _state(property_id: str, fields: tuple[str, str, str, str],
           bounds: tuple[tuple[int, int], ...], observation: object) -> dict:
    values = _numbers(observation, bounds)
    holds = compute_property(property_id, values)
    if observation[3] is holds:
        raise ValueError("safety observer disagrees with independent property calculation")
    return {**dict(zip(fields[:3], values)), "property_holds": holds,
            "violation": not holds}


def accounting_state(observation: object) -> dict:
    """Keep the Stage 4 public helper and its exact three-counter bounds."""
    scenario = get_scenario("accounting_flawed")
    return _state("allocation_conservation", scenario.state_fields,
                  scenario.state_bounds, observation)


def checked_state(fixture_id: str, observation: object) -> dict | None:
    scenario = get_scenario(fixture_id)
    if scenario.mode != "safety":
        return None
    assert scenario.property_id is not None
    return _state(scenario.property_id, scenario.state_fields,
                  scenario.state_bounds, observation)
