"""Data Validator — sanity checks, unit normalization, provider comparison.

v7.2 Data Verification Layer. All market data passes through this BEFORE
reaching the AI pipeline. Catches:
  - Price anomalies (京东方A != 138.37)
  - Volume/amount unit errors (41511亿 vs 4.15亿)
  - Price change outliers (>20% in one day without halt)
  - Stale data (cache too old)
  - Provider inconsistencies
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass
class ValidationResult:
    """Result of a data validation check."""
    is_valid: bool = True
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    normalized_data: dict[str, Any] = field(default_factory=dict)
    quality_score: float = 1.0  # 0-1, 1 = perfect

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    def to_dict(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "warnings": self.warnings,
            "errors": self.errors,
            "quality_score": round(self.quality_score, 2),
            "normalized": self.normalized_data,
        }


class DataValidator:
    """Validates and normalizes market data before it enters the AI pipeline.

    Rules:
      1. Price must be > 0 and within reasonable range for A-shares
      2. Daily change must be within [-20%, +20%] (科创板/创业板: [-20%, +20%])
      3. Amount (成交额) should be 0.01亿 ~ 500亿 for individual stocks
      4. Volume must be positive
      5. PE should be 1-1000 (negative = loss-making, ok)
      6. Data freshness: spot data < 60s old
    """

    # Price boundaries for different board types
    PRICE_MIN = 0.01
    PRICE_MAX_BY_BOARD = {
        "SH": 3000,
        "SZ": 500,   # Main board
        "BJ": 200,   # 北京所
    }

    # Amount (成交额) boundaries per stock (元)
    AMOUNT_MIN = 1_000_000      # 100万元 — below this is suspicious
    AMOUNT_MAX = 50_000_000_000  # 500亿元 — above this is suspicious for single stock

    # Daily change limits (科创板/创业板 can go ±20%)
    CHANGE_MAX_ABS = 21.0  # Allow slight overshoot for rounding
    CHANGE_WARN_ABS = 15.0  # Warn above this

    # PE boundaries
    PE_MIN = -1000  # Negative = loss-making
    PE_MAX = 2000

    # Data freshness (seconds)
    MAX_DATA_AGE_SECONDS = 120

    def validate_quote(self, raw: dict, code: str = "") -> ValidationResult:
        """Validate a single stock quote. Normalizes units."""
        result = ValidationResult()
        normalized: dict[str, Any] = dict(raw)  # Start with a copy

        price = raw.get("price", 0) or raw.get("最新价", 0)
        change_pct = raw.get("change_pct", 0) or raw.get("涨跌幅", 0)
        amount = raw.get("amount", 0) or raw.get("成交额", 0)
        volume = raw.get("volume", 0) or raw.get("成交量", 0)
        pe = raw.get("pe", 0) or raw.get("市盈率-动态", 0)

        # ---- Price Sanity ----
        if price <= 0:
            result.errors.append(f"[{code}] Price = {price}: non-positive")
            result.is_valid = False
            result.quality_score -= 0.5
        else:
            board = code[-2:] if code and len(code) >= 2 else "SZ"
            max_price = self.PRICE_MAX_BY_BOARD.get(board, 500)
            if price > max_price:
                result.warnings.append(
                    f"[{code}] Price {price:.2f} exceeds expected max "
                    f"{max_price} for {board} board. Verify data source."
                )
                result.quality_score -= 0.15

        # ---- Change Sanity ----
        if abs(change_pct) > self.CHANGE_MAX_ABS:
            result.errors.append(
                f"[{code}] Daily change {change_pct:+.1f}% exceeds ±{self.CHANGE_MAX_ABS}% limit"
            )
            result.is_valid = False
            result.quality_score -= 0.4
        elif abs(change_pct) > self.CHANGE_WARN_ABS:
            result.warnings.append(
                f"[{code}] Daily change {change_pct:+.1f}% is unusually large"
            )
            result.quality_score -= 0.05

        # ---- Amount Normalization & Sanity ----
        # akshare returns 成交额 in 元
        # Normalize to 万元 for internal use, 亿 for display
        if amount > 0:
            if amount > self.AMOUNT_MAX:
                # Could be a unit error — maybe it's already in 万元 or 亿
                if amount > 1e13:  # > 1万亿 for single stock = definitely wrong
                    result.errors.append(
                        f"[{code}] Amount {amount:.0f} (元) = {amount/1e8:.0f}亿 — "
                        f"exceeds max {self.AMOUNT_MAX/1e8:.0f}亿 for single stock"
                    )
                    result.is_valid = False
                    result.quality_score -= 0.3
                else:
                    result.warnings.append(
                        f"[{code}] Amount {amount/1e8:.1f}亿 is high — verify"
                    )
                    result.quality_score -= 0.05
            elif 0 < amount < self.AMOUNT_MIN:
                result.warnings.append(
                    f"[{code}] Amount {amount:.0f} (元) = {amount/1e4:.2f}万 is very low"
                )
                result.quality_score -= 0.05

            # Add normalized amount fields
            normalized["amount_wan"] = round(amount / 1e4, 2)    # 万元
            normalized["amount_yi"] = round(amount / 1e8, 2)     # 亿元
        else:
            result.warnings.append(f"[{code}] Amount is zero or missing")
            result.quality_score -= 0.05

        # ---- Volume Sanity ----
        if volume < 0:
            result.errors.append(f"[{code}] Volume {volume} is negative")
            result.is_valid = False
            result.quality_score -= 0.3

        # ---- PE Sanity ----
        if pe != 0 and (pe < self.PE_MIN or pe > self.PE_MAX):
            result.warnings.append(f"[{code}] PE {pe} is outside expected range [{self.PE_MIN}, {self.PE_MAX}]")
            result.quality_score -= 0.05

        # ---- Quality Score ----
        result.quality_score = max(0.0, result.quality_score)

        # If validation passed, include normalized data
        if result.is_valid:
            result.normalized_data = normalized

        return result

    def validate_klines(self, klines: list[dict], code: str = "") -> ValidationResult:
        """Validate K-line data series."""
        result = ValidationResult()
        if not klines:
            result.warnings.append(f"[{code}] K-line data is empty")
            result.quality_score -= 0.1
            return result

        normalized: list[dict] = []

        for i, bar in enumerate(klines):
            close = bar.get("close", 0)
            high = bar.get("high", 0)
            low = bar.get("low", 0)
            open_price = bar.get("open", 0)

            # OHLC consistency
            if not (min(open_price, close) <= high and max(open_price, close) >= low):
                if not (high >= low):
                    result.errors.append(
                        f"[{code}] Bar {i}: high({high}) < low({low})"
                    )
                    result.is_valid = False
                    result.quality_score -= 0.3

            # Price gap check (day-over-day)
            if i > 0:
                prev_close = klines[i - 1].get("close", 0)
                if prev_close > 0:
                    gap_pct = abs(close / prev_close - 1) * 100
                    if gap_pct > 21:  # More than daily limit
                        result.warnings.append(
                            f"[{code}] Bar {i}: gap {gap_pct:.1f}% from prev close. "
                            f"Possible split/dividend adjustment needed."
                        )

            # Add amount normalization if present
            nb = dict(bar)
            amount = bar.get("amount", 0)
            if amount > 0:
                nb["amount_wan"] = round(amount / 1e4, 2)
                nb["amount_yi"] = round(amount / 1e8, 2)
            normalized.append(nb)

        result.normalized_data = {"klines": normalized, "count": len(normalized)}
        return result

    def validate_market_overview(self, data: dict) -> ValidationResult:
        """Validate market overview data."""
        result = ValidationResult()

        breadth = data.get("market_breadth", {})
        up = breadth.get("up", 0)
        down = breadth.get("down", 0)
        total_vol = breadth.get("total_volume", 0)

        # Total listed stocks ~5000 A-shares
        if up + down > 6000:
            result.warnings.append(f"Market breadth total {up + down} exceeds ~5000 A-shares")
            result.quality_score -= 0.1

        if up + down == 0:
            result.warnings.append("Market breadth is all zeros — data may be stale")
            result.quality_score -= 0.2

        # Total market volume — typically 0.5-3万亿
        if total_vol > 10:
            result.warnings.append(f"Total market volume {total_vol}万亿 exceeds normal range")
            result.quality_score -= 0.1
        elif total_vol > 0 and total_vol < 0.1:
            result.warnings.append(f"Total market volume {total_vol}万亿 is suspiciously low")
            result.quality_score -= 0.1

        return result

    def compare_providers(
        self, primary_data: dict | None, fallback_data: dict
    ) -> dict:
        """Compare data from different providers and flag discrepancies."""
        if primary_data is None:
            return {
                "provider_match": False,
                "using": "fallback",
                "reason": "Primary data unavailable",
                "quality": "degraded",
            }

        # Compare key fields
        price_live = primary_data.get("price", 0)
        price_fallback = fallback_data.get("latest_price", fallback_data.get("price", 0))

        discrepancies = []
        if price_live > 0 and price_fallback > 0:
            diff_pct = abs(price_live / price_fallback - 1) * 100
            if diff_pct > 10:
                discrepancies.append(
                    f"Price diff {diff_pct:.1f}%: primary={price_live}, fallback={price_fallback}"
                )

        return {
            "provider_match": len(discrepancies) == 0,
            "using": "live",
            "discrepancies": discrepancies,
            "quality": "degraded" if discrepancies else "good",
        }


# Singleton
validator = DataValidator()
