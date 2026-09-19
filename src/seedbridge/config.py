"""Explicit, validated support for the four repository-owned teaching fixtures."""

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UINT256_MAX = (1 << 256) - 1


@dataclass(frozen=True)
class Scenario:
    fixture_id: str
    contract: str
    suffix: str
    allowed_calls: tuple[str, ...]
    actor: str = "0x0000000000000000000000000000000000010000"
    deployer: str = "0x0000000000000000000000000000000000030000"
    observe_id: str = "observe()"
    goal_id: str = "observe.goal"
    invariant_id: str = "invariantHolds()"
    prefix_minimum: int = 1
    prefix_maximum: int = 3
    ready_observation_index: int = 0
    ready_values: tuple[int, ...] = (2,)
    state_fields: tuple[str, str, str, str] = ("phase", "counter", "unused", "goal")
    state_bounds: tuple[tuple[int, int], tuple[int, int], tuple[int, int]] = (
        (0, 3), (0, 19), (0, 0),
    )

    def __post_init__(self) -> None:
        if not 1 <= self.prefix_minimum <= self.prefix_maximum <= 3:
            raise ValueError("scenario prefix bounds must remain within 1..3")
        if self.ready_observation_index not in range(3) or not self.ready_values:
            raise ValueError("scenario ready predicate must reference a numeric observation")
        if len(self.state_fields) != 4 or len(self.state_bounds) != 3:
            raise ValueError("scenario state projection must declare three integers and goal")
        if any(type(low) is not int or type(high) is not int or low < 0 or high < low
               for low, high in self.state_bounds):
            raise ValueError("scenario state projection bounds must be finite uint ranges")

    def ready(self, observation: list[object], prefix_length: int) -> bool:
        if not self.prefix_minimum <= prefix_length <= self.prefix_maximum:
            return False
        if len(observation) != 4 or type(observation[3]) is not bool or observation[3]:
            return False
        try:
            value = int(observation[self.ready_observation_index])
        except (TypeError, ValueError):
            return False
        return value in self.ready_values

    @property
    def root(self) -> Path:
        return ROOT / "fixtures" / self.fixture_id

    @property
    def source_file(self) -> Path:
        return self.root / "src" / f"{self.contract}.sol"

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "fixture_id": self.fixture_id,
            "project_path": str(self.root),
            "source_path": str(self.source_file),
            "contract": self.contract,
            "deployment": {
                "deployer": self.deployer,
                "constructor_signature": f"{self.contract}()",
                "constructor_arguments": [],
            },
            "actor": self.actor,
            "allowed_calls": list(self.allowed_calls),
            "target_call": f"{self.suffix}(uint256)",
            "symbolic_parameter": {
                "name": "arg0", "type": "uint256", "minimum": "0",
                "maximum": str(UINT256_MAX),
            },
            "goal_id": self.goal_id,
            "observe_id": self.observe_id,
            "invariant_id": self.invariant_id,
            "ready_predicate": {
                "observation_index": self.ready_observation_index,
                "operator": "in",
                "values": list(self.ready_values),
            },
            "state_projection": {
                "fields": list(self.state_fields),
                "integer_bounds": [
                    {"minimum": str(low), "maximum": str(high)}
                    for low, high in self.state_bounds
                ],
                "goal_domain": [False, True],
            },
            "goal_definition": "observe[3] == true",
            "execution": {
                "prefix_steps": {"minimum": self.prefix_minimum, "maximum": self.prefix_maximum},
                "worker_count": 1, "call_value": "0", "reinsertion_rounds": 1,
            },
        }


SCENARIOS = {
    "phase_counter": Scenario(
        "phase_counter", "PhaseCounter", "complete",
        ("begin()", "advance(uint256)", "complete(uint256)"),
    ),
    "bounded_ledger": Scenario(
        "bounded_ledger", "BoundedLedger", "settle",
        ("open()", "reserve(uint256)", "settle(uint256)"),
        state_fields=("phase", "total", "reserved", "goal"),
        state_bounds=((0, 3), (0, 30), (0, 23)),
    ),
    "range_gate": Scenario(
        "range_gate", "RangeGate", "passRange",
        ("begin()", "configure(uint256)", "passRange(uint256)"),
        prefix_minimum=2, prefix_maximum=2,
        state_fields=("phase", "bound", "offset", "goal"),
        state_bounds=((0, 3), (0, 30), (0, 32)),
    ),
    "workflow_gate": Scenario(
        "workflow_gate", "WorkflowGate", "unlock",
        ("start()", "choose(uint256)", "unlock(uint256)", "continueWork(uint256)"),
        prefix_minimum=2, prefix_maximum=2,
        state_fields=("phase", "lane", "progress", "goal"),
        state_bounds=((0, 5), (0, 3), (0, 4)),
    ),
}


def get_scenario(fixture_id: str) -> Scenario:
    try:
        return SCENARIOS[fixture_id]
    except KeyError:
        raise ValueError(f"Unsupported fixture: {fixture_id}; choose one of {list(SCENARIOS)}") from None


@dataclass(frozen=True)
class RunConfig:
    fixture_id: str
    seed: int = 1
    max_prefixes: int = 5
    warmup_tests: int = 400
    process_timeout: float = 60
    total_solve_timeout: float = 180

    def __post_init__(self) -> None:
        get_scenario(self.fixture_id)
        if not 0 <= self.seed < (1 << 63):
            raise ValueError("seed must fit a nonnegative signed 64-bit integer")
        if not 1 <= self.max_prefixes <= 20:
            raise ValueError("max_prefixes must be in [1, 20]")
        if not 1 <= self.warmup_tests <= 10000:
            raise ValueError("warmup_tests must be in [1, 10000]")
        if self.process_timeout <= 0 or self.total_solve_timeout <= 0:
            raise ValueError("runtime limits must be positive")
