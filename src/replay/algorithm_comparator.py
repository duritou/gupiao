"""Offline comparison of two algorithms on identical frozen snapshots."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from math import sqrt
from statistics import stdev
from typing import Any

_DIRECTIONS = frozenset({"buy", "sell"})


def _direction(decision: Mapping[str, Any]) -> str:
    """Resolve an executable direction while preserving legacy decisions."""
    if decision.get("actionable") is False:
        return ""
    value = decision.get("executable_direction") or decision.get("direction")
    normalized = str(value or "").strip().lower()
    return normalized if normalized in _DIRECTIONS else ""


def _outcome(decision: Mapping[str, Any], outcomes: Mapping[str, Any]) -> float | None:
    code = str(decision.get("stock_code") or decision.get("code") or "").strip().upper()
    value = outcomes.get(code)
    if value is None:
        value = outcomes.get(str(decision.get("stock_code") or decision.get("code") or ""))
    if value is None:
        value = decision.get("forward_return_pct")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class ReplaySnapshot:
    """One point-in-time observation shared by baseline and candidate."""

    trade_date: str
    baseline: tuple[dict[str, Any], ...] = ()
    candidate: tuple[dict[str, Any], ...] = ()
    outcomes: Mapping[str, Any] = field(default_factory=dict)
    lookahead_safe: bool = False

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ReplaySnapshot:
        return cls(
            trade_date=str(payload.get("trade_date") or payload.get("date") or ""),
            baseline=tuple(payload.get("baseline") or ()),
            candidate=tuple(payload.get("candidate") or ()),
            outcomes=dict(payload.get("outcomes") or {}),
            lookahead_safe=bool(payload.get("lookahead_safe", False)),
        )


@dataclass(frozen=True, slots=True)
class AlgorithmMetrics:
    """Comparable metrics calculated without network or current-market state."""

    candidates: int = 0
    actionable_signals: int = 0
    evaluated_signals: int = 0
    correct_signals: int = 0
    accuracy: float | None = None
    average_return_pct: float | None = None
    average_return_ci95_pct: tuple[float, float] | None = None
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    coverage_pct: float = 0.0
    rejection_rate_pct: float = 0.0
    turnover_events: int = 0
    turnover_rate_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": self.candidates,
            "actionable_signals": self.actionable_signals,
            "evaluated_signals": self.evaluated_signals,
            "correct_signals": self.correct_signals,
            "accuracy": self.accuracy,
            "average_return_pct": self.average_return_pct,
            "average_return_ci95_pct": self.average_return_ci95_pct,
            "total_return_pct": self.total_return_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "coverage_pct": self.coverage_pct,
            "rejection_rate_pct": self.rejection_rate_pct,
            "turnover_events": self.turnover_events,
            "turnover_rate_pct": self.turnover_rate_pct,
        }


@dataclass(frozen=True, slots=True)
class AlgorithmComparison:
    """Result of comparing baseline and candidate on the same dates."""

    status: str
    snapshot_count: int
    date_from: str
    date_to: str
    lookahead_safe: bool
    metrics: dict[str, AlgorithmMetrics] = field(default_factory=dict)
    deltas: dict[str, float | None] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "snapshot_count": self.snapshot_count,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "lookahead_safe": self.lookahead_safe,
            "metrics": {
                name: metric.to_dict() for name, metric in self.metrics.items()
            },
            "deltas": self.deltas,
            "warnings": list(self.warnings),
            "data_source": "frozen_local_snapshots_only",
        }


def _max_drawdown(returns: list[float]) -> tuple[float, float]:
    equity = 1.0
    peak = equity
    for value in returns:
        equity *= 1.0 + value / 100.0
        peak = max(peak, equity)
    drawdown = min(
        ((equity / peak) - 1.0) * 100.0
        for equity in _equity_curve(returns)
    )
    return equity, abs(drawdown)


def _equity_curve(returns: list[float]) -> list[float]:
    curve = [1.0]
    for value in returns:
        curve.append(curve[-1] * (1.0 + value / 100.0))
    return curve


def _metrics(
    snapshots: Sequence[ReplaySnapshot], algorithm: str
) -> AlgorithmMetrics:
    candidates = 0
    actionable = 0
    evaluated = 0
    correct = 0
    signed_returns: list[float] = []
    selected_by_date: list[set[str]] = []
    for snapshot in snapshots:
        decisions = getattr(snapshot, algorithm)
        candidates += len(decisions)
        selected: set[str] = set()
        for decision in decisions:
            direction = _direction(decision)
            if not direction:
                continue
            actionable += 1
            code = str(
                decision.get("stock_code") or decision.get("code") or ""
            ).strip().upper()
            if code:
                selected.add(code)
            value = _outcome(decision, snapshot.outcomes)
            if value is None:
                continue
            evaluated += 1
            signed = value if direction == "buy" else -value
            signed_returns.append(signed)
            correct += signed > 0
        selected_by_date.append(selected)

    equity, max_drawdown = _max_drawdown(signed_returns)
    average_return = (
        sum(signed_returns) / len(signed_returns) if signed_returns else None
    )
    confidence_interval = None
    if average_return is not None and len(signed_returns) >= 2:
        margin = 1.96 * stdev(signed_returns) / sqrt(len(signed_returns))
        confidence_interval = (
            average_return - margin,
            average_return + margin,
        )
    turnover_events = 0
    previous: set[str] = set()
    for current in selected_by_date:
        turnover_events += len(previous.symmetric_difference(current))
        previous = current
    return AlgorithmMetrics(
        candidates=candidates,
        actionable_signals=actionable,
        evaluated_signals=evaluated,
        correct_signals=correct,
        accuracy=correct / evaluated if evaluated else None,
        average_return_pct=average_return,
        average_return_ci95_pct=confidence_interval,
        total_return_pct=(equity - 1.0) * 100.0,
        max_drawdown_pct=max_drawdown,
        coverage_pct=evaluated / actionable * 100.0 if actionable else 0.0,
        rejection_rate_pct=(candidates - actionable) / candidates * 100.0
        if candidates else 0.0,
        turnover_events=turnover_events,
        turnover_rate_pct=turnover_events / max(1, actionable) * 100.0,
    )


def compare_algorithms(
    snapshots: Sequence[ReplaySnapshot | Mapping[str, Any]],
) -> AlgorithmComparison:
    """Compare two algorithms without reading files, databases, or the network."""
    normalized = [
        item if isinstance(item, ReplaySnapshot) else ReplaySnapshot.from_mapping(item)
        for item in snapshots
    ]
    dates = [item.trade_date for item in normalized]
    warnings: list[str] = []
    if not normalized:
        return AlgorithmComparison(
            status="insufficient_snapshots",
            snapshot_count=0,
            date_from="",
            date_to="",
            lookahead_safe=False,
            warnings=("no_frozen_snapshots",),
        )
    if any(not value for value in dates) or len(set(dates)) != len(dates):
        return AlgorithmComparison(
            status="invalid_snapshots",
            snapshot_count=len(normalized),
            date_from=min(dates) if dates else "",
            date_to=max(dates) if dates else "",
            lookahead_safe=False,
            warnings=("trade_dates_must_be_present_and_unique",),
        )
    ordered = sorted(normalized, key=lambda item: item.trade_date)
    lookahead_safe = all(item.lookahead_safe for item in ordered)
    if not lookahead_safe:
        warnings.append("lookahead_safety_not_confirmed")
    metrics = {
        "baseline": _metrics(ordered, "baseline"),
        "candidate": _metrics(ordered, "candidate"),
    }
    deltas = {
        "accuracy": (
            metrics["candidate"].accuracy - metrics["baseline"].accuracy
            if metrics["candidate"].accuracy is not None
            and metrics["baseline"].accuracy is not None else None
        ),
        "average_return_pct": (
            metrics["candidate"].average_return_pct
            - metrics["baseline"].average_return_pct
            if metrics["candidate"].average_return_pct is not None
            and metrics["baseline"].average_return_pct is not None else None
        ),
        "total_return_pct": (
            metrics["candidate"].total_return_pct
            - metrics["baseline"].total_return_pct
        ),
        "max_drawdown_pct": (
            metrics["candidate"].max_drawdown_pct
            - metrics["baseline"].max_drawdown_pct
        ),
        "coverage_pct": (
            metrics["candidate"].coverage_pct - metrics["baseline"].coverage_pct
        ),
        "rejection_rate_pct": (
            metrics["candidate"].rejection_rate_pct
            - metrics["baseline"].rejection_rate_pct
        ),
        "turnover_rate_pct": (
            metrics["candidate"].turnover_rate_pct
            - metrics["baseline"].turnover_rate_pct
        ),
    }
    return AlgorithmComparison(
        status="ok" if lookahead_safe else "lookahead_unverified",
        snapshot_count=len(ordered),
        date_from=ordered[0].trade_date,
        date_to=ordered[-1].trade_date,
        lookahead_safe=lookahead_safe,
        metrics=metrics,
        deltas=deltas,
        warnings=tuple(warnings),
    )
