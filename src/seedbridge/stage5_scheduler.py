"""Predeclared, bounded choice between one- and two-call symbolic queries."""

from __future__ import annotations

from dataclasses import dataclass, field

from .suffix import SuffixPlan


MODES = ("symbolic_one", "symbolic_two", "symbolic_adaptive")
NO_PROGRESS = {"no_candidate", "no_model_complete", "all_paths_reverted"}
TERMINAL_ERRORS = {"timeout", "unsupported", "tool_error", "invalid_model",
                   "replay_mismatch", "state_mismatch", "observer_mismatch",
                   "result_mismatch", "decode_error", "prefix_mismatch",
                   "prefix_incomplete", "incomplete", "repaired_regression_failure"}


@dataclass
class QueryScheduler:
    mode: str
    one: list[SuffixPlan]
    two: list[SuffixPlan]
    minimum_query_seconds: float
    continuation_reserve_seconds: float
    decisions: list[dict] = field(default_factory=list)
    feedback: list[dict] = field(default_factory=list)
    attempted: set[str] = field(default_factory=set)
    promoted: bool = False
    confirmed: bool = False

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError("unsupported Stage 5 symbolic mode")
        if self.minimum_query_seconds <= 0 or self.continuation_reserve_seconds < 0:
            raise ValueError("invalid query or continuation reserve")
        ids = [plan.query_id for plan in self.one + self.two]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate full-context query identity")
        if any(len(plan.calls) != 1 for plan in self.one):
            raise ValueError("one-call queue has a two-call plan")
        if any(len(plan.calls) != 2 for plan in self.two):
            raise ValueError("two-call queue has a one-call plan")

    def record_feedback(self, plan: SuffixPlan, status: str, *,
                        actual_seconds: float, remaining_seconds: float) -> None:
        if plan.query_id not in self.attempted or actual_seconds < 0 or remaining_seconds < 0:
            raise ValueError("feedback does not correspond to an attempted query")
        if status not in NO_PROGRESS | TERMINAL_ERRORS | {"confirmed", "candidate_rejected"}:
            raise ValueError("unknown solver or confirmation feedback")
        row = {"query_id": plan.query_id, "suffix_length": len(plan.calls),
               "status": status, "actual_seconds": actual_seconds,
               "remaining_seconds": remaining_seconds}
        self.feedback.append(row)
        if status == "confirmed":
            self.confirmed = True
        if self.mode == "symbolic_adaptive" and len(plan.calls) == 1 and status in NO_PROGRESS:
            self.promoted = True

    def next_query(self, remaining_seconds: float) -> SuffixPlan | None:
        if remaining_seconds < 0:
            raise ValueError("negative remaining budget")
        if self.confirmed:
            reason = "confirmed_property_violation"
            pool: list[SuffixPlan] = []
        elif remaining_seconds < self.minimum_query_seconds + self.continuation_reserve_seconds:
            reason = "insufficient_budget_for_query_and_continuation"
            pool = []
        else:
            reason = "selected"
            if self.mode == "symbolic_one":
                pool = self.one
            elif self.mode == "symbolic_two":
                pool = self.two
            else:
                pool = self.two if self.promoted else self.one
            pool = [plan for plan in pool if plan.query_id not in self.attempted]
            if not pool and self.mode == "symbolic_adaptive" and not self.promoted:
                one_feedback = [item["status"] for item in self.feedback
                                if item["suffix_length"] == 1]
                if one_feedback and all(status in NO_PROGRESS | {"candidate_rejected"}
                                        for status in one_feedback):
                    self.promoted = True
                    pool = [plan for plan in self.two
                            if plan.query_id not in self.attempted]
                elif one_feedback:
                    reason = "one_call_exhausted_without_complete_no_progress"
            if not pool:
                if reason == "selected":
                    reason = "query_space_exhausted"
        selected = pool[0] if pool else None
        if selected is not None:
            self.attempted.add(selected.query_id)
        self.decisions.append({
            "ordinal": len(self.decisions), "mode": self.mode,
            "feedback_used": self.feedback[-1] if self.feedback else None,
            "promoted_to_two": self.promoted,
            "remaining_seconds": remaining_seconds,
            "required_reserve_seconds": self.continuation_reserve_seconds,
            "minimum_query_seconds": self.minimum_query_seconds,
            "query_id": selected.query_id if selected else None,
            "suffix_length": len(selected.calls) if selected else None,
            "reason": reason,
        })
        return selected
