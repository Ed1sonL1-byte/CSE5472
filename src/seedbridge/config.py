"""Explicit support for the two repository-owned teaching fixtures."""

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
            "execution": {
                "prefix_steps": {"minimum": 1, "maximum": 3},
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
