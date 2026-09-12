"""Small, auditable market-regime classifier.

The classifier borrows TickFlow's useful separation of breadth, speculation,
resilience and trend, but consumes only a point-in-time local snapshot. It is
diagnostic by default: callers may inspect the state before deciding whether a
strategy should apply a regime gate.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

REGIME_THRESHOLDS = {
    "strong": 70,
    "lean_strong": 55,
    "range": 45,
    "lean_weak": 30,
}


@dataclass(frozen=True)
class MarketRegime:
    """Point-in-time market environment result."""

    state: str
    score: int
    confidence: float
    as_of_date: str = ""
    components: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    source: str = "local_market_snapshot"
    lookahead_safe: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "score": self.score,
            "confidence": round(self.confidence, 3),
            "as_of_date": self.as_of_date,
            "components": {key: round(value, 2) for key, value in self.components.items()},
            "reasons": self.reasons,
            "source": self.source,
            "lookahead_safe": self.lookahead_safe,
        }


def _number(snapshot: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = snapshot.get(key)
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return None


def _clamp_score(value: float, low: float, high: float) -> float:
    if high <= low:
        return 50.0
    return max(0.0, min(100.0, (value - low) / (high - low) * 100.0))


def classify_market_regime(
    snapshot: Mapping[str, Any] | None,
    *,
    as_of_date: str = "",
    signal_date: str = "",
) -> MarketRegime:
    """Classify one EOD snapshot without fetching or filling missing fields.

    ``signal_date`` is optional. When supplied, a snapshot dated after the
    signal date is marked unsafe and does not silently become a valid regime.
    """
    data = snapshot or {}
    total = _number(data, "total", "covered_stocks", "total_count") or 0.0
    advancing = _number(data, "advancing", "up", "up_count")
    declining = _number(data, "declining", "down", "down_count")
    average_change = _number(data, "average_change_pct", "avg_pct", "average_change")
    limit_up = _number(data, "limit_up")
    limit_down = _number(data, "limit_down")
    snapshot_date = str(data.get("trade_date") or data.get("data_date") or as_of_date)
    lookahead_safe = not signal_date or not snapshot_date or snapshot_date <= signal_date

    if total <= 0 or advancing is None or declining is None:
        return MarketRegime(
            state="unknown",
            score=50,
            confidence=0.0,
            as_of_date=snapshot_date,
            reasons=["market breadth snapshot is unavailable"],
            lookahead_safe=lookahead_safe,
        )

    breadth_pct = max(0.0, min(100.0, advancing / total * 100.0))
    down_pct = max(0.0, min(100.0, declining / total * 100.0))
    avg_change = average_change or 0.0

    profit = (
        _clamp_score(breadth_pct, 21.0, 75.0) * 0.65
        + _clamp_score(avg_change, -1.2, 1.3) * 0.35
    )
    resilience = 100.0 - _clamp_score(down_pct, 25.0, 75.0)
    trend = _clamp_score(avg_change, -2.5, 2.5)

    components: dict[str, float] = {
        "profit": profit,
        "resilience": resilience,
        "trend": trend,
    }
    available_components = 3
    if limit_up is not None and limit_down is not None:
        speculation = _clamp_score(limit_up - limit_down, -20.0, 40.0)
        components["speculation"] = speculation
        available_components += 1
    else:
        components["speculation"] = 50.0

    score = round(
        components["profit"] * 0.35
        + components["speculation"] * 0.25
        + components["resilience"] * 0.20
        + components["trend"] * 0.20
    )
    if score >= REGIME_THRESHOLDS["strong"]:
        state = "strong"
    elif score >= REGIME_THRESHOLDS["lean_strong"]:
        state = "lean_strong"
    elif score >= REGIME_THRESHOLDS["range"]:
        state = "range"
    elif score >= REGIME_THRESHOLDS["lean_weak"]:
        state = "lean_weak"
    else:
        state = "weak"

    reasons: list[str] = []
    if breadth_pct >= 60:
        reasons.append("上涨家数占比偏高")
    elif breadth_pct <= 40:
        reasons.append("下跌家数占比偏高")
    if avg_change >= 0.5:
        reasons.append("平均涨跌幅支持趋势")
    elif avg_change <= -0.5:
        reasons.append("平均涨跌幅转弱")
    if limit_up is not None and limit_down is not None:
        if limit_up > limit_down:
            reasons.append("涨停参与度高于跌停")
        elif limit_down > limit_up:
            reasons.append("跌停参与度高于涨停")
    if not reasons:
        reasons.append("宽度与趋势信号接近中性")
    if not lookahead_safe:
        reasons.append("snapshot date is after signal date")

    coverage_confidence = min(1.0, total / 500.0)
    field_confidence = available_components / 4.0
    confidence = round(coverage_confidence * 0.6 + field_confidence * 0.4, 3)
    return MarketRegime(
        state=state,
        score=max(0, min(100, score)),
        confidence=confidence,
        as_of_date=snapshot_date,
        components=components,
        reasons=reasons,
        lookahead_safe=lookahead_safe,
    )


__all__ = ["MarketRegime", "REGIME_THRESHOLDS", "classify_market_regime"]
