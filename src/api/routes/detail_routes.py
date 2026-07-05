"""Stock detail routes — AI-first comprehensive stock analysis"""

from fastapi import APIRouter, Query

from src.shared.mock_data import generate_stock_detail

router = APIRouter(tags=["detail"], prefix="/detail")


@router.get("/{code}")
async def get_stock_detail(
    code: str,
    include: str = Query("all", description="Comma-separated: signals,evidence,kline,financials,news,fundflow"),
):
    """Get comprehensive AI-first stock detail."""
    detail = generate_stock_detail(code)

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
        return result

    return detail
