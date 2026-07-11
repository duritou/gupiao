"""Daily Brief routes backed by real pipeline decisions."""

from fastapi import APIRouter

from src.api.routes.brief_utils import build_real_brief

router = APIRouter(tags=["dailybrief"], prefix="/dailybrief")


@router.get("/latest")
async def latest_brief():
    """Get the latest generated brief from real journal data."""
    return await build_real_brief()


@router.post("/generate")
async def generate_brief():
    """Regenerate today's brief from real journal data."""
    return await build_real_brief()
