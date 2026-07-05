"""Alert routes — signal alerts and notifications"""

from fastapi import APIRouter, Query

from src.shared.mock_data import generate_alerts

router = APIRouter(tags=["alerts"], prefix="/alerts")


@router.get("/recent")
async def get_recent_alerts(
    limit: int = Query(50, ge=1, le=100),
    type: str = Query(None, description="Filter by type: signal/risk/all"),
):
    """Get recent alerts for today."""
    all_alerts = generate_alerts(limit)

    if type and type != "all":
        if type == "signal":
            all_alerts = [a for a in all_alerts if a["direction"] in ("up", "down")]
        elif type == "risk":
            all_alerts = [a for a in all_alerts if a["score"] < 45]

    unread = sum(1 for a in all_alerts if not a["read"])
    return {
        "alerts": all_alerts[:limit],
        "total_today": len(all_alerts),
        "unread": unread,
    }


@router.get("/unread-count")
async def unread_count():
    """Get count of unread alerts."""
    alerts = generate_alerts(20)
    return {"unread": sum(1 for a in alerts if not a["read"])}
