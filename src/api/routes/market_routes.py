"""Market overview routes — Dashboard data (live with mock fallback)."""

from fastapi import APIRouter

from src.shared.mock_data import get_market_overview, get_sectors
from src.infrastructure.market_data.live_service import live_service

router = APIRouter(tags=["market"], prefix="/market")


@router.get("/overview")
async def market_overview():
    """Get full market overview. Uses live data if available, mock otherwise."""
    mock = get_market_overview()

    # Try live indices
    live_indices = await live_service.get_index_quotes()
    if live_indices:
        idx_map = {i["name"]: i for i in live_indices}
        for key, name in [("shanghai", "上证指数"), ("shenzhen", "深证成值"),
                          ("chinext", "创业板指"), ("star50", "科创50")]:
            if name in idx_map:
                mock["indices"][key] = idx_map[name]

    # Try live breadth
    live_breadth = await live_service.get_market_breadth()
    if live_breadth:
        mock["market_breadth"].update(live_breadth)

    # Add live source indicator
    mock["data_source"] = "live" if live_indices else "mock"

    return mock


@router.get("/sectors")
async def market_sectors():
    """Get sector performance. Uses live data if available."""
    live_sectors = await live_service.get_sectors()
    if live_sectors:
        return {"sectors": live_sectors, "data_source": "live"}

    return {"sectors": get_sectors(), "data_source": "mock"}


@router.get("/live-status")
async def live_status():
    """Check if live data is available."""
    indices = await live_service.get_index_quotes()
    return {
        "live_available": len(indices) > 0,
        "indices_count": len(indices),
        "provider": "akshare",
    }


@router.get("/data-quality")
async def data_quality():
    """Data quality report — validates real data against expected ranges."""
    from src.shared.mock_data import STOCK_NAMES

    # Test with a sample of well-known stocks
    test_codes = ["000001.SZ", "000725.SZ", "600519.SH", "300750.SZ", "688981.SH"]
    results = []

    for code in test_codes:
        quote = await live_service.get_realtime_quote(code)
        if quote:
            quality = quote.get("_quality_score", 1.0)
            warnings = quote.get("_quality_warnings", [])
            results.append({
                "code": code,
                "name": quote.get("stock_name", ""),
                "price": quote.get("price", 0),
                "change_pct": quote.get("change_pct", 0),
                "amount_yi": quote.get("amount_yi", 0),
                "quality_score": quality,
                "warnings": warnings,
                "status": "ok" if quality >= 0.8 else "degraded" if quality >= 0.5 else "error",
            })

    # Overall health
    avg_quality = sum(r["quality_score"] for r in results) / len(results) if results else 0
    provider = "akshare" if results else "mock"

    return {
        "provider": provider,
        "overall_quality": round(avg_quality, 2),
        "status": "healthy" if avg_quality >= 0.8 else "degraded" if avg_quality >= 0.5 else "unhealthy",
        "samples": results,
        "suggestions": _generate_quality_suggestions(results),
    }


def _generate_quality_suggestions(results: list[dict]) -> list[str]:
    """Generate actionable suggestions from quality results."""
    suggestions = []
    for r in results:
        if r["quality_score"] < 0.5:
            suggestions.append(
                f"[{r['code']} {r['name']}] 数据质量异常(分数{r['quality_score']:.1f})，"
                f"价格{r['price']}元。建议对照同花顺验证。"
            )
    if not suggestions:
        suggestions.append("所有抽样数据通过质量检查 ✓")
    return suggestions


@router.get("/system-health")
async def system_health():
    """Complete system health check — Data Trust + all subsystems."""
    from src.infrastructure.market_data.trust import trust_engine

    health = trust_engine.check_system_health()
    result = health.to_dict()

    # Add live status check
    from src.infrastructure.market_data.live_service import live_service
    indices = await live_service.get_index_quotes()
    result["live_data"] = {
        "available": len(indices) > 0,
        "indices_count": len(indices),
    }

    return result
