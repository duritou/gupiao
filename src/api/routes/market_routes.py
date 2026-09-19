"""Market routes — v7.4: real data with provenance."""

import asyncio
import logging
import time
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from config.settings import settings
from src.ai_os.market_regime import classify_market_regime
from src.infrastructure.market_data.hithink_contracts import normalize_thscode
from src.infrastructure.market_data.hithink_provider import hithink_provider
from src.infrastructure.market_data.manifest_loader import manifest_loader
from src.infrastructure.market_data.registry import get_source_summary, get_sources_by_layer
from src.infrastructure.market_data.source_manager import DataProvenance, source_manager

router = APIRouter(tags=["market"], prefix="/market")
logger = logging.getLogger(__name__)


_OVERVIEW_CACHE_TTL_SECONDS = 30.0
_OVERVIEW_PROVIDER_TIMEOUT_SECONDS = 10.0
_DASHBOARD_QUOTE_TIMEOUT_SECONDS = 4.0
_DASHBOARD_QUOTE_CONCURRENCY = 8
_overview_cache: tuple[float, dict] | None = None
_overview_lock = asyncio.Lock()


class QuoteBatchRequest(BaseModel):
    """Bounded real-time quote request for interactive UI surfaces."""

    codes: list[str] = Field(max_length=50)


class MetadataSnapshotRequest(BaseModel):
    """Caller-supplied dated metadata from a source with historical coverage."""

    as_of_date: str = Field(description="快照对应的交易日，格式 YYYY-MM-DD")
    snapshots: list[dict] = Field(min_length=1, max_length=5000)
    source: str = Field(default="external_dated_source", min_length=1, max_length=80)


def _symbol_search_view(payload: object, query: str, mode: str) -> dict:
    rows = getattr(payload, "data", None)
    results = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    return {
        "query": query,
        "results": results,
        "_meta": {
            "provider": "hithink",
            "source_name": "同花顺金融数据服务",
            "source_layer": "hithink_rest",
            "endpoint": getattr(payload, "endpoint", ""),
            "request_id": getattr(payload, "request_id", ""),
            "fetched_at": getattr(payload, "fetched_at", ""),
            "data_date": getattr(payload, "data_date", ""),
            "is_live": False,
            "available": bool(results),
            "rollout_mode": mode,
            "result_count": len(results),
        },
    }


def _exact_symbol_view(query: str) -> dict | None:
    try:
        thscode = normalize_thscode(query)
    except ValueError:
        return None
    ticker = thscode.split(".", 1)[0]
    return {
        "query": query,
        "results": [{"thscode": thscode, "ticker": ticker, "name": ""}],
        "_meta": {
            "provider": "local_normalization",
            "source_layer": "local_contract",
            "available": True,
            "is_live": False,
            "result_count": 1,
            "note": "完整或可规范化代码不请求远程消歧服务",
        },
    }


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


async def _build_market_overview(*, require_intraday: bool = False) -> dict:
    """Market overview with explicit data provenance."""
    # P0+: indices 与 breadth 并行获取。akshare 风控时各吃 8s 超时,
    # 串行需 ~16s, 并行降到 ~8s (日报 build_real_brief 内部调本接口, 一并提速)。
    index_call = (
        source_manager.get_intraday_index_quotes
        if require_intraday else source_manager.get_index_quotes
    )
    breadth_call = (
        source_manager.get_intraday_market_breadth
        if require_intraday else source_manager.get_market_breadth
    )
    # Some third-party SDKs perform blocking work before their first await.
    # Run the complete provider coroutine on a worker loop so a wedged SDK can
    # never freeze FastAPI's health and dashboard routes.
    async def bounded_fetch(fetch, label: str):
        """Keep one slow provider from making the dashboard look offline."""
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(lambda: asyncio.run(fetch())),
                timeout=_OVERVIEW_PROVIDER_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("market overview provider timed out: %s", label)
            return None, DataProvenance(
                provider="none",
                source_name=label,
                fetched_at=datetime.now().isoformat(),
                error_message=f"{label}超时",
            )
        except Exception as exc:
            logger.warning("market overview provider failed: %s: %s", label, exc)
            return None, DataProvenance(
                provider="none",
                source_name=label,
                fetched_at=datetime.now().isoformat(),
                error_message=str(exc)[:240],
            )

    index_fetch = bounded_fetch(index_call, "指数行情")
    breadth_fetch = bounded_fetch(breadth_call, "涨跌统计")
    (indices, idx_prov), (breadth, breadth_prov) = await asyncio.gather(
        index_fetch,
        breadth_fetch,
    )

    idx_map = {}
    if indices:
        idx_map = {i["name"]: i for i in indices}

    # Keep the live overview aligned with replay diagnostics.  The classifier
    # only consumes the breadth snapshot returned by the provider; when a
    # provider omits an explicit total, derive it from up/down/flat counts.
    regime_snapshot = dict(breadth or {})
    if not regime_snapshot.get("total"):
        regime_snapshot["total"] = sum(
            int(regime_snapshot.get(key) or 0) for key in ("up", "down", "flat")
        )
    market_regime = classify_market_regime(
        regime_snapshot,
        as_of_date=str(regime_snapshot.get("data_date") or ""),
    )
    breadth_data_date = str(
        getattr(breadth_prov, "data_date", "")
        or regime_snapshot.get("data_date")
        or ""
    )[:10]

    result = {
        "indices": {
            "shanghai": idx_map.get("上证指数", {"name": "上证指数", "value": 0, "change_pct": 0}),
            "shenzhen": idx_map.get("深证成指", {"name": "深证成指", "value": 0, "change_pct": 0}),
            "chinext": idx_map.get("创业板指", {"name": "创业板指", "value": 0, "change_pct": 0}),
            "star50": idx_map.get("科创50", {"name": "科创50", "value": 0, "change_pct": 0}),
        },
        "market_breadth": breadth
        or {
            "up": 0,
            "down": 0,
            "flat": 0,
            "limit_up": 0,
            "limit_down": 0,
            "total_volume": 0,
        },
        "risk_summary": [],
        "northbound": {"net_flow": 0, "direction": "neutral"},
        "total_volume": breadth.get("total_volume", 0) if breadth else 0,
        "market_regime": market_regime.to_dict(),
        "_data": {
            "indices": idx_prov.to_dict(),
            "breadth": breadth_prov.to_dict(),
            "is_live": idx_prov.is_live or breadth_prov.is_live,
            "available": indices is not None or breadth is not None,
            "mode": "intraday" if require_intraday else "dated_close_or_fallback",
            "requested_intraday": require_intraday,
                "intraday_available": bool(
                    breadth is not None
                    and breadth_prov.is_live
                    and breadth_data_date == datetime.now().date().isoformat()
                ),
        },
    }
    return result


@router.get("/overview")
async def market_overview(require_intraday: bool = False):
    """Return a short cached snapshot and collapse concurrent dashboard requests."""
    global _overview_cache
    if require_intraday:
        # Intraday checkpoints must not reuse a dated-close dashboard cache.
        return await _build_market_overview(require_intraday=True)
    now = time.monotonic()
    if _overview_cache is not None and now - _overview_cache[0] < _OVERVIEW_CACHE_TTL_SECONDS:
        return dict(_overview_cache[1])

    async with _overview_lock:
        now = time.monotonic()
        if _overview_cache is not None and now - _overview_cache[0] < _OVERVIEW_CACHE_TTL_SECONDS:
            return dict(_overview_cache[1])
        result = await _build_market_overview()
        _overview_cache = (time.monotonic(), result)
        return dict(result)


@router.post("/quotes")
async def market_quotes(req: QuoteBatchRequest):
    """Fetch current quotes separately from T-1 research signals.

    Every row carries provenance so clients can distinguish real-time,
    cached, delayed, and unavailable values without guessing.
    """
    normalized_codes = list(
        dict.fromkeys(code.strip().upper() for code in req.codes if code.strip())
    )
    semaphore = asyncio.Semaphore(_DASHBOARD_QUOTE_CONCURRENCY)

    async def fetch_quote(code: str):
        async def run():
            async with semaphore:
                return await asyncio.to_thread(
                    lambda: asyncio.run(source_manager.get_realtime_quote(code))
                )

        try:
            return await asyncio.wait_for(
                run(),
                timeout=_DASHBOARD_QUOTE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            from src.infrastructure.market_data.source_manager import DataProvenance

            return None, DataProvenance(
                provider="none",
                source_name="实时报价超时",
                fetched_at=datetime.now().isoformat(),
                error_message=(
                    f"报价在 {_DASHBOARD_QUOTE_TIMEOUT_SECONDS:.0f} 秒内未返回，"
                    "Dashboard 已降级"
                ),
            )

    fetched = await asyncio.gather(*(fetch_quote(code) for code in normalized_codes))
    quotes = []
    for code, (quote, provenance) in zip(normalized_codes, fetched, strict=False):
        item = dict(quote or {})
        item.setdefault("stock_code", code)
        item["provenance"] = provenance.to_dict()
        item["available"] = quote is not None
        quotes.append(item)
    return {
        "quotes": quotes,
        "requested_at": datetime.now().isoformat(timespec="seconds"),
    }


@router.get("/symbol-search")
async def symbol_search(
    q: str = Query(..., min_length=1, max_length=80, description="股票代码或名称"),
    limit: int = Query(default=10, ge=1, le=50),
):
    """Resolve an A-share code/name through HiThink without touching strategy data."""
    query = q.strip()
    exact = _exact_symbol_view(query)
    if exact is not None:
        return exact

    mode = settings.HITHINK_SYMBOL_MODE
    error = ""
    if mode in {"primary", "shadow", "validator", "fallback"} and hithink_provider.configured:
        try:
            payload = await hithink_provider.fetch_symbol_search(query, limit)
            view = _symbol_search_view(payload, query, mode)
            if mode in {"primary", "fallback"} and view["results"]:
                return view
            if mode in {"shadow", "validator"}:
                return {
                    "query": query,
                    "results": [],
                    "_meta": {
                        **view["_meta"],
                        "available": False,
                        "shadow_result_count": view["_meta"]["result_count"],
                        "note": "HiThink 消歧结果仅 shadow/validator 观测，未进入默认返回",
                    },
                }
        except Exception as exc:
            error = str(getattr(exc, "category", type(exc).__name__))[:80]
    return {
        "query": query,
        "results": [],
        "_meta": {
            "provider": "none",
            "source_layer": "fallback",
            "available": False,
            "is_live": False,
            "fallback_reason": error or "hithink_symbol_search_unavailable",
            "rollout_mode": mode,
        },
    }


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
        "tested": health.get("tested", False),
        "last_probe": health.get("last_probe", {}),
    }


@router.post("/probe")
async def probe_live_sources(code: str = "600000.SH"):
    """Run a bounded real-provider probe and update health diagnostics."""
    return await source_manager.probe_live_sources(code.strip().upper())


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
        "tested": health.get("tested", False),
        "last_probe": health.get("last_probe", {}),
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
        from src.ai_os.task_executor import task_executor
        from src.api.routes.alerts_routes import _build_alerts_from_journal
        from src.infrastructure.storage.market_database import market_db

        today = datetime.now().date().isoformat()
        executor_status = task_executor.get_status()
        completed_today = sum(
            str(item.get("completed_at") or "").startswith(today)
            and item.get("status") in {"success", "skipped"}
            for item in task_executor.get_recent_executions(limit=500)
        )
        alerts_today, decision_stats, paper_actions, replay_run_rows, replay_dates = (
            await asyncio.gather(
                asyncio.to_thread(_build_alerts_from_journal, today),
                asyncio.to_thread(market_db.get_decision_stats),
                asyncio.to_thread(market_db.get_paper_trades, limit=500),
                asyncio.to_thread(market_db.get_replay_runs, limit=200),
                asyncio.to_thread(market_db.get_replay_dates, limit=365),
            )
        )
        replay_runs = len(replay_run_rows)

        for s in result["subsystems"]:
            if s["name"] == "Market Data":
                s["status"] = "healthy" if sm_health["live_data_available"] else "down"
                s["details"]["sources"] = sm_health["sources"]
            elif s["name"] == "AI OS Scheduler":
                s["status"] = "healthy" if executor_status["is_running"] else "down"
                s["details"] = {
                    "is_running": executor_status["is_running"],
                    "running_tasks": executor_status["running_tasks"],
                    "tasks_completed_today": completed_today,
                }
            elif s["name"] == "Alert Intelligence":
                s["status"] = "healthy" if executor_status["is_running"] else "degraded"
                s["details"] = {
                    "alerts_today": len(alerts_today),
                    "urgent": sum(a["level"] in {"P0", "P1"} for a in alerts_today),
                    "monitoring": executor_status["is_running"],
                }
            elif s["name"] == "Trust Engine":
                s["status"] = (
                    "healthy" if decision_stats["decisive_verified_decisions"]
                    else "degraded"
                )
                s["details"] = {
                    "total_decisions": decision_stats["total_decisions"],
                    "verified_decisions": decision_stats["decisive_verified_decisions"],
                    "observed_decisions": decision_stats["verified_decisions"],
                    "accuracy_available": decision_stats["accuracy_available"],
                    "accuracy": decision_stats["accuracy"],
                }
            elif s["name"] == "User Model":
                s["status"] = "healthy" if decision_stats["total_decisions"] else "degraded"
                s["details"] = {
                    "profile_loaded": bool(decision_stats["total_decisions"]),
                    "decisions_analyzed": decision_stats["total_decisions"],
                    "paper_actions": len(paper_actions),
                }
            elif s["name"] == "Replay Engine":
                s["status"] = "healthy"
                s["details"] = {
                    "replay_runs": replay_runs,
                    "replayable_dates": len(replay_dates),
                    "lookahead_safe": True,
                    "simulation_capable": True,
                }

    statuses = [item.get("status", "down") for item in result.get("subsystems", [])]
    if "down" in statuses:
        result["overall_status"] = "down"
    elif "degraded" in statuses:
        result["overall_status"] = "degraded"
    else:
        result["overall_status"] = "healthy"

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


@router.post("/metadata-snapshot")
async def ingest_metadata_snapshot(req: MetadataSnapshotRequest):
    """Persist a caller-supplied point-in-time stock metadata snapshot.

    The endpoint accepts only already dated rows. It never substitutes the
    current ``stock_basic`` state for a historical date.
    """
    try:
        normalized_date = date.fromisoformat(req.as_of_date).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="as_of_date must be YYYY-MM-DD") from exc

    invalid = [
        index
        for index, item in enumerate(req.snapshots)
        if not str(item.get("ts_code") or item.get("code") or "").strip()
    ]
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"snapshots missing ts_code/code at indexes: {invalid[:10]}",
        )

    from src.infrastructure.storage.market_database import market_db

    source = req.source.strip() or "external_dated_source"
    stored = await asyncio.to_thread(
        market_db.upsert_stock_metadata_snapshot,
        req.snapshots,
        normalized_date,
        source,
    )
    coverage = await asyncio.to_thread(
        market_db.get_stock_metadata_coverage,
        normalized_date,
    )
    return {
        "status": "ok" if stored else "empty",
        "as_of_date": normalized_date,
        "source": source,
        "input_count": len(req.snapshots),
        "stored_count": stored,
        "coverage": coverage,
    }


@router.get("/metadata-status")
async def metadata_status(as_of_date: str = Query(..., description="查询截止日期 YYYY-MM-DD")):
    """Return historical metadata coverage without current-state fallback."""
    try:
        normalized_date = date.fromisoformat(as_of_date).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="as_of_date must be YYYY-MM-DD") from exc

    from src.infrastructure.storage.market_database import market_db

    coverage = await asyncio.to_thread(
        market_db.get_stock_metadata_coverage,
        normalized_date,
    )
    return {"as_of_date": normalized_date, "coverage": coverage}


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

async def _run_sync(
    codes, days_back, with_indicators, target_date: str = "", metadata_date: str = ""
):
    """后台同步任务:baostock 拉日线 → (可选)算指标。

    sync_daily_bars 是含阻塞 IO 的同步函数,放线程池跑以免卡住事件循环。
    """
    from src.infrastructure.storage.market_database import market_db

    loop = asyncio.get_event_loop()

    def progress(idx, total, code, status):
        _sync_state["progress"] = {
            "done": idx, "total": total, "current": code, "last_status": status,
        }

    try:
        metadata_result = None
        if metadata_date:
            metadata_result = await loop.run_in_executor(
                None,
                lambda: market_db.sync_stock_metadata_snapshot(
                    metadata_date, codes=codes
                ),
            )
        result = await loop.run_in_executor(
            None,
            lambda: market_db.sync_daily_bars(
                codes=codes,
                days_back=days_back,
                progress_callback=progress,
                target_date=target_date,
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

        if metadata_result is not None:
            sync_dict["metadata_snapshot"] = metadata_result
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
    metadata_date: str = Query(
        default="", description="可选：同步指定交易日的历史股票元数据快照"
    ),
):
    """触发本地数据仓库同步(后台执行,立即返回)。

    全 A 股同步耗时较长(首次约 30-60 分钟),用 asyncio.create_task 后台跑,
    不阻塞本请求。用 GET /market/sync/status 查进度。
    """
    import asyncio

    if metadata_date:
        try:
            metadata_date = date.fromisoformat(metadata_date).isoformat()
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="metadata_date must be YYYY-MM-DD",
            ) from exc

    if _sync_state["running"]:
        return {
            "status": "already_running",
            "started_at": _sync_state["started_at"],
            "progress": _sync_state["progress"],
        }

    _sync_state["running"] = True
    _sync_state["started_at"] = datetime.now().isoformat()
    _sync_state["finished_at"] = None
    _sync_state["params"] = {
        "codes": codes,
        "days_back": days_back,
        "with_indicators": with_indicators,
        "metadata_date": metadata_date,
    }
    _sync_state["progress"] = {"done": 0, "total": 0, "current": ""}
    _sync_state["result"] = None
    _sync_state["error"] = None

    asyncio.create_task(
        _run_sync(codes, days_back, with_indicators, metadata_date=metadata_date)
    )

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
    db_stats = await asyncio.to_thread(market_db.get_stats)
    return {
        "running": _sync_state["running"],
        "started_at": _sync_state["started_at"],
        "finished_at": _sync_state["finished_at"],
        "progress": _sync_state["progress"],
        "result": _sync_state["result"],
        "error": _sync_state["error"],
        "db_stats": db_stats,
    }
