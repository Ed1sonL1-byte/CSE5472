"""Non-overlapping wall-clock accounting for Stage 2 campaigns."""

from contextlib import contextmanager
from dataclasses import dataclass
import time
from typing import Callable, Iterator


STAGE_STATUSES = {
    "running", "completed", "skipped", "no_eligible_prefix", "no_candidate",
    "timeout", "campaign_deadline", "invalid_model", "replay_mismatch",
    "tool_error", "evidence_error", "unverified",
}


class CampaignDeadlineError(TimeoutError):
    """The campaign has no chargeable wall-clock budget remaining."""

    status = "campaign_deadline"


@dataclass
class StageHandle:
    """Mutable outcome for one stage while timing remains owned by the ledger."""

    record: dict

    def finish(self, status: str = "completed", reason: str | None = None) -> None:
        if self.record["status"] != "running":
            raise RuntimeError("stage outcome was already finalized")
        if status not in STAGE_STATUSES - {"running"}:
            raise ValueError(f"unsupported stage status: {status}")
        self.record["status"] = status
        if reason:
            self.record["reason"] = reason


class BudgetLedger:
    """Charge every campaign operation to one monotonic wall-clock deadline."""

    def __init__(self, total_seconds: float, *, cleanup_tolerance_seconds: float = 2.0,
                 initial_charge_seconds: float = 0.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if total_seconds <= 0:
            raise ValueError("total campaign budget must be positive")
        if cleanup_tolerance_seconds < 0:
            raise ValueError("cleanup tolerance cannot be negative")
        if not 0 <= initial_charge_seconds < total_seconds:
            raise ValueError("initial charge must be nonnegative and smaller than total budget")
        self.total_seconds = float(total_seconds)
        self.cleanup_tolerance_seconds = float(cleanup_tolerance_seconds)
        self.initial_charge_seconds = float(initial_charge_seconds)
        self._clock = clock
        self._physical_started_at = clock()
        self.started_at = self._physical_started_at - self.initial_charge_seconds
        self.deadline = self._physical_started_at + self.total_seconds - self.initial_charge_seconds
        self._active: str | None = None
        self.records: list[dict] = []
        if self.initial_charge_seconds:
            self.records.append({
                "name": "common_build_warmup_charge",
                "kind": "common",
                "status": "completed",
                "reason": "physical common work is charged once to each arm",
                "started_offset_seconds": 0.0,
                "finished_offset_seconds": self.initial_charge_seconds,
                "elapsed_seconds": self.initial_charge_seconds,
                "budget_before_seconds": self.total_seconds,
                "budget_after_seconds": self.total_seconds - self.initial_charge_seconds,
                "after_deadline": False,
                "after_deadline_by_seconds": 0.0,
                "within_cleanup_tolerance": True,
                "attempted": True,
                "logical_precharge": True,
            })

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, self._clock() - self.started_at)

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.deadline - self._clock())

    def timeout_for(self, requested_seconds: float, *, reserve_seconds: float = 0.0) -> float:
        """Bound a subprocess timeout by the campaign deadline and a future reserve."""
        if requested_seconds <= 0:
            raise ValueError("requested timeout must be positive")
        if reserve_seconds < 0:
            raise ValueError("reserve cannot be negative")
        available = self.remaining_seconds - reserve_seconds
        if available <= 0:
            raise CampaignDeadlineError("campaign budget is exhausted or reserved")
        return min(float(requested_seconds), available)

    def record_skipped(self, name: str, *, kind: str, status: str, reason: str) -> dict:
        if self._active is not None:
            raise RuntimeError("cannot record a skipped stage while another stage is active")
        if status not in STAGE_STATUSES - {"running"}:
            raise ValueError(f"unsupported stage status: {status}")
        offset = self.elapsed_seconds
        record = {
            "name": name,
            "kind": kind,
            "status": status,
            "reason": reason,
            "started_offset_seconds": offset,
            "finished_offset_seconds": offset,
            "elapsed_seconds": 0.0,
            "budget_before_seconds": self.remaining_seconds,
            "budget_after_seconds": self.remaining_seconds,
            "after_deadline": offset > self.total_seconds,
            "after_deadline_by_seconds": max(0.0, offset - self.total_seconds),
            "within_cleanup_tolerance": (
                max(0.0, offset - self.total_seconds) <= self.cleanup_tolerance_seconds),
            "attempted": False,
        }
        self.records.append(record)
        return record

    @contextmanager
    def stage(self, name: str, *, kind: str) -> Iterator[StageHandle]:
        if not name or not kind:
            raise ValueError("stage name and kind are required")
        if self._active is not None:
            raise RuntimeError(f"stage {self._active!r} is already active")
        if self.remaining_seconds <= 0:
            self.record_skipped(name, kind=kind, status="campaign_deadline",
                                reason="stage was not started because the total budget was exhausted")
            raise CampaignDeadlineError("campaign budget exhausted before stage start")

        start = self._clock()
        record = {
            "name": name,
            "kind": kind,
            "status": "running",
            "started_offset_seconds": max(0.0, start - self.started_at),
            "budget_before_seconds": max(0.0, self.deadline - start),
            "attempted": True,
        }
        self.records.append(record)
        self._active = name
        handle = StageHandle(record)
        try:
            yield handle
        except BaseException as error:
            if record["status"] == "running":
                record["status"] = getattr(error, "status", "tool_error")
                record["reason"] = f"{type(error).__name__}: {error}"
            raise
        else:
            if record["status"] == "running":
                handle.finish()
        finally:
            finish = self._clock()
            record["finished_offset_seconds"] = max(0.0, finish - self.started_at)
            record["elapsed_seconds"] = max(0.0, finish - start)
            record["budget_after_seconds"] = max(0.0, self.deadline - finish)
            record["after_deadline"] = finish > self.deadline
            record["after_deadline_by_seconds"] = max(0.0, finish - self.deadline)
            record["within_cleanup_tolerance"] = (
                record["after_deadline_by_seconds"] <= self.cleanup_tolerance_seconds)
            if record["after_deadline"] and record["status"] == "completed":
                record["status"] = "campaign_deadline"
                record["reason"] = "stage completed after the chargeable campaign deadline"
            self._active = None

    def summary(self, *, charged_end_seconds: float | None = None) -> dict:
        if self._active is not None:
            raise RuntimeError("cannot summarize while a stage is active")
        current = self.elapsed_seconds
        wall = current if charged_end_seconds is None else float(charged_end_seconds)
        if not 0 <= wall <= current:
            raise ValueError("charged end must be within the ledger lifetime")
        stage_total = min(
            sum(float(record["elapsed_seconds"]) for record in self.records), wall)
        return {
            "budget_seconds": self.total_seconds,
            "initial_common_charge_seconds": self.initial_charge_seconds,
            "cleanup_tolerance_seconds": self.cleanup_tolerance_seconds,
            "charged_wall_seconds": wall,
            "stage_elapsed_seconds": stage_total,
            "unattributed_wall_seconds": max(0.0, wall - stage_total),
            "remaining_seconds": max(0.0, self.total_seconds - wall),
            "deadline_reached": wall >= self.total_seconds,
            "cpu_usage": {
                "status": "unavailable",
                "reason": "portable process-tree CPU attribution is not available",
            },
        }


class ElapsedStages:
    """Stage 1-compatible elapsed map that records exits through exceptions and returns."""

    def __init__(self, target: dict[str, float], *,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.target = target
        self._clock = clock
        self._active: str | None = None

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        if self._active is not None:
            raise RuntimeError(f"stage {self._active!r} is already active")
        self._active = name
        started = self._clock()
        try:
            yield
        finally:
            elapsed = max(0.0, self._clock() - started)
            self.target[name] = self.target.get(name, 0.0) + elapsed
            self._active = None
