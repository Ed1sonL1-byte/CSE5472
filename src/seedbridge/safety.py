"""Independent business-property checks for the Stage 4 accounting pair."""

from .config import get_scenario


def accounting_state(observation: object) -> dict:
    if not isinstance(observation, list) or len(observation) != 4:
        raise ValueError("accounting observation must have four fields")
    values = []
    for item in observation[:3]:
        if isinstance(item, bool) or not isinstance(item, (str, int)):
            raise ValueError("accounting state field is not an integer")
        if isinstance(item, str) and (not item.isdecimal() or (len(item) > 1 and item[0] == "0")):
            raise ValueError("accounting state field is not a canonical decimal")
        value = int(item)
        if not 0 <= value <= 100:
            raise ValueError("accounting state field exceeds declared bound")
        values.append(value)
    if type(observation[3]) is not bool:
        raise ValueError("accounting violation marker must be boolean")
    allocated, spent, remaining = values
    computed_holds = allocated == spent + remaining
    if observation[3] is computed_holds:
        raise ValueError("accounting observer disagrees with independent property calculation")
    return {"allocated": allocated, "spent": spent, "remaining": remaining,
            "property_holds": computed_holds, "violation": not computed_holds}


def checked_state(fixture_id: str, observation: object) -> dict | None:
    if get_scenario(fixture_id).mode == "safety":
        return accounting_state(observation)
    return None
