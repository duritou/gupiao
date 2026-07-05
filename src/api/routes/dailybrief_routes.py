"""Daily Brief routes — auto-generated morning report"""

from fastapi import APIRouter

from src.shared.mock_data import generate_daily_brief

router = APIRouter(tags=["dailybrief"], prefix="/dailybrief")


@router.get("/latest")
async def latest_brief():
    """Get the latest daily brief (today's if generated, otherwise generates now)."""
    return generate_daily_brief()


@router.post("/generate")
async def generate_brief():
    """Force-generate today's daily brief."""
    return generate_daily_brief()
