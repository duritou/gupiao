"""Timeline routes — score evolution over time"""

from fastapi import APIRouter, Query

from src.shared.mock_data import generate_timeline

router = APIRouter(tags=["timeline"], prefix="/timeline")


@router.get("/{code}")
async def get_timeline(
    code: str,
    days: int = Query(30, ge=7, le=180, description="Number of days of history"),
):
    """Get score timeline for a stock — daily scores + change events."""
    return generate_timeline(code, days)
