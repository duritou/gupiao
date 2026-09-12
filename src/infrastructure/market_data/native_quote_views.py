"""Quote-derived views shared by Adaptive's research and API paths.

These views are intentionally narrow: valuation is a quote snapshot, while
fund flow is an explicitly labelled active-buy/sell volume proxy.  Neither is
presented as a substitute for a full financial statement or broker flow feed.
"""

from __future__ import annotations

import math
from typing import Any


def _number(value: object, *, zero_is_missing: bool = True) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or (zero_is_missing and number == 0):
        return None
    return number


def quote_valuation_snapshot(quote: dict | None, provenance: object) -> dict | None:
    """Build a clearly scoped valuation view from an Adaptive quote."""
    if not isinstance(quote, dict):
        return None
    pe = _number(quote.get("pe") or quote.get("pe_ttm"))
    pb = _number(quote.get("pb"))
    market_cap = _number(
        quote.get("total_market_cap")
        or quote.get("market_cap")
        or quote.get("market_cap_yi"),
    )
    if market_cap is not None and market_cap < 10_000:
        market_cap *= 100_000_000
    if pe is None and pb is None and market_cap is None:
        return None

    data: dict[str, object] = {
        "name": quote.get("stock_name") or quote.get("name") or "",
        "code": quote.get("stock_code") or quote.get("code") or "",
        "price": _number(quote.get("price")),
        "change_pct": _number(quote.get("change_pct"), zero_is_missing=False),
        "pe": pe,
        "pb": pb,
        "market_cap": market_cap,
    }
    metadata = provenance.to_dict() if hasattr(provenance, "to_dict") else {}
    return {
        "data": {key: value for key, value in data.items() if value is not None},
        "_meta": {
            **metadata,
            "available": True,
            "source_layer": "adaptive_source_manager_quote",
            "valuation_scope": "quote_snapshot",
            "is_proxy": True,
            "warning": (
                "Quote snapshot valuation only; it is not a full "
                "financial-statement valuation."
            ),
        },
    }


def _active_trade_ratio(quote: dict) -> float | None:
    value = quote.get("active_volume_ratio")
    if value is None:
        try:
            outer = float(quote.get("outer_volume_lots") or 0)
            inner = float(quote.get("inner_volume_lots") or 0)
        except (TypeError, ValueError):
            return None
        total = outer + inner
        value = (outer - inner) / total if total > 0 else None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def quote_fundflow_proxy(
    quote: dict | None, provenance: object, normalized: str
) -> dict | None:
    """Build a labelled proxy from active buy/sell quote volumes."""
    if not isinstance(quote, dict):
        return None
    active_ratio = _active_trade_ratio(quote)
    if active_ratio is None:
        return None
    amount_wan = quote.get("amount_wan")
    if amount_wan is None and quote.get("amount") is not None:
        try:
            amount_wan = float(quote["amount"]) / 10_000
        except (TypeError, ValueError):
            amount_wan = None
    metadata = provenance.to_dict() if hasattr(provenance, "to_dict") else {}
    return {
        "data": {
            "name": quote.get("stock_name") or quote.get("name") or normalized,
            "price": quote.get("price"),
            "change_pct": quote.get("change_pct"),
            "main_net_pct": round(active_ratio * 100, 2),
            "outer_volume_lots": quote.get("outer_volume_lots"),
            "inner_volume_lots": quote.get("inner_volume_lots"),
            "amount_wan": amount_wan,
            "data_date": quote.get("data_date"),
            "proxy_type": "active_trade_ratio",
        },
        "_meta": {
            **metadata,
            "provider": metadata.get("provider") or "adaptive_source_manager",
            "available": True,
            "is_proxy": True,
            "source_layer": "adaptive_source_manager_quote",
            "warning": (
                "Main fund flow is unavailable; this is an active buy/sell "
                "volume difference proxy."
            ),
            "error": "",
        },
    }


async def get_native_valuation(code: str) -> dict[str, Any] | None:
    """Read one quote and return the native valuation snapshot, if usable."""
    from src.infrastructure.market_data.source_manager import source_manager

    try:
        quote, provenance = await source_manager.get_realtime_quote(code)
    except Exception:
        return None
    return quote_valuation_snapshot(quote, provenance)


async def get_native_fundflow(code: str) -> dict[str, Any] | None:
    """Read one quote and return the native fund-flow proxy, if usable."""
    from src.infrastructure.market_data.source_manager import source_manager

    try:
        quote, provenance = await source_manager.get_realtime_quote(code)
    except Exception:
        return None
    return quote_fundflow_proxy(quote, provenance, code)

