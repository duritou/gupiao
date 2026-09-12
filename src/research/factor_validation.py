"""Point-in-time factor diagnostics.

The validator consumes already materialized observations, so it never fetches
data or silently changes the decision universe. Each row must contain
``date``, ``symbol``, ``factor`` and ``forward_return``; ``horizon`` defaults
to one session. This keeps IC/IR checks usable from replay, notebooks and
future API routes without coupling them to pandas or a data provider.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import mean, stdev
from typing import Any, Iterable


@dataclass(frozen=True)
class FactorValidationResult:
    """Aggregated cross-sectional diagnostics for one factor/horizon."""

    factor_name: str
    horizon: int
    observation_count: int
    date_count: int
    mean_ic: float
    ic_std: float
    information_ratio: float
    hit_rate: float
    top_bottom_spread: float
    usable: bool
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RollingValidation:
    """Walk-forward result for one out-of-sample validation window."""

    start_date: str
    end_date: str
    result: FactorValidationResult


@dataclass(frozen=True)
class FactorValidationReport:
    """Multi-horizon validation with relative IC/spread decay."""

    factor_name: str
    by_horizon: dict[int, FactorValidationResult]
    ic_decay: dict[int, float]
    spread_decay: dict[int, float]


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _rank(values: list[float]) -> list[float]:
    """Average-rank ties, returning ranks in the original order."""
    ordered = sorted(enumerate(values), key=lambda pair: pair[1])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and ordered[end][1] == ordered[cursor][1]:
            end += 1
        average = (cursor + end - 1) / 2.0 + 1.0
        for index in range(cursor, end):
            ranks[ordered[index][0]] = average
        cursor = end
    return ranks


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 3:
        return None
    left_mean = mean(left)
    right_mean = mean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_ss = sum((a - left_mean) ** 2 for a in left)
    right_ss = sum((b - right_mean) ** 2 for b in right)
    denominator = math.sqrt(left_ss * right_ss)
    return numerator / denominator if denominator > 0 else None


def _group_observations(
    observations: Iterable[dict[str, Any]], horizon: int
) -> dict[str, list[tuple[float, float]]]:
    grouped: dict[str, dict[str, tuple[float, float]]] = {}
    for row in observations:
        row_horizon = row.get("horizon", 1)
        try:
            if int(row_horizon) != horizon:
                continue
        except (TypeError, ValueError):
            continue
        date = str(row.get("date") or "").strip()
        symbol = str(row.get("symbol") or "").strip()
        factor = _as_float(row.get("factor"))
        forward_return = _as_float(row.get("forward_return"))
        if not date or not symbol or factor is None or forward_return is None:
            continue
        grouped.setdefault(date, {})[symbol] = (factor, forward_return)
    return {date: list(symbols.values()) for date, symbols in grouped.items()}


def validate_factor(
    observations: Iterable[dict[str, Any]],
    factor_name: str = "factor",
    horizon: int = 1,
    min_names_per_date: int = 3,
    quantiles: int = 5,
) -> FactorValidationResult:
    """Compute daily Spearman IC, IC-IR and top/bottom spread.

    ``observations`` are expected to be formed using a forward return that is
    strictly after the signal date. The function deliberately does not infer
    or repair dates, making an accidental look-ahead visible to its caller.
    """
    if horizon < 1:
        raise ValueError("horizon must be positive")
    if min_names_per_date < 3:
        raise ValueError("min_names_per_date must be at least 3")
    if quantiles < 2:
        raise ValueError("quantiles must be at least 2")

    grouped = _group_observations(observations, horizon)
    daily_ics: list[float] = []
    spreads: list[float] = []
    usable_count = 0
    for pairs in grouped.values():
        if len(pairs) < min_names_per_date:
            continue
        factors = [pair[0] for pair in pairs]
        returns = [pair[1] for pair in pairs]
        ic = _pearson(_rank(factors), _rank(returns))
        if ic is None:
            continue
        daily_ics.append(ic)
        order = sorted(range(len(factors)), key=lambda index: factors[index])
        bucket_size = max(1, len(order) // quantiles)
        bottom = order[:bucket_size]
        top = order[-bucket_size:]
        spreads.append(
            mean(returns[index] for index in top)
            - mean(returns[index] for index in bottom)
        )
        usable_count += len(pairs)

    warnings: list[str] = []
    if not daily_ics:
        warnings.append("insufficient cross-sectional observations")
        return FactorValidationResult(
            factor_name=factor_name,
            horizon=horizon,
            observation_count=0,
            date_count=0,
            mean_ic=0.0,
            ic_std=0.0,
            information_ratio=0.0,
            hit_rate=0.0,
            top_bottom_spread=0.0,
            usable=False,
            warnings=warnings,
        )

    ic_std = stdev(daily_ics) if len(daily_ics) > 1 else 0.0
    ir = mean(daily_ics) / ic_std if ic_std > 1e-12 else 0.0
    hit_rate = sum(ic > 0 for ic in daily_ics) / len(daily_ics)
    if len(daily_ics) < 5:
        warnings.append("fewer than five independent dates")
    if abs(mean(daily_ics)) < 0.02:
        warnings.append("mean IC is economically weak")
    return FactorValidationResult(
        factor_name=factor_name,
        horizon=horizon,
        observation_count=usable_count,
        date_count=len(daily_ics),
        mean_ic=round(mean(daily_ics), 6),
        ic_std=round(ic_std, 6),
        information_ratio=round(ir, 6),
        hit_rate=round(hit_rate, 6),
        top_bottom_spread=round(mean(spreads), 6),
        usable=True,
        warnings=warnings,
    )


def neutralize_factor(
    observations: Iterable[dict[str, Any]], group_key: str = "industry"
) -> list[dict[str, Any]]:
    """Remove same-date group means while preserving the original observations.

    This is a deliberately small sector-neutralization primitive. It uses only
    fields present in the supplied snapshot, so it cannot accidentally look up
    a later industry classification during replay.
    """
    rows = [dict(row) for row in observations]
    grouped: dict[tuple[str, str], list[tuple[int, float]]] = {}
    for index, row in enumerate(rows):
        date = str(row.get("date") or "")
        group = str(row.get(group_key) or "__missing__")
        factor = _as_float(row.get("factor"))
        if date and factor is not None:
            grouped.setdefault((date, group), []).append((index, factor))
    for members in grouped.values():
        group_mean = mean(value for _, value in members)
        for index, value in members:
            rows[index]["factor"] = value - group_mean
    return rows


def validate_factor_horizons(
    observations: Iterable[dict[str, Any]],
    factor_name: str = "factor",
    horizons: Iterable[int] = (1, 5, 20),
) -> FactorValidationReport:
    """Validate several forward-return horizons and report relative decay."""
    rows = list(observations)
    selected = tuple(dict.fromkeys(int(horizon) for horizon in horizons))
    if not selected or any(horizon < 1 for horizon in selected):
        raise ValueError("horizons must contain positive integers")
    by_horizon = {
        horizon: validate_factor(rows, factor_name=factor_name, horizon=horizon)
        for horizon in selected
    }
    baseline_horizon = next(
        (horizon for horizon in selected if by_horizon[horizon].usable), selected[0]
    )
    baseline_ic = abs(by_horizon[baseline_horizon].mean_ic)
    baseline_spread = abs(by_horizon[baseline_horizon].top_bottom_spread)
    ic_decay = {
        horizon: round(
            result.mean_ic / baseline_ic if baseline_ic > 1e-12 else 0.0, 6
        )
        for horizon, result in by_horizon.items()
    }
    spread_decay = {
        horizon: round(
            result.top_bottom_spread / baseline_spread if baseline_spread > 1e-12 else 0.0,
            6,
        )
        for horizon, result in by_horizon.items()
    }
    return FactorValidationReport(factor_name, by_horizon, ic_decay, spread_decay)


def validate_factor_rolling(
    observations: Iterable[dict[str, Any]],
    factor_name: str = "factor",
    horizon: int = 1,
    train_dates: int = 60,
    test_dates: int = 20,
) -> list[RollingValidation]:
    """Run expanding walk-forward diagnostics on chronological date blocks."""
    if train_dates < 1 or test_dates < 1:
        raise ValueError("train_dates and test_dates must be positive")
    rows = list(observations)
    dates = sorted({str(row.get("date") or "") for row in rows if row.get("date")})
    windows: list[RollingValidation] = []
    start = train_dates
    while start < len(dates):
        end = min(start + test_dates, len(dates))
        test_set = set(dates[start:end])
        result = validate_factor(
            [row for row in rows if str(row.get("date")) in test_set],
            factor_name=factor_name,
            horizon=horizon,
        )
        windows.append(RollingValidation(dates[start], dates[end - 1], result))
        start = end
    return windows
