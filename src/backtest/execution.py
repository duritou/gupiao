"""Point-in-time A-share fill rules used by the research backtester."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FillAssessment:
    """Result of evaluating one order against one daily bar."""

    fill_price: float | None
    rejection_reason: str = ""

    @property
    def accepted(self) -> bool:
        return self.fill_price is not None


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _limit_ratio(stock_code: str, bar: dict) -> float:
    configured = _number(bar.get("price_limit_pct"))
    if configured is not None:
        return configured / 100 if configured > 1 else configured
    if _is_true(bar.get("is_st")):
        return 0.05
    digits = "".join(char for char in stock_code if char.isdigit())[-6:]
    if digits.startswith(("300", "301", "688")):
        return 0.20
    if digits.startswith(("4", "8", "92")):
        return 0.30
    return 0.10


def _is_one_price_bar(bar: dict, reference_price: float) -> bool:
    high = _number(bar.get("high") or bar.get("High"))
    low = _number(bar.get("low") or bar.get("Low"))
    return high is not None and low is not None and abs(high - low) <= reference_price * 1e-6


def assess_daily_open_fill(
    action: str,
    stock_code: str,
    bar: dict,
    previous_close: float | None,
    slippage_rate: float,
) -> FillAssessment:
    """Evaluate a next-session open fill without inventing missing liquidity."""

    if _is_true(bar.get("is_suspended")) or _is_true(bar.get("suspended")):
        return FillAssessment(None, "suspended")
    trade_status = str(bar.get("trade_status") or "").strip().lower()
    if trade_status in {"suspended", "halted", "stop", "停牌"}:
        return FillAssessment(None, "suspended")
    if "volume" in bar:
        try:
            if float(bar.get("volume") or 0) <= 0:
                return FillAssessment(None, "zero_volume")
        except (TypeError, ValueError):
            return FillAssessment(None, "invalid_volume")

    open_price = _number(bar.get("open") or bar.get("Open"))
    if open_price is None:
        open_price = _number(bar.get("close") or bar.get("Close"))
    if open_price is None:
        return FillAssessment(None, "missing_open_price")

    normalized_action = action.strip().upper()
    explicit_limit = _number(
        bar.get("limit_up") if normalized_action == "BUY" else bar.get("limit_down")
    )
    if explicit_limit is None and previous_close is not None and previous_close > 0:
        ratio = _limit_ratio(stock_code, bar)
        explicit_limit = previous_close * (
            1 + ratio if normalized_action == "BUY" else 1 - ratio
        )

    if explicit_limit is not None and _is_one_price_bar(bar, open_price):
        tolerance = max(0.01, explicit_limit * 0.001)
        if normalized_action == "BUY" and open_price >= explicit_limit - tolerance:
            return FillAssessment(None, "one_price_limit_up")
        if normalized_action == "SELL" and open_price <= explicit_limit + tolerance:
            return FillAssessment(None, "one_price_limit_down")

    rate = max(0.0, float(slippage_rate))
    multiplier = 1 + rate if normalized_action == "BUY" else 1 - rate
    # A-share prices are quoted to cents. Keeping extra fractional digits
    # would make the simulated fill impossible to reproduce in a real order.
    return FillAssessment(round(open_price * multiplier, 2))
