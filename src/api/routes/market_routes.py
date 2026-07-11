"""Market routes — v7.4: real data with provenance."""

from datetime import datetime

from fastapi import APIRouter, Query

from src.infrastructure.market_data.source_manager import source_manager
from src.infrastructure.market_data.registry import get_source_summary, get_sources_by_layer
from src.infrastructure.market_data.manifest_loader import manifest_loader

router = APIRouter(tags=["market"], prefix="/market")


# 后台数据同步任务状态(单 worker,模块级即可)
_sync_state = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "params": {},
    "progress": {"done": 0, "total": 0, "current": ""},
    "result": None,
    "error": None,
}


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


@router.get("/data-status")
async def data_status(code: str = ""):
    """Full data pipeline status — transparent to the user.

    Shows: source, timestamp, freshness, latency, backup providers,
    provider rankings, recent reliability stats.
    """
    return source_manager.get_data_status(code)


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


@router.get("/feeds")
async def data_feeds():
    """List all registered data feeds with their sources and fields."""
    return {"feeds": source_manager.get_feeds()}


@router.get("/registry")
async def data_registry(layer: str = Query("", description="Filter: market/exchange/disclosure/news/macro/industry/company")):
    """Complete data source registry — all 30+ sources across 7 layers."""
    if layer:
        sources = get_sources_by_layer(layer)
        return {
            "layer": layer,
            "sources": [
                {
                    "id": s.id, "name": s.name, "name_en": s.name_en,
                    "url": s.url, "tier": s.tier.value, "category": s.category,
                    "provides": s.provides, "update_frequency": s.update_frequency,
                    "base_trust": s.base_trust, "is_free": s.is_free,
                    "requires_auth": s.requires_auth,
                    "integration_status": s.integration_status,
                    "notes": s.notes,
                }
                for s in sources
            ],
        }
    return get_source_summary()


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


@router.get("/provider-metrics")
async def provider_metrics(provider: str = ""):
    """Live provider metrics — YAML manifest + runtime stats."""
    if provider:
        return manifest_loader.get_summary(provider).to_dict()
    return {
        "providers": [s.to_dict() for s in manifest_loader.get_all_summaries()],
        "total_providers": len(manifest_loader.list_all()),
    }


@router.get("/provider-certification")
async def provider_certification():
    """Provider certification status — only certified capabilities feed AI.

    Shows per-provider: which capabilities are certified, data quality
    grade, known limits, and whether AI can use this provider.
    """
    summaries = manifest_loader.get_all_summaries()
    return {
        "providers": [
            {
                "provider": s.provider,
                "certified_count": sum(
                    1 for c in s.certified if c.get("verified")
                ),
                "total_capabilities": len(s.capabilities),
                "certified": s.certified,
                "data_quality_grade": s.data_quality.quality_grade,
                "data_quality": s.data_quality.to_dict(),
                "known_limits": s.known_limits,
                "ai_ready": any(
                    c.get("verified") for c in s.certified
                ),
            }
            for s in summaries
        ],
    }


# ================================================================
# Data sync — local warehouse refresh
# ================================================================

async def _run_sync(codes, days_back, with_indicators):
    """后台同步任务:baostock 拉日线 → (可选)算指标。

    sync_daily_bars 是含阻塞 IO 的同步函数,放线程池跑以免卡住事件循环。
    """
    import asyncio
    from src.infrastructure.storage.market_database import market_db

    loop = asyncio.get_event_loop()

    def progress(idx, total, code, status):
        _sync_state["progress"] = {
            "done": idx, "total": total, "current": code, "last_status": status,
        }

    try:
        result = await loop.run_in_executor(
            None,
            lambda: market_db.sync_daily_bars(
                codes=codes, days_back=days_back, progress_callback=progress,
            ),
        )
        sync_dict = {
            "new_daily": result.new_daily,
            "stocks_updated": result.stocks_updated,
            "errors_count": len(result.errors),
            "duration_seconds": round(result.duration_seconds, 1),
            "recent_errors": result.errors[-5:],
        }

        if with_indicators:
            computed = await loop.run_in_executor(
                None, market_db.compute_and_store_indicators
            )
            sync_dict["indicators_computed"] = computed

        _sync_state["result"] = sync_dict
    except Exception as e:
        _sync_state["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    finally:
        _sync_state["running"] = False
        _sync_state["finished_at"] = datetime.now().isoformat()


@router.post("/sync")
async def sync_market_data(
    codes: list[str] = Query(default=None, description="指定股票代码,留空=全 A 股"),
    days_back: int = Query(default=30, ge=1, le=365),
    with_indicators: bool = Query(default=True),
):
    """触发本地数据仓库同步(后台执行,立即返回)。

    全 A 股同步耗时较长(首次约 30-60 分钟),用 asyncio.create_task 后台跑,
    不阻塞本请求。用 GET /market/sync/status 查进度。
    """
    import asyncio

    if _sync_state["running"]:
        return {
            "status": "already_running",
            "started_at": _sync_state["started_at"],
            "progress": _sync_state["progress"],
        }

    _sync_state["running"] = True
    _sync_state["started_at"] = datetime.now().isoformat()
    _sync_state["finished_at"] = None
    _sync_state["params"] = {"codes": codes, "days_back": days_back, "with_indicators": with_indicators}
    _sync_state["progress"] = {"done": 0, "total": 0, "current": ""}
    _sync_state["result"] = None
    _sync_state["error"] = None

    asyncio.create_task(_run_sync(codes, days_back, with_indicators))

    return {
        "status": "started",
        "started_at": _sync_state["started_at"],
        "params": _sync_state["params"],
        "note": "全 A 股首次同步约 30-60 分钟,可用 GET /market/sync/status 查进度",
    }


@router.get("/sync/status")
async def sync_status():
    """查询数据同步进度 + 当前本地仓库统计。"""
    from src.infrastructure.storage.market_database import market_db
    return {
        "running": _sync_state["running"],
        "started_at": _sync_state["started_at"],
        "finished_at": _sync_state["finished_at"],
        "progress": _sync_state["progress"],
        "result": _sync_state["result"],
        "error": _sync_state["error"],
        "db_stats": market_db.get_stats(),
    }
