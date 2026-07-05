"""Stock detail routes — AI-first comprehensive stock analysis (live + mock)."""

from fastapi import APIRouter, Query

from src.shared.mock_data import generate_stock_detail
from src.infrastructure.market_data.live_service import live_service

router = APIRouter(tags=["detail"], prefix="/detail")


@router.get("/{code}")
async def get_stock_detail(
    code: str,
    include: str = Query("all", description="Comma-separated: signals,evidence,kline,financials,news,fundflow"),
):
    """Get comprehensive AI-first stock detail."""
    detail = generate_stock_detail(code)

    # Try live kline data
    live_klines = await live_service.get_kline(code, count=250)
    if live_klines:
        detail["live_klines"] = live_klines
        detail["data_source"] = "live"

    # Try live quote
    live_quote = await live_service.get_realtime_quote(code)
    if live_quote:
        detail["latest_price"] = live_quote["price"]
        detail["price_change_pct"] = live_quote["change_pct"]
        detail["live_quote"] = live_quote
        detail["data_source"] = "live"

    # Filter based on include param
    if include != "all":
        inc = set(include.split(","))
        result: dict = {"stock_code": detail["stock_code"], "stock_name": detail["stock_name"]}
        if "signals" in inc or "ai" in inc:
            result.update({
                "ai_score": detail["ai_score"],
                "direction": detail["direction"],
                "confidence": detail["confidence"],
                "recommendation": detail["recommendation"],
                "stars": detail["stars"],
                "scores": detail["scores"],
                "top_signal": detail["top_signal"],
            })
        if "evidence" in inc:
            result["evidence"] = detail["evidence"]
            result["risk_factors"] = detail["risk_factors"]
        if "kline" in inc or "indicators" in inc:
            result["indicators"] = detail["indicators"]
        if "financials" in inc:
            result["financials"] = detail["financials"]
        if "news" in inc:
            result["news"] = detail["news"]
        if "fundflow" in inc:
            result["fund_flow"] = detail["fund_flow"]
        if "live_klines" in detail:
            result["live_klines"] = detail["live_klines"]
        return result

    return detail
