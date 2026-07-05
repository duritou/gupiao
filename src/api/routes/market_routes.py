"""Market overview routes — Dashboard data"""

from fastapi import APIRouter

from src.shared.mock_data import get_market_overview, get_sectors

router = APIRouter(tags=["market"], prefix="/market")


@router.get("/overview")
async def market_overview():
    """Get full market overview: indices, breadth, volume, northbound, sentiment, sectors."""
    return get_market_overview()


@router.get("/sectors")
async def market_sectors():
    """Get all sector scores and statuses."""
    return {"sectors": get_sectors()}
