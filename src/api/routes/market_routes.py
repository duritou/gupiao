"""Market routes — v7.4: real data with provenance."""

from fastapi import APIRouter

from src.infrastructure.market_data.source_manager import source_manager

router = APIRouter(tags=["market"], prefix="/market")


@router.get("/overview")
async def market_overview():
    """Market overview with explicit data provenance."""
    # Indices
    indices, idx_prov = await source_manager.get_index_quotes()
    idx_map = {}
    if indices:
        idx_map = {i["name"]: i for i in indices}

    # Breadth
    breadth, breadth_prov = await source_manager.get_market_breadth()

    result = {
        "indices": {
            "shanghai": idx_map.get("上证指数", {"name": "上证指数", "value": 0, "change_pct": 0}),
            "shenzhen": idx_map.get("深证成指", {"name": "深证成指", "value": 0, "change_pct": 0}),
            "chinext": idx_map.get("创业板指", {"name": "创业板指", "value": 0, "change_pct": 0}),
            "star50": idx_map.get("科创50", {"name": "科创50", "value": 0, "change_pct": 0}),
        },
        "market_breadth": breadth or {"up": 0, "down": 0, "flat": 0, "limit_up": 0, "limit_down": 0, "total_volume": 0},
        "hot_sectors": [],
        "risk_summary": [],
        "northbound": {"net_flow": 0, "direction": "neutral"},
        "total_volume": breadth.get("total_volume", 0) if breadth else 0,
        "_data": {
            "indices": idx_prov.to_dict(),
            "breadth": breadth_prov.to_dict(),
            "is_live": idx_prov.is_live or breadth_prov.is_live,
            "available": indices is not None or breadth is not None,
        },
    }
    return result


@router.get("/sectors")
async def market_sectors():
    """Sector performance."""
    # Try live sectors
    try:
        import akshare as ak
        import asyncio
        df = await asyncio.to_thread(ak.stock_board_concept_name_em)
        if df is not None and not df.empty:
            result = []
            for _, row in df.head(30).iterrows():
                score = max(10, min(99, 50 + float(row.get("涨跌幅", 0)) * 10))
                stars = 5 if score >= 80 else 4 if score >= 65 else 3 if score >= 45 else 2 if score >= 25 else 1
                result.append({
                    "name": str(row.get("板块名称", "")),
                    "score": score, "change_pct": float(row.get("涨跌幅", 0)),
                    "stars": stars, "status": "强势" if score >= 70 else "震荡" if score >= 40 else "弱势",
                })
            result.sort(key=lambda s: s["score"], reverse=True)
            return {"sectors": result[:12], "data_source": "akshare", "is_live": True}
    except Exception:
        pass
    return {"sectors": [], "data_source": "none", "is_live": False}


@router.get("/live-status")
async def live_status():
    """Check data source availability."""
    health = source_manager.check_health()
    return {
        "live_available": health["live_data_available"],
        "cache_entries": health["cache_entries"],
        "sources": health["sources"],
        "recommendation": health["recommendation"],
    }


@router.get("/data-quality")
async def data_quality():
    """Data quality report."""
    health = source_manager.check_health()
    freshness = source_manager.get_data_freshness()

    return {
        "sources": health["sources"],
        "freshness": freshness,
        "live_available": health["live_data_available"],
        "recommendation": health["recommendation"],
    }


@router.get("/system-health")
async def system_health():
    """Complete system health check."""
    from src.infrastructure.market_data.trust import trust_engine

    # Update trust engine with source manager status
    for s in source_manager.get_all_sources_status():
        provider = trust_engine.get_or_create_provider(s["name"])
        if s["available"]:
            provider.record_success(s.get("latency_ms", 0))
        elif s["consecutive_failures"] > 0:
            provider.record_failure()

    health = trust_engine.check_system_health()
    result = health.to_dict()

    # Override Market Data status from source_manager (more accurate)
    sm_health = source_manager.check_health()
    result["live_data"] = {
        "available": sm_health["live_data_available"],
        "cache_entries": sm_health["cache_entries"],
        "recommendation": sm_health["recommendation"],
    }

    # Update market data subsystem status
    if result["subsystems"]:
        for s in result["subsystems"]:
            if s["name"] == "Market Data":
                s["status"] = "healthy" if sm_health["live_data_available"] else "down"
                s["details"]["sources"] = sm_health["sources"]

    return result
