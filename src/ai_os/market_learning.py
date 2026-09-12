"""Conservative scoring feedback from verified daily market observations."""

from __future__ import annotations

from typing import Any


HORIZON_WEIGHTS = {1: 0.25, 5: 0.50, 20: 0.25}
HORIZON_MIN_OBSERVATIONS = {1: 2, 5: 20, 20: 40}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def learning_adjustment(profile: dict, stock_code: str, sources: list[str]) -> dict:
    """Return a bounded score adjustment and its auditable evidence.

    A symbol needs two decisive next-session observations before affecting its
    score.  A discovery source needs three.  One-off outcomes remain evidence,
    not a learned rule.
    """
    symbol_stats = (profile.get("by_symbol") or {}).get(stock_code) or {}
    symbol_adjustment = 0.0
    observations = float(symbol_stats.get("observations", 0) or 0)
    if observations >= 2:
        edge = float(symbol_stats.get("correct", 0) or 0) - float(
            symbol_stats.get("incorrect", 0) or 0
        )
        # Two observations are only an early hint.  Do not let a tiny sample
        # lift a technical score into the apparent BUY range.
        sample_cap = 2.0 if observations < 3 else 4.0 if observations < 5 else 8.0
        symbol_adjustment = _clamp(edge / observations * sample_cap, -sample_cap, sample_cap)

    source_stats: dict[str, dict] = {}
    source_votes: list[float] = []
    for source in dict.fromkeys(sources):
        stats = (profile.get("by_source") or {}).get(source) or {}
        source_stats[source] = stats
        if float(stats.get("observations", 0) or 0) < 3:
            continue
        win_rate = float(stats.get("win_rate", 0))
        if win_rate >= 2 / 3:
            source_votes.append(3.0)
        elif win_rate <= 1 / 3:
            source_votes.append(-3.0)
        else:
            source_votes.append(0.0)
    source_adjustment = sum(source_votes) / len(source_votes) if source_votes else 0.0
    total = _clamp(symbol_adjustment + source_adjustment, -11.0, 11.0)
    return {
        "score_adjustment": round(total, 2),
        "symbol_adjustment": round(symbol_adjustment, 2),
        "source_adjustment": round(source_adjustment, 2),
        "symbol_stats": symbol_stats,
        "source_stats": source_stats,
        "horizon_days": profile.get("horizon_days", 1),
        "policy": "symbol>=2 early cap2; symbol>=3 cap4; symbol>=5 cap8; source>=3 cap3; decisive BUY/SELL only",
    }


def multi_horizon_learning_adjustment(
    profiles: dict[int, dict[str, Any]],
    stock_code: str,
    sources: list[str],
) -> dict[str, Any]:
    """Combine mature horizon profiles without letting sparse horizons steer scores."""
    contributions: dict[str, dict[str, Any]] = {}
    eligible: list[tuple[int, float, dict[str, Any]]] = []
    for horizon, weight in HORIZON_WEIGHTS.items():
        profile = profiles.get(horizon) or {"horizon_days": horizon}
        total = int(profile.get("decisive_observations", 0) or 0)
        if total < HORIZON_MIN_OBSERVATIONS[horizon]:
            contributions[str(horizon)] = {
                "available": False,
                "reason": "insufficient_observations",
                "decisive_observations": total,
            }
            continue
        result = learning_adjustment(profile, stock_code, sources)
        eligible.append((horizon, weight, result))
        contributions[str(horizon)] = {
            "available": True,
            "weight": weight,
            **result,
        }

    if not eligible:
        fallback = learning_adjustment(
            profiles.get(1) or {"horizon_days": 1}, stock_code, sources
        )
        return {
            **fallback,
            "horizon_days": 1,
            "active_horizons": [],
            "horizon_contributions": contributions,
            "policy": "multi-horizon; fallback to 1d until a configured horizon matures",
        }

    total_weight = sum(weight for _, weight, _ in eligible)
    combined = sum(
        weight * float(result.get("score_adjustment", 0) or 0)
        for _, weight, result in eligible
    ) / total_weight
    return {
        "score_adjustment": round(_clamp(combined, -11.0, 11.0), 2),
        "symbol_adjustment": round(
            sum(weight * float(result.get("symbol_adjustment", 0) or 0)
                for _, weight, result in eligible) / total_weight,
            2,
        ),
        "source_adjustment": round(
            sum(weight * float(result.get("source_adjustment", 0) or 0)
                for _, weight, result in eligible) / total_weight,
            2,
        ),
        "horizon_days": "multi",
        "active_horizons": [horizon for horizon, _, _ in eligible],
        "horizon_contributions": contributions,
        "policy": "1d=25%; 5d=50%; 20d=25%; horizon activates only after minimum decisive observations",
    }
