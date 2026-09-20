"""Versioned, data-driven Stage 3 study planning."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re

from .campaign import ARMS
from .config import SCENARIOS, get_scenario
from .io import read_json, write_json


PROFILE_ID = re.compile(r"[a-z0-9][a-z0-9-]{1,63}\Z")
FAMILIES = {"total_budget", "goal_invocation_limit"}


@dataclass(frozen=True)
class StudyProfile:
    profile_id: str
    arm: str
    total_budget_seconds: float
    prefix_check_limit_seconds: float
    goal_invocation_limit_seconds: float | None
    augmentation_limit_seconds: float
    startup_reserve_seconds: float
    continuation_reserve_seconds: float
    cleanup_tolerance_seconds: float
    families: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: dict) -> "StudyProfile":
        if not isinstance(value, dict):
            raise ValueError("study profile must be an object")
        return cls(
            profile_id=str(value["profile_id"]),
            arm=str(value["arm"]),
            total_budget_seconds=float(value["total_budget_seconds"]),
            prefix_check_limit_seconds=float(value["prefix_check_limit_seconds"]),
            goal_invocation_limit_seconds=(
                None if value.get("goal_invocation_limit_seconds") is None
                else float(value["goal_invocation_limit_seconds"])
            ),
            augmentation_limit_seconds=float(value["augmentation_limit_seconds"]),
            startup_reserve_seconds=float(value["startup_reserve_seconds"]),
            continuation_reserve_seconds=float(value["continuation_reserve_seconds"]),
            cleanup_tolerance_seconds=float(value["cleanup_tolerance_seconds"]),
            families=tuple(value["families"]),
        )

    def validate(self, common_limit_seconds: float) -> None:
        if not PROFILE_ID.fullmatch(self.profile_id):
            raise ValueError(f"invalid profile id: {self.profile_id!r}")
        if self.arm not in ARMS:
            raise ValueError(f"unknown study arm: {self.arm}")
        values = (
            self.total_budget_seconds, self.prefix_check_limit_seconds,
            self.augmentation_limit_seconds, self.startup_reserve_seconds,
            self.continuation_reserve_seconds, self.cleanup_tolerance_seconds,
        )
        if any(value <= 0 for value in values):
            raise ValueError(f"profile {self.profile_id} has a nonpositive limit")
        if self.arm == "symbolic_augment":
            if self.goal_invocation_limit_seconds is None or self.goal_invocation_limit_seconds <= 0:
                raise ValueError(f"symbolic profile {self.profile_id} needs a positive goal limit")
        elif self.goal_invocation_limit_seconds is not None:
            raise ValueError(f"non-symbolic profile {self.profile_id} cannot set a goal limit")
        if set(self.families) - FAMILIES or len(set(self.families)) != len(self.families):
            raise ValueError(f"profile {self.profile_id} has invalid experiment families")
        if not self.families:
            raise ValueError(f"profile {self.profile_id} belongs to no experiment family")
        if self.total_budget_seconds <= common_limit_seconds:
            raise ValueError(f"profile {self.profile_id} cannot pay the common-work limit")
        if (self.augmentation_limit_seconds + self.startup_reserve_seconds
                + self.continuation_reserve_seconds >= self.total_budget_seconds):
            raise ValueError(f"profile {self.profile_id} leaves no continuation budget")

    @property
    def identity(self) -> tuple:
        return (
            self.arm, self.total_budget_seconds, self.prefix_check_limit_seconds,
            self.goal_invocation_limit_seconds, self.augmentation_limit_seconds,
        )


@dataclass(frozen=True)
class StudySlot:
    study_id: str
    fixture_id: str
    repeat_id: int
    seed: int
    profile_id: str
    arm: str
    total_budget_seconds: float
    prefix_check_limit_seconds: float
    goal_invocation_limit_seconds: float | None
    families: tuple[str, ...]

    @property
    def common_block_id(self) -> str:
        return f"{self.fixture_id}/repeat-{self.repeat_id:02d}"

    @property
    def slot_id(self) -> str:
        return f"{self.common_block_id}/{self.profile_id}"

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "families": list(self.families),
            "common_block_id": self.common_block_id,
            "slot_id": self.slot_id,
        }


@dataclass(frozen=True)
class StudySpec:
    study_id: str
    mode: str
    fixtures: tuple[str, ...]
    repeats: tuple[int, ...]
    seeds: dict[str, int]
    profiles: tuple[StudyProfile, ...]
    profile_orders: dict[str, tuple[str, ...]]
    warmup_sequences: int
    continuation_sequence_safety_limit: int
    max_prefixes: int
    max_candidates: int
    concrete_attempts_per_prefix: int
    boundary_values: tuple[int, ...]
    common_limit_seconds: float
    storage_min_free_bytes: int
    storage_max_study_bytes: int
    schema_version: int = 1

    @classmethod
    def from_dict(cls, document: dict) -> "StudySpec":
        if not isinstance(document, dict) or document.get("schema_version") != 1:
            raise ValueError("study config schema_version must be 1")
        spec = cls(
            study_id=str(document["study_id"]),
            mode=str(document["mode"]),
            fixtures=tuple(document["fixtures"]),
            repeats=tuple(int(value) for value in document["repeats"]),
            seeds={str(key): int(value) for key, value in document["seeds"].items()},
            profiles=tuple(StudyProfile.from_dict(value) for value in document["profiles"]),
            profile_orders={str(key): tuple(value) for key, value in document["profile_orders"].items()},
            warmup_sequences=int(document["warmup_sequences"]),
            continuation_sequence_safety_limit=int(document["continuation_sequence_safety_limit"]),
            max_prefixes=int(document["max_prefixes"]),
            max_candidates=int(document["max_candidates"]),
            concrete_attempts_per_prefix=int(document["concrete_attempts_per_prefix"]),
            boundary_values=tuple(int(value) for value in document["boundary_values"]),
            common_limit_seconds=float(document["common_limit_seconds"]),
            storage_min_free_bytes=int(document["storage_min_free_bytes"]),
            storage_max_study_bytes=int(document["storage_max_study_bytes"]),
        )
        spec.validate()
        return spec

    def validate(self) -> None:
        if not PROFILE_ID.fullmatch(self.study_id):
            raise ValueError("study_id must be a lowercase stable identifier")
        if self.mode not in {"formal", "smoke"}:
            raise ValueError("study mode must be formal or smoke")
        if not self.fixtures or len(set(self.fixtures)) != len(self.fixtures):
            raise ValueError("study fixtures must be unique and nonempty")
        if any(fixture not in SCENARIOS for fixture in self.fixtures):
            raise ValueError("study contains an unknown fixture")
        if not self.repeats or len(set(self.repeats)) != len(self.repeats):
            raise ValueError("study repeats must be unique and nonempty")
        if any(not 1 <= repeat <= 10 for repeat in self.repeats):
            raise ValueError("study repeat ids must be in 1..10")
        if not 2 <= self.warmup_sequences <= 10000:
            raise ValueError("warmup sequence limit must be in 2..10000")
        if self.continuation_sequence_safety_limit < 10000:
            raise ValueError("continuation safety limit must be at least 10000")
        if not 1 <= self.max_prefixes <= 4 or not 1 <= self.max_candidates <= 4:
            raise ValueError("prefix and candidate limits must be in 1..4")
        if not 1 <= self.concrete_attempts_per_prefix <= 64:
            raise ValueError("concrete attempts per prefix must be in 1..64")
        if self.common_limit_seconds <= 0:
            raise ValueError("common-work limit must be positive")
        if self.storage_min_free_bytes <= 0 or self.storage_max_study_bytes <= 0:
            raise ValueError("storage safeguards must be positive")
        if not self.boundary_values or len(set(self.boundary_values)) != len(self.boundary_values):
            raise ValueError("boundary dictionary must be nonempty and unique")

        profile_ids = [profile.profile_id for profile in self.profiles]
        if not profile_ids or len(set(profile_ids)) != len(profile_ids):
            raise ValueError("study profile ids must be unique and nonempty")
        for profile in self.profiles:
            profile.validate(self.common_limit_seconds)
        identities = [profile.identity for profile in self.profiles]
        if len(set(identities)) != len(identities):
            raise ValueError("study contains duplicate execution profiles")

        expected_profiles = set(profile_ids)
        for repeat in self.repeats:
            order = self.profile_orders.get(str(repeat), ())
            if len(order) != len(profile_ids) or set(order) != expected_profiles:
                raise ValueError(f"profile order for repeat {repeat} is missing or invalid")
        for fixture in self.fixtures:
            get_scenario(fixture)
            for repeat in self.repeats:
                key = f"{fixture}:{repeat}"
                if key not in self.seeds or not 0 <= self.seeds[key] < (1 << 63):
                    raise ValueError(f"missing valid seed for {key}")

        if self.mode == "formal":
            self._validate_formal_protocol()

        slots = self.slots()
        if len({slot.slot_id for slot in slots}) != len(slots):
            raise ValueError("study slot ids are not unique")

    def _validate_formal_protocol(self) -> None:
        if set(self.fixtures) != set(SCENARIOS) or len(self.fixtures) != 4:
            raise ValueError("formal study requires exactly the four built-in fixtures")
        if self.repeats != tuple(range(1, 11)):
            raise ValueError("formal study repeats must be exactly 1..10")
        if len(self.profiles) != 8:
            raise ValueError("formal study requires eight distinct profiles per common block")
        if any(profile.augmentation_limit_seconds != 2.5 for profile in self.profiles):
            raise ValueError("formal augmentation limit must remain 2.5 seconds")
        if any(profile.prefix_check_limit_seconds != 0.75 for profile in self.profiles):
            raise ValueError("formal prefix-check limit must remain 0.75 seconds")

        main = [profile for profile in self.profiles if "total_budget" in profile.families]
        expected_main = {
            (arm, budget, 0.75 if arm == "symbolic_augment" else None)
            for arm in ARMS for budget in (8.0, 32.0)
        }
        actual_main = {
            (profile.arm, profile.total_budget_seconds, profile.goal_invocation_limit_seconds)
            for profile in main
        }
        if actual_main != expected_main or len(main) != 6:
            raise ValueError("formal total-budget family must contain the frozen six profiles")

        goal = [profile for profile in self.profiles if "goal_invocation_limit" in profile.families]
        if ({profile.goal_invocation_limit_seconds for profile in goal} != {0.5, 0.75, 1.5}
                or any(profile.arm != "symbolic_augment" or profile.total_budget_seconds != 32.0
                       for profile in goal)
                or len(goal) != 3):
            raise ValueError("formal goal-limit family must contain 0.50/0.75/1.50 at 32 seconds")

        plan = self.plan()
        if (plan["distinct_slot_count"] != 320 or plan["common_block_count"] != 40
                or plan["total_budget_slot_count"] != 240
                or plan["goal_limit_new_slot_count"] != 80
                or plan["goal_limit_comparison_slot_count"] != 120):
            raise ValueError("formal study matrix does not expand to the frozen 320-slot protocol")

    def seed(self, fixture: str, repeat: int) -> int:
        return self.seeds[f"{fixture}:{repeat}"]

    def profile(self, profile_id: str) -> StudyProfile:
        try:
            return next(profile for profile in self.profiles if profile.profile_id == profile_id)
        except StopIteration as error:
            raise ValueError(f"unknown study profile: {profile_id}") from error

    def slots(self) -> list[StudySlot]:
        result = []
        for fixture in self.fixtures:
            for repeat in self.repeats:
                for profile_id in self.profile_orders[str(repeat)]:
                    profile = self.profile(profile_id)
                    result.append(StudySlot(
                        study_id=self.study_id, fixture_id=fixture, repeat_id=repeat,
                        seed=self.seed(fixture, repeat), profile_id=profile.profile_id,
                        arm=profile.arm, total_budget_seconds=profile.total_budget_seconds,
                        prefix_check_limit_seconds=profile.prefix_check_limit_seconds,
                        goal_invocation_limit_seconds=profile.goal_invocation_limit_seconds,
                        families=profile.families,
                    ))
        return result

    def plan(self) -> dict:
        slots = self.slots()
        blocks = [
            {"common_block_id": f"{fixture}/repeat-{repeat:02d}", "fixture_id": fixture,
             "repeat_id": repeat, "seed": self.seed(fixture, repeat),
             "profile_order": list(self.profile_orders[str(repeat)])}
            for fixture in self.fixtures for repeat in self.repeats
        ]
        goal_slots = [slot for slot in slots if "goal_invocation_limit" in slot.families]
        return {
            "schema_version": 1,
            "study_id": self.study_id,
            "mode": self.mode,
            "common_block_count": len(blocks),
            "distinct_slot_count": len(slots),
            "total_budget_slot_count": sum(
                "total_budget" in slot.families for slot in slots),
            "goal_limit_comparison_slot_count": len(goal_slots),
            "goal_limit_reused_slot_count": sum(
                len(slot.families) == 2 for slot in goal_slots),
            "goal_limit_new_slot_count": sum(
                slot.families == ("goal_invocation_limit",) for slot in goal_slots),
            "blocks": blocks,
            "slots": [slot.to_dict() for slot in slots],
        }


def load_study_spec(path: Path) -> StudySpec:
    return StudySpec.from_dict(read_json(path))


def write_study_plan(config_path: Path, output: Path | None = None) -> dict:
    plan = load_study_spec(config_path).plan()
    if output:
        write_json(output, plan)
    return plan
