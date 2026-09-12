"""Market routes — v7.4: real data with provenance."""

import asyncio
import logging
import math
import time
from datetime import date, datetime

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from config.settings import settings
from src.ai_os.market_regime import classify_market_regime
from src.infrastructure.market_data.hithink_contracts import normalize_thscode
from src.infrastructure.market_data.hithink_provider import hithink_provider
from src.infrastructure.market_data.manifest_loader import manifest_loader
from src.infrastructure.market_data.provider_resilience import (
    parse_retry_after,
    record_provider_failure,
    record_provider_success,
    reserve_provider_request,
)
from src.infrastructure.market_data.registry import get_source_summary, get_sources_by_layer
from src.infrastructure.market_data.source_manager import source_manager

router = APIRouter(tags=["market"], prefix="/market")
logger = logging.getLogger(__name__)


_SECTOR_URL = "https://push2.eastmoney.com/api/qt/clist/get"
_SECTOR_CACHE_TTL_SECONDS = 120.0
_SECTOR_FAILURE_CACHE_SECONDS = 30.0
_OVERVIEW_CACHE_TTL_SECONDS = 30.0
_SECTOR_NAMES = [
    "食品饮料", "医药生物", "电子", "计算机", "电力设备", "机械设备",
    "汽车", "化工", "银行", "非银金融", "房地产", "建筑装饰",
]
_SECTOR_ETF_PROXIES = {
    "sh512480": "半导体",
    "sz159819": "人工智能",
    "sh562500": "机器人",
    "sh516160": "新能源",
    "sh512010": "医药生物",
    "sz159928": "消费",
    "sh512880": "证券",
    "sh512800": "银行",
    "sh512660": "国防军工",
    "sz159825": "农业",
    "sh515880": "通信",
    "sh512720": "计算机",
}
_sector_cache: dict | None = None
_sector_cache_expires_at = 0.0
_sector_refresh_task: asyncio.Task[None] | None = None
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
    index_fetch = (
        source_manager.get_intraday_index_quotes()
        if require_intraday else source_manager.get_index_quotes()
    )
    breadth_fetch = (
        source_manager.get_intraday_market_breadth()
        if require_intraday else source_manager.get_market_breadth()
    )
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
        "hot_sectors": [],
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
    fetched = await asyncio.gather(
        *(source_manager.get_realtime_quote(code) for code in normalized_codes)
    )
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


def _sector_fallback(*, refreshing: bool, error: str = "") -> dict:
    """Return an honest, fast placeholder without inventing market movement."""
    fallback_result = [
        {
            "name": sector,
            "score": 50,
            "change_pct": 0.0,
            "stars": 3,
            "status": "暂无数据",
        }
        for sector in _SECTOR_NAMES
    ]
    if refreshing:
        message = "正在后台刷新实时板块数据，页面可继续使用"
    else:
        message = "实时板块数据暂时不可用，显示参考板块列表"
    return {
        "sectors": fallback_result,
        "data_source": "static_fallback",
        "is_live": False,
        "refreshing": refreshing,
        "stale": False,
        "message": message,
        "error": error[:240],
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }


def _sector_score(change_pct: float) -> tuple[float, int, str]:
    score = round(max(10.0, min(99.0, 50.0 + change_pct * 10.0)), 1)
    stars = (
        5 if score >= 80 else
        4 if score >= 65 else
        3 if score >= 45 else
        2 if score >= 25 else
        1
    )
    status = "强势" if score >= 70 else "震荡" if score >= 40 else "弱势"
    return score, stars, status


async def _fetch_eastmoney_sector_payload() -> dict:
    """Fetch one bounded Eastmoney snapshot without an uncancellable worker thread."""
    params = {
        "pn": "1",
        "pz": "100",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:90 t:3 f:!50",
        "fields": "f3,f12,f14",
    }
    # TLS setup to this public host is occasionally slower than 1.5 seconds on
    # Windows.  The refresh already runs behind a stale-cache boundary, so a
    # bounded 4/6 second connect/read budget improves success without freezing
    # the Market Map UI.
    timeout = httpx.Timeout(connect=4.0, read=6.0, write=2.0, pool=1.0)
    headers = {
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://quote.eastmoney.com/center/boardlist.html",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
        ),
    }
    wait = reserve_provider_request(
        "eastmoney",
        min_interval_seconds=settings.EASTMONEY_MIN_INTERVAL_SECONDS,
        jitter_seconds=settings.EASTMONEY_JITTER_SECONDS,
    )
    if wait > 0:
        await asyncio.sleep(wait)
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            headers=headers,
            follow_redirects=True,
            trust_env=False,
            limits=httpx.Limits(
                max_connections=1,
                max_keepalive_connections=1,
                keepalive_expiry=15.0,
            ),
        ) as client:
            response = await client.get(_SECTOR_URL, params=params)
            if response.status_code in {403, 429}:
                retry_after = parse_retry_after(
                    response.headers.get("Retry-After"),
                    maximum_seconds=settings.REMOTE_MARKET_RETRY_AFTER_MAX_SECONDS,
                )
                record_provider_failure(
                    "eastmoney",
                    f"sector HTTP {response.status_code}",
                    failure_threshold=settings.EASTMONEY_FAILURE_THRESHOLD,
                    cooldown_seconds=settings.EASTMONEY_COOLDOWN_SECONDS,
                    immediate=True,
                    retry_after_seconds=retry_after,
                )
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        if not (
            isinstance(exc, httpx.HTTPStatusError)
            and exc.response.status_code in {403, 429}
        ):
            record_provider_failure(
                "eastmoney",
                f"sector {type(exc).__name__}: {exc}",
                failure_threshold=settings.EASTMONEY_FAILURE_THRESHOLD,
                cooldown_seconds=settings.EASTMONEY_COOLDOWN_SECONDS,
            )
        raise
    record_provider_success("eastmoney")

    rows = (body.get("data") or {}).get("diff") or []
    sectors = []
    for row in rows:
        name = str(row.get("f14") or "").strip()
        try:
            change_pct = float(row.get("f3"))
        except (TypeError, ValueError):
            continue
        if not name or not math.isfinite(change_pct):
            continue
        score, stars, status = _sector_score(change_pct)
        sectors.append({
            "name": name,
            "score": score,
            "change_pct": round(change_pct, 2),
            "stars": stars,
            "status": status,
        })
    if not sectors:
        raise ValueError("provider returned no sector rows")
    sectors.sort(key=lambda item: item["change_pct"], reverse=True)
    return {
        "sectors": sectors[:12],
        "data_source": "eastmoney_async",
        "is_live": True,
        "is_proxy": False,
        "refreshing": False,
        "stale": False,
        "message": "",
        "error": "",
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }


def _parse_tencent_sector_proxy(raw: bytes) -> dict:
    """Build an honest sector proxy map from one Tencent ETF quote response."""
    text = raw.decode("gb18030", errors="replace")
    sectors = []
    data_dates = []
    for line in text.split(";"):
        if "=" not in line or '"' not in line:
            continue
        key, payload = line.split("=", 1)
        symbol = key.strip().removeprefix("v_").lower()
        sector_name = _SECTOR_ETF_PROXIES.get(symbol)
        values = payload.split('"', 2)[1].split("~")
        if not sector_name or len(values) <= 32:
            continue
        try:
            change_pct = float(values[32])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(change_pct):
            continue
        exchange_timestamp = values[30].strip() if len(values) > 30 else ""
        if len(exchange_timestamp) >= 8 and exchange_timestamp[:8].isdigit():
            data_dates.append(
                f"{exchange_timestamp[:4]}-{exchange_timestamp[4:6]}-"
                f"{exchange_timestamp[6:8]}"
            )
        score, stars, status = _sector_score(change_pct)
        sectors.append({
            "name": sector_name,
            "score": score,
            "change_pct": round(change_pct, 2),
            "stars": stars,
            "status": status,
            "proxy_symbol": symbol,
            "proxy_name": values[1].strip() if len(values) > 1 else "",
        })
    if not sectors:
        raise ValueError("Tencent returned no usable sector ETF quotes")
    sectors.sort(key=lambda item: item["change_pct"], reverse=True)
    data_date = max(data_dates, default="")
    date_note = f"，行情日期 {data_date}" if data_date else ""
    return {
        "sectors": sectors,
        "data_source": "tencent_sector_etf_proxy",
        "is_live": True,
        "is_proxy": True,
        "refreshing": False,
        "stale": False,
        "message": (
            "东方财富板块接口暂不可用，已自动切换为腾讯行业 ETF 最新快照"
            f"（行业代理指标{date_note}）"
        ),
        "error": "",
        "data_date": data_date,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }


async def _fetch_tencent_sector_proxy_payload() -> dict:
    symbols = ",".join(_SECTOR_ETF_PROXIES)
    timeout = httpx.Timeout(connect=1.5, read=2.5, write=1.5, pool=1.0)
    headers = {
        "Accept": "*/*",
        "Referer": "https://gu.qq.com/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
        ),
    }
    wait = reserve_provider_request(
        "qt.gtimg.cn",
        min_interval_seconds=settings.PUBLIC_DATA_MIN_INTERVAL_SECONDS,
        jitter_seconds=settings.PUBLIC_DATA_JITTER_SECONDS,
    )
    if wait > 0:
        await asyncio.sleep(wait)
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            headers=headers,
            follow_redirects=True,
            trust_env=False,
            limits=httpx.Limits(
                max_connections=1,
                max_keepalive_connections=1,
                keepalive_expiry=15.0,
            ),
        ) as client:
            response = await client.get(f"https://qt.gtimg.cn/q={symbols}")
            response.raise_for_status()
    except httpx.HTTPError as exc:
        record_provider_failure(
            "qt.gtimg.cn",
            f"sector proxy {type(exc).__name__}: {exc}",
            failure_threshold=settings.PUBLIC_DATA_FAILURE_THRESHOLD,
            cooldown_seconds=settings.PUBLIC_DATA_COOLDOWN_SECONDS,
        )
        raise
    record_provider_success("qt.gtimg.cn")
    return _parse_tencent_sector_proxy(response.content)


async def _fetch_live_sector_payload() -> dict:
    """Prefer full boards, then use a clearly labelled real ETF proxy snapshot."""
    try:
        return await _fetch_eastmoney_sector_payload()
    except Exception as eastmoney_error:
        logger.info("Eastmoney sectors unavailable; trying Tencent proxy: %s", eastmoney_error)
        try:
            return await _fetch_tencent_sector_proxy_payload()
        except Exception as tencent_error:
            raise RuntimeError(
                "sector providers unavailable: "
                f"eastmoney={eastmoney_error}; tencent={tencent_error}"
            ) from tencent_error


async def _refresh_sector_cache() -> None:
    global _sector_cache, _sector_cache_expires_at
    try:
        _sector_cache = await _fetch_live_sector_payload()
        _sector_cache_expires_at = time.monotonic() + _SECTOR_CACHE_TTL_SECONDS
    except Exception as exc:
        logger.warning("Market Map sector refresh failed: %s", exc)
        _sector_cache = _sector_fallback(refreshing=False, error=str(exc))
        _sector_cache_expires_at = time.monotonic() + _SECTOR_FAILURE_CACHE_SECONDS


def _clear_sector_refresh_task(task: asyncio.Task[None]) -> None:
    global _sector_refresh_task
    if _sector_refresh_task is task:
        _sector_refresh_task = None


def _schedule_sector_refresh() -> None:
    global _sector_refresh_task
    if _sector_refresh_task is not None and not _sector_refresh_task.done():
        return
    task = asyncio.create_task(_refresh_sector_cache())
    _sector_refresh_task = task
    task.add_done_callback(_clear_sector_refresh_task)


@router.get("/sectors")
async def market_sectors(refresh: bool = False):
    """Return sector performance immediately and refresh it safely in the background."""
    global _sector_cache_expires_at
    now = time.monotonic()
    if refresh:
        _sector_cache_expires_at = 0.0
    if _sector_cache is not None and now < _sector_cache_expires_at:
        return dict(_sector_cache)

    _schedule_sector_refresh()
    if _sector_cache is not None:
        payload = dict(_sector_cache)
        payload.update({
            "refreshing": True,
            "stale": True,
            "message": "正在后台刷新，当前显示上次可用数据",
        })
        return payload
    return _sector_fallback(refreshing=True)


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
