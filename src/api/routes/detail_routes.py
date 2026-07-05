"""Stock detail routes — v7.4: real data with proven provenance."""

from fastapi import APIRouter, Query

from src.infrastructure.market_data.source_manager import source_manager

router = APIRouter(tags=["detail"], prefix="/detail")


@router.get("/{code}")
async def get_stock_detail(code: str, include: str = Query("all")):
    """Get stock detail with explicit data provenance.

    If live data is unavailable, returns an error — never mock data.
    """
    result: dict = {"stock_code": code}

    # 1. Get real-time quote (with provenance)
    quote, quote_prov = await source_manager.get_realtime_quote(code)

    if quote is not None:
        result["stock_name"] = quote.get("stock_name", code)
        result["latest_price"] = quote["price"]
        result["price_change_pct"] = quote["change_pct"]
        result["open"] = quote.get("open", 0)
        result["high"] = quote.get("high", 0)
        result["low"] = quote.get("low", 0)
        result["pre_close"] = quote.get("pre_close", 0)
        result["volume"] = quote.get("volume", 0)
        result["amount_yi"] = quote.get("amount_yi", 0)
        result["turnover"] = quote.get("turnover", 0)
        result["pe"] = quote.get("pe", 0)
        result["total_market_cap"] = quote.get("total_market_cap", 0)
    else:
        result["stock_name"] = code
        result["data_error"] = quote_prov.error_message

    # 2. Get K-line data (with provenance)
    klines, kline_prov = await source_manager.get_kline(code, count=250)
    if klines is not None:
        result["klines"] = klines
        # Compute basic indicators from real data
        if len(klines) >= 20:
            closes = [k["close"] for k in klines]
            ma5 = sum(closes[-5:]) / 5
            ma10 = sum(closes[-10:]) / 10
            ma20 = sum(closes[-20:]) / 20
            result["indicators"] = {
                "ma5": round(ma5, 2),
                "ma10": round(ma10, 2),
                "ma20": round(ma20, 2),
                "data_points": len(klines),
            }

    # 3. Data provenance — ALWAYS present
    result["_data"] = {
        "quote": quote_prov.to_dict() if quote_prov else {"available": False},
        "kline": kline_prov.to_dict() if kline_prov else {"available": False},
        "is_live": quote_prov.is_live if quote_prov else False,
        "data_available": quote is not None or klines is not None,
        "recommendation": (
            "Data ready for AI analysis" if quote is not None
            else "Live data unavailable — AI analysis paused. Check network or wait for market hours."
        ),
    }

    return result
