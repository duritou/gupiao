"""估值数据路由 - 提供股票估值指标（PE/PB/PS/市值等）。"""

import math

from fastapi import APIRouter

from src.infrastructure.market_data.native_quote_views import get_native_valuation
from src.infrastructure.market_data.source_manager import source_manager  # noqa: F401
from src.infrastructure.market_data.vibe_provider import get_vibe_provider

router = APIRouter(tags=["valuation"])


def _number(value: object, *, zero_is_missing: bool = True) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or (zero_is_missing and number == 0):
        return None
    return number


def _native_quote_valuation(quote: dict | None, provenance: object) -> dict | None:
    """Build a clearly scoped valuation view from Adaptive's own quote layer."""
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
    data = {key: value for key, value in data.items() if value is not None}
    metadata = provenance.to_dict() if hasattr(provenance, "to_dict") else {}
    return {
        "data": data,
        "_meta": {
            **metadata,
            "available": True,
            "source_layer": "adaptive_source_manager_quote",
            "valuation_scope": "quote_snapshot",
            "is_proxy": True,
            "warning": "仅含行情快照估值字段，不等同于完整财报估值",
        },
    }


@router.get("/valuation")
async def get_valuation(code: str):
    """获取指定股票的估值数据。

    Args:
        code: 股票代码（如 "000001"）

    Returns:
        dict: 估值数据，包含PE、PB、PS、市值等指标
    """
    try:
        quote, provenance = await source_manager.get_eod_quote(
            code.strip().upper()
        )
        tushare_view = _native_quote_valuation(quote, provenance)
        if tushare_view is not None:
            if provenance.provider == "tushare":
                tushare_view["_meta"]["provider"] = "tushare"
                tushare_view["_meta"]["source_layer"] = "adaptive_tushare"
                tushare_view["_meta"]["is_proxy"] = False
            return tushare_view
    except Exception:
        pass
    if provenance.provider == "tushare":
        try:
            native = await get_native_valuation(code)
            if native is not None:
                return native
        except Exception:
            pass
    # The compatibility source remains the last resort for this page.
    provider = get_vibe_provider()
    return await provider.get_valuation(code)
