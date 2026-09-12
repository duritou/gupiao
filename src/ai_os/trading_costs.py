"""Paper-trading cost policy for A-share simulations."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

COMMISSION_RATE = Decimal("0.0005")
STAMP_TAX_RATE = Decimal("0.0005")
PRICE_TICK_SIZE = Decimal("0.01")
FEE_POLICY = "commission_0.0005_both_sides_stamp_0.0005_sell"


def _to_cent(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def quantize_price(price: float, tick_size: Decimal = PRICE_TICK_SIZE) -> float:
    """Round a simulated fill to the exchange price tick."""
    return float(Decimal(str(max(0.0, float(price)))).quantize(
        tick_size, rounding=ROUND_HALF_UP
    ))


def calculate_trade_costs(
    value: float,
    action: str,
    *,
    commission_rate: Decimal | float = COMMISSION_RATE,
    stamp_tax_rate: Decimal | float = STAMP_TAX_RATE,
) -> dict[str, float]:
    """Return cent-rounded commission, stamp tax, and total fees.

    Commission is 0.05% on both sides. Stamp tax is 0.05% on SELL only.
    No broker minimum commission is assumed because the configured policy is
    an exact rate rather than a rate-plus-minimum schedule.
    """
    gross = Decimal(str(max(0.0, float(value))))
    commission = _to_cent(gross * Decimal(str(commission_rate)))
    stamp_tax = (
        _to_cent(gross * Decimal(str(stamp_tax_rate)))
        if str(action).upper() == "SELL"
        else Decimal("0.00")
    )
    return {
        "commission": float(commission),
        "stamp_tax": float(stamp_tax),
        "total_fees": float(commission + stamp_tax),
    }
