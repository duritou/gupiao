"""估值数据路由 - 提供股票估值指标（PE/PB/PS/市值等）。"""

import math

from fastapi import APIRouter

from config.settings import settings
from src.infrastructure.market_data.hithink_provider import hithink_provider
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


def _hithink_valuation_view(payload: object, requested_code: str) -> dict | None:
    """Map one HiThink valuation row into the route's stable response shape."""
    rows = getattr(payload, "data", None)
    if not isinstance(rows, list) or not rows:
        return None
    row = rows[0]
    if not isinstance(row, dict):
        return None
    data = {
        "name": row.get("name") or "",
        "code": row.get("thscode") or requested_code,
        "pe": row.get("pe_ttm"),
        "pb": row.get("pb_mrq"),
        "ps": row.get("ps_ttm"),
        "pcf": row.get("pcf_ttm"),
    }
    return {
        "data": data,
        "_meta": {
            "provider": "hithink",
            "source_name": "同花顺金融数据服务",
            "source_layer": "hithink_rest",
            "endpoint": getattr(payload, "endpoint", ""),
            "request_id": getattr(payload, "request_id", ""),
            "fetched_at": getattr(payload, "fetched_at", ""),
            "data_date": getattr(payload, "data_date", ""),
            "is_live": False,
            "is_cached": False,
            "available": True,
            "valuation_scope": "hithink_snapshot",
            "is_proxy": False,
            "warning": "HiThink 提供固定估值快照字段；缺失值保留为 null",
        },
    }


async def _try_hithink_valuation(code: str) -> dict | None:
    """Fetch HiThink only when the capability is enabled and configured."""
    if not hithink_provider.configured:
        return None
    payload = await hithink_provider.fetch_valuation_snapshot(code)
    return _hithink_valuation_view(payload, code)


@router.get("/valuation")
async def get_valuation(code: str):
    """获取指定股票的估值数据。

    Args:
        code: 股票代码（如 "000001"）

    Returns:
        dict: 估值数据，包含PE、PB、PS、市值等指标
    """
    normalized_code = code.strip().upper()
    mode = settings.HITHINK_VALUATION_MODE
    hithink_error = ""
    if mode in {"primary", "shadow", "validator"}:
        try:
            hithink_view = await _try_hithink_valuation(normalized_code)
            if mode == "primary" and hithink_view is not None:
                return hithink_view
        except Exception as exc:
            hithink_error = getattr(exc, "category", type(exc).__name__)

    provenance = None
    try:
        quote, provenance = await source_manager.get_eod_quote(
            normalized_code
        )
        tushare_view = _native_quote_valuation(quote, provenance)
        if tushare_view is not None:
            if provenance.provider == "tushare":
                tushare_view["_meta"]["provider"] = "tushare"
                tushare_view["_meta"]["source_layer"] = "adaptive_tushare"
                tushare_view["_meta"]["is_proxy"] = False
            if hithink_error:
                tushare_view["_meta"]["hithink_fallback_reason"] = hithink_error
            return tushare_view
    except Exception:
        pass
    if mode == "fallback":
        try:
            hithink_view = await _try_hithink_valuation(normalized_code)
            if hithink_view is not None:
                return hithink_view
        except Exception:
            pass
    if provenance is not None and provenance.provider == "tushare":
        try:
            native = await get_native_valuation(code)
            if native is not None:
                return native
        except Exception:
            pass
    # The compatibility source remains the last resort for this page.
    provider = get_vibe_provider()
    return await provider.get_valuation(code)
