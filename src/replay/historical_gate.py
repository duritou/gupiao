"""Promotion gate for offline algorithm replay results."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.replay.algorithm_comparator import (
    ReplaySnapshot,
    compare_algorithms,
)


@dataclass(frozen=True, slots=True)
class HistoricalGateResult:
    """Fail-closed result for the minimum historical validation gate."""

    status: str
    required_days: int
    available_days: int
    lookahead_safe: bool
    historical_gate_passed: bool
    eligible_for_promotion: bool
    reasons: tuple[str, ...] = ()
    comparison: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "required_days": self.required_days,
            "available_days": self.available_days,
            "lookahead_safe": self.lookahead_safe,
            "historical_gate_passed": self.historical_gate_passed,
            "eligible_for_promotion": self.eligible_for_promotion,
            "reasons": list(self.reasons),
            "comparison": self.comparison,
            "data_source": "frozen_local_snapshots_only",
        }


def evaluate_historical_gate(
    snapshots: Sequence[ReplaySnapshot | Mapping[str, Any]],
    *,
    required_days: int = 20,
) -> HistoricalGateResult:
    """Evaluate minimum replay requirements without promoting an algorithm."""
    required = max(1, int(required_days))
    comparison = compare_algorithms(snapshots)
    available = comparison.snapshot_count
    reasons: list[str] = []
    if available < required:
        reasons.append("insufficient_complete_trading_days")
    if not comparison.lookahead_safe:
        reasons.append("lookahead_safety_not_confirmed")
    metrics = comparison.metrics
    baseline = metrics.get("baseline")
    candidate = metrics.get("candidate")
    if baseline and candidate:
        if candidate.total_return_pct < baseline.total_return_pct:
            reasons.append("candidate_total_return_worse_than_baseline")
        if candidate.max_drawdown_pct > baseline.max_drawdown_pct:
            reasons.append("candidate_drawdown_worse_than_baseline")
    if reasons:
        status = (
            "insufficient_history"
            if "insufficient_complete_trading_days" in reasons
            else "blocked"
        )
    else:
        status = "passed"
    return HistoricalGateResult(
        status=status,
        required_days=required,
        available_days=available,
        lookahead_safe=comparison.lookahead_safe,
        historical_gate_passed=status == "passed",
        # Five shadow-trading days are a separate required gate.
        eligible_for_promotion=False,
        reasons=tuple(dict.fromkeys(reasons)),
        comparison=comparison.to_dict(),
    )
