"""Knowledge Graph + Event Feed API 鈥?v7.4."""

from fastapi import APIRouter, Query

from src.knowledge.event_feed import event_feed, EventType
from src.knowledge.graph import kg

router = APIRouter(tags=["knowledge"], prefix="/knowledge")


@router.get("/events")
async def get_events(
    event_type: str = Query("", description="earnings/announcement/policy/macro/market/signal/news"),
    stock_code: str = Query(""),
    sector: str = Query(""),
    min_importance: int = Query(0),
    limit: int = Query(30, ge=1, le=100),
):
    """Query structured events from the Event Feed."""
    events = event_feed.get_events(
        limit=limit, event_type=event_type,
        stock_code=stock_code, sector=sector,
        min_importance=min_importance,
    )
    return {
        "events": [e.to_dict() for e in events],
        "total": len(events),
        "stats": event_feed.get_stats(),
    }


@router.get("/events/timeline")
async def event_timeline(hours: int = Query(24, ge=1, le=168)):
    """Recent event timeline for visualization."""
    events = event_feed.get_timeline(hours=hours, limit=50)
    return {"events": [e.to_dict() for e in events], "hours": hours}


@router.get("/events/important")
async def important_events():
    """Most important events right now (importance >= 70)."""
    events = event_feed.get_important_events(limit=15)
    return {
        "events": [e.to_dict() for e in events],
        "total": len(events),
    }


@router.get("/stock/{code}/knowledge")
async def stock_knowledge(code: str):
    """All knowledge the system has about a stock 鈥?events, evidence chain."""
    knowledge = kg.get_stock_knowledge(code)
    return knowledge


@router.get("/stock/{code}/evidence")
async def stock_evidence(code: str):
    """Evidence chain for a stock 鈥?what supports the AI recommendation."""
    from src.api.routes.journal_utils import stock_name_from_journal
    name = stock_name_from_journal(code)
    chain = kg.build_evidence_chain(code, name)
    return chain.to_dict()


@router.get("/sector/{sector}")
async def sector_context(sector: str):
    """Rich context about a sector 鈥?stocks, events, sentiment."""
    ctx = kg.get_sector_context(sector)
    return ctx

