"""Daily price-limit bands for the simulated fills.

The simulator refuses to buy at the limit-up price and to sell at the
limit-down price, because neither side has a counterparty there.  That check
needs the right band for the symbol, and the band depends on the board and on
whether the stock carries an ST designation -- not on the exchange suffix
alone.
"""

from __future__ import annotations

from typing import Any

from src.ai_os.numeric_policy import finite_or

MAIN_BOARD_LIMIT_PCT = 10.0
GROWTH_BOARD_LIMIT_PCT = 20.0
BEIJING_LIMIT_PCT = 30.0
ST_MAIN_BOARD_LIMIT_PCT = 5.0

# 创业板 and 科创板 both trade in a 20% band.
_TWENTY_PCT_PREFIXES = ("300", "301", "688", "689")
# 北交所 keeps a 30% band.
_BEIJING_PREFIXES = ("43", "83", "87", "88", "920")


def price_limit_pct(code: str, *, is_st: bool = False) -> float:
    """Return the daily price-limit band, in percent, for one symbol.

    ST widens nothing on 创业板/科创板 -- those boards keep their 20% band --
    but it halves the main board's 10% to 5%.
    """
    normalized = str(code or "").strip().upper()
    digits = normalized.split(".")[0]
    if digits.startswith(_TWENTY_PCT_PREFIXES):
        return GROWTH_BOARD_LIMIT_PCT
    if digits.startswith(_BEIJING_PREFIXES):
        return BEIJING_LIMIT_PCT
    return ST_MAIN_BOARD_LIMIT_PCT if is_st else MAIN_BOARD_LIMIT_PCT


def resolve_change_pct(
    decision: dict[str, Any], quote: dict[str, Any], trade_date: str
) -> float:
    """Return the session's change percent, or 0.0 when it cannot be established.

    Two things the previous `float(a or b or 0)` chain got wrong:

    * A genuine 0.0% session is a real value, but `or` treats it as missing and
      falls through to the stored daily bar.
    * That stored bar was read with `ORDER BY trade_date DESC LIMIT 1` and no
      date check, so it could be months old.  A stock that had been limit-down
      on that earlier date then had its stop-loss skipped silently.

    Only a value belonging to `trade_date` is accepted; anything else reports
    0.0, which means "no limit condition established" rather than "at a limit".
    """
    fresh = decision.get("market_change_pct")
    if fresh is not None and fresh != "":
        return finite_or(fresh, 0.0)

    quote_date = str(quote.get("trade_date") or quote.get("data_date") or "")[:10]
    if quote_date and quote_date == str(trade_date or "")[:10]:
        stored = quote.get("change_pct")
        if stored is not None and stored != "":
            return finite_or(stored, 0.0)
    return 0.0


def at_limit_up(change_pct: float, limit_pct: float, *, tolerance: float = 0.2) -> bool:
    """Whether the session is close enough to the upper limit to block a buy."""
    return float(change_pct) >= float(limit_pct) - tolerance


def at_limit_down(
    change_pct: float, limit_pct: float, *, tolerance: float = 0.2
) -> bool:
    """Whether the session is close enough to the lower limit to block a sell."""
    return float(change_pct) <= -float(limit_pct) + tolerance
