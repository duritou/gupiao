"""Knowledge Graph + Event Feed API — v7.4."""

from fastapi import APIRouter, Query

from src.knowledge.event_feed import event_feed, EventType
from src.knowledge.graph import kg

router = APIRouter(tags=["knowledge"], prefix="/knowledge")


def _seed_sample_events():
    """Seed the event feed with realistic sample events for demonstration."""
    if event_feed._events:
        return

    from datetime import datetime
    today = datetime.now()

    event_feed.add_earnings_event(
        "688256.SH", "寒武纪", "2026Q2",
        revenue=18.5, net_profit=3.2,
        revenue_growth=42.0, profit_growth=58.0,
        roe=12.5, source="cninfo",
    )

    event_feed.add_earnings_event(
        "300308.SZ", "中际旭创", "2026Q2",
        revenue=45.2, net_profit=8.1,
        revenue_growth=35.0, profit_growth=28.0,
        roe=18.2, source="cninfo",
    )

    event_feed.add_policy_event(
        title="工信部：加快机器人产业创新发展",
        summary="工信部发布《关于加快机器人产业创新发展的指导意见》，提出到2028年机器人产业规模突破2000亿元。重点支持伺服电机、减速器、传感器等核心零部件。",
        sectors=["机器人", "高端制造"],
        issuing_body="miit", importance=92, direction="positive",
    )

    event_feed.add_policy_event(
        title="国家能源局：2026年光伏新增装机目标120GW",
        summary="国家能源局发布2026年能源工作指导意见，光伏新增装机目标上调至120GW，风电新增80GW。",
        sectors=["光伏", "新能源", "风电"],
        issuing_body="nea", importance=85, direction="positive",
    )

    event_feed.add_macro_event(
        "制造业PMI", "51.2 (扩张)", "50.8",
        source="nbs", importance=78,
    )

    event_feed.add_macro_event(
        "CPI同比", "2.1%", "1.8%",
        source="nbs", importance=72,
    )

    # News fusion — same event, multiple sources
    e = event_feed.add_event(
        event_type=EventType.NEWS,
        title="寒武纪发布新一代AI训练芯片思元590",
        summary="寒武纪正式发布思元590，采用7nm工艺，算力较上一代提升3倍。已获多家云计算客户订单。",
        stock_codes=["688256.SH"], sectors=["半导体", "AI"],
        tags=["产品发布", "AI芯片", "利好"],
        primary_source="xinhua", importance=88, direction="positive",
        impact_score=8.5,
    )
    # Simulate Reuters confirming the same event
    merged = event_feed.try_merge_with_existing(
        "寒武纪发布新一代AI训练芯片思元590", "reuters"
    )
    if not merged:
        event_feed.add_event(
            event_type=EventType.NEWS,
            title="寒武纪发布新一代AI训练芯片思元590",
            summary="Cambricon launches new AI training chip Siyuan 590.",
            stock_codes=["688256.SH"], sectors=["半导体"],
            tags=["产品发布", "AI芯片"],
            primary_source="reuters", importance=85, direction="positive",
            impact_score=8.0,
        )

    # Index stocks for Knowledge Graph
    for code, name, sector in [
        ("688256.SH", "寒武纪", "半导体"),
        ("688981.SH", "中芯国际", "半导体"),
        ("002371.SZ", "北方华创", "半导体"),
        ("300308.SZ", "中际旭创", "科技"),
        ("600519.SH", "贵州茅台", "消费"),
        ("300750.SZ", "宁德时代", "新能源"),
    ]:
        kg.index_stock(code, name, sector)


@router.get("/events")
async def get_events(
    event_type: str = Query("", description="earnings/announcement/policy/macro/market/signal/news"),
    stock_code: str = Query(""),
    sector: str = Query(""),
    min_importance: int = Query(0),
    limit: int = Query(30, ge=1, le=100),
):
    """Query structured events from the Event Feed."""
    _seed_sample_events()
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
    _seed_sample_events()
    events = event_feed.get_timeline(hours=hours, limit=50)
    return {"events": [e.to_dict() for e in events], "hours": hours}


@router.get("/events/important")
async def important_events():
    """Most important events right now (importance >= 70)."""
    _seed_sample_events()
    events = event_feed.get_important_events(limit=15)
    return {
        "events": [e.to_dict() for e in events],
        "total": len(events),
    }


@router.get("/stock/{code}/knowledge")
async def stock_knowledge(code: str):
    """All knowledge the system has about a stock — events, evidence chain."""
    _seed_sample_events()
    knowledge = kg.get_stock_knowledge(code)
    return knowledge


@router.get("/stock/{code}/evidence")
async def stock_evidence(code: str):
    """Evidence chain for a stock — what supports the AI recommendation."""
    _seed_sample_events()
    from src.shared.mock_data import get_stock_name
    name = get_stock_name(code)
    chain = kg.build_evidence_chain(code, name)
    return chain.to_dict()


@router.get("/sector/{sector}")
async def sector_context(sector: str):
    """Rich context about a sector — stocks, events, sentiment."""
    _seed_sample_events()
    ctx = kg.get_sector_context(sector)
    return ctx
