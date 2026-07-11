"""Morning Brief routes backed by real pipeline decisions."""

from fastapi import APIRouter

from src.api.routes.brief_utils import build_real_brief

router = APIRouter(tags=["morning-brief"], prefix="/morning-brief")


@router.get("/today")
async def get_morning_brief():
    """Generate today's brief from the decision journal and real market overview."""
    return await build_real_brief()
