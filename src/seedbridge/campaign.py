"""Versioned Stage 2 campaign data protocol."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import uuid

from .budget import BudgetLedger
from .config import get_scenario
from .io import write_json


ARMS = ("native_resume", "concrete_augment", "symbolic_augment")
EXECUTION_STATUSES = {
    "pending", "completed", "campaign_deadline", "tool_error", "evidence_error",
}
AUGMENTATION_STATUSES = {
    "not_applicable", "pending", "completed", "no_eligible_prefix", "no_candidate",
    "timeout", "invalid_model", "replay_mismatch", "tool_error", "partial",
}
LINEAGE_STATUSES = {"not_applicable", "pending", "verified", "unverified"}


@dataclass(frozen=True)
class BudgetSpec:
    total_seconds: float
    common_limit_seconds: float
    augmentation_limit_seconds: float
    query_limit_seconds: float
    startup_reserve_seconds: float
    continuation_reserve_seconds: float
    cleanup_tolerance_seconds: float = 2.0

    def __post_init__(self) -> None:
        values = asdict(self)
        if any(type(value) not in (int, float) or value < 0 for value in values.values()):
            raise ValueError("campaign budget values must be nonnegative numbers")
        if self.total_seconds <= 0 or self.query_limit_seconds <= 0:
            raise ValueError("total and per-query budgets must be positive")
        if self.common_limit_seconds > self.total_seconds:
            raise ValueError("common limit cannot exceed the total budget")
        if self.augmentation_limit_seconds > self.total_seconds:
            raise ValueError("augmentation limit cannot exceed the total budget")
        if self.startup_reserve_seconds + self.continuation_reserve_seconds >= self.total_seconds:
            raise ValueError("startup and continuation reserves must leave chargeable campaign time")


@dataclass(frozen=True)
class CampaignSpec:
    fixture_id: str
    arm: str
    repeat_id: int
    seed: int
    warmup_sequences: int
    budget: BudgetSpec
    max_steps: int = 4
    max_prefixes: int = 4
    max_candidates: int = 4
    concrete_attempts_per_prefix: int = 64
    worker_count: int = 1
    call_value: str = "0"
    augmentation_rounds: int = 1
    schema_version: int = 1

    def __post_init__(self) -> None:
        get_scenario(self.fixture_id)
        if self.arm not in ARMS:
            raise ValueError(f"unsupported campaign arm: {self.arm}")
        if self.schema_version != 1:
            raise ValueError("unsupported CampaignSpec schema")
        if not 1 <= self.repeat_id <= 5:
            raise ValueError("repeat_id must be in [1, 5]")
        if not 0 <= self.seed < (1 << 63):
            raise ValueError("seed must fit a nonnegative signed 64-bit integer")
        if not 1 <= self.warmup_sequences <= 10000:
            raise ValueError("warmup_sequences must be in [1, 10000]")
        if self.max_steps != 4 or not 1 <= self.max_prefixes <= 4:
            raise ValueError("Stage 2 requires four-step campaigns and at most four prefixes")
        if not 1 <= self.max_candidates <= 4:
            raise ValueError("Stage 2 accepts at most four candidates")
        if self.concrete_attempts_per_prefix <= 0:
            raise ValueError("concrete attempt limit must be positive")
        if self.worker_count != 1 or self.call_value != "0" or self.augmentation_rounds != 1:
            raise ValueError("Stage 2 fixes one worker, zero value, and one augmentation round")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, document: dict) -> "CampaignSpec":
        if not isinstance(document, dict) or not isinstance(document.get("budget"), dict):
            raise ValueError("CampaignSpec must contain a budget object")
        fields = {**document, "budget": BudgetSpec(**document["budget"])}
        return cls(**fields)


@dataclass
class CampaignRecord:
    spec: CampaignSpec
    campaign_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    execution_status: str = "pending"
    goal_reached: bool = False
    augmentation_status: str = "pending"
    lineage_status: str = "pending"
    evaluation_valid: bool = False
    failure: dict | None = None
    artifacts: dict = field(default_factory=dict)
    outcomes: dict = field(default_factory=dict)
    stages: list[dict] = field(default_factory=list)
    budget: dict | None = None
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None

    def __post_init__(self) -> None:
        if self.spec.arm == "native_resume":
            self.augmentation_status = "not_applicable"
        self._validate_statuses()

    def _validate_statuses(self) -> None:
        if self.execution_status not in EXECUTION_STATUSES:
            raise ValueError(f"invalid execution status: {self.execution_status}")
        if self.augmentation_status not in AUGMENTATION_STATUSES:
            raise ValueError(f"invalid augmentation status: {self.augmentation_status}")
        if self.lineage_status not in LINEAGE_STATUSES:
            raise ValueError(f"invalid lineage status: {self.lineage_status}")
        if type(self.goal_reached) is not bool or type(self.evaluation_valid) is not bool:
            raise ValueError("goal_reached and evaluation_valid must be booleans")

    def finalize(self, ledger: BudgetLedger) -> None:
        self._validate_statuses()
        self.stages = list(ledger.records)
        self.budget = ledger.summary()
        self.finished_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        self._validate_statuses()
        return {
            "schema_version": 1,
            "campaign_id": self.campaign_id,
            "spec": self.spec.to_dict(),
            "execution_status": self.execution_status,
            "goal_reached": self.goal_reached,
            "augmentation_status": self.augmentation_status,
            "lineage_status": self.lineage_status,
            "evaluation_valid": self.evaluation_valid,
            "failure": self.failure,
            "artifacts": self.artifacts,
            "outcomes": self.outcomes,
            "stages": self.stages,
            "budget": self.budget,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    def save(self, path: Path) -> None:
        write_json(path, self.to_dict())
