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
