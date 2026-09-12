"""Brief builders backed by real journal and market data."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from datetime import datetime
from time import monotonic
from typing import Any

from src.api.routes.journal_utils import (
    brief_date,
    get_journal_decisions,
    recommendation_from_score,
)
from src.infrastructure.market_data.vibe_provider import get_vibe_provider

_BRIEF_CACHE_SECONDS = 300
# The production journal query currently takes about four seconds on the
# persisted decision set.  Pre-market generation is not latency-sensitive,
# so allow it to finish instead of silently publishing an empty watchlist.
_BRIEF_DATABASE_TIMEOUT_SECONDS = 6.0
_BRIEF_OPTIONAL_SOURCE_TIMEOUT_SECONDS = 4.0
_brief_cache: tuple[float, str, dict[str, Any]] | None = None
_brief_refresh_task: asyncio.Task[dict] | None = None
_IN_PROGRESS_STATES = {"pending", "queued", "running", "in_progress", "collecting"}


async def _bounded(
    operation: Awaitable[Any],
    fallback: Any,
    timeout_seconds: float,
) -> Any:
    try:
        return await asyncio.wait_for(operation, timeout=timeout_seconds)
    except Exception:
        return fallback


async def _get_short_term_sentiment(vibe) -> tuple[dict[str, Any], dict[str, Any]]:
    """Prefer the native limit-up pools, then fall back to Vibe emotion data."""
    try:
        from src.infrastructure.market_data.eastmoney_emotion import (
            fetch_limit_up_sentiment,
        )

        native = await _bounded(fetch_limit_up_sentiment(), {}, 4.0)
        if isinstance(native, dict) and native.get("data"):
            return native["data"], dict(native.get("_meta") or {})
    except Exception:
        pass
    fallback = await _bounded(vibe.get_sentiment_lite(), {}, 4.0)
    return fallback, {"provider": "vibe", "source_layer": "vibe_fallback"}


def _sentiment_from_market(market: dict) -> dict:
    breadth = market.get("market_breadth") or {}
    up = int(breadth.get("up") or 0)
    down = int(breadth.get("down") or 0)
    total = up + down
    score = round((up / total) * 100, 1) if total else 0
    if score >= 65:
        label = "positive"
    elif score >= 45:
        label = "neutral"
    elif score > 0:
        label = "weak"
    else:
        label = "unknown"
    stars = 5 if score >= 80 else 4 if score >= 65 else 3 if score >= 45 else 2 if score > 0 else 0
    return {"score": score, "label": label, "stars": stars}


def _market_regime_from_overview(market: dict) -> dict[str, Any]:
    """Expose the overview classifier without turning missing data into a signal."""
    regime = market.get("market_regime") if isinstance(market, dict) else None
    if isinstance(regime, dict):
        return dict(regime)
    return {
        "state": "unknown",
        "score": 50,
        "confidence": 0.0,
        "as_of_date": "",
        "components": {},
        "reasons": ["market regime unavailable"],
        "source": "brief_fallback",
        "lookahead_safe": False,
    }


def _brief_data_state(
    component_status: dict[str, bool],
    pipeline_acceptance: dict[str, Any],
) -> str:
    """Distinguish an active collection from an empty or degraded snapshot."""
    if any(
        str(pipeline_acceptance.get(key) or "").strip().lower() in _IN_PROGRESS_STATES
        for key in ("acceptance_status", "process_status", "persistence_status", "evidence_status")
    ):
        return "collecting"
    if not any(component_status.values()):
        return "empty"
    if not all(component_status.values()):
        return "degraded"
    return "ready"


async def _build_real_brief_uncached(force_refresh: bool = False) -> dict:
    from src.api.routes.market_routes import market_overview, market_sectors

    global _brief_cache
    today = brief_date()
    if (
        not force_refresh
        and _brief_cache is not None
        and _brief_cache[1] == today
        and monotonic() - _brief_cache[0] < _BRIEF_CACHE_SECONDS
    ):
        return {**_brief_cache[2], "cached": True}

    decisions = await _bounded(
        asyncio.to_thread(get_journal_decisions, limit=30),
        [],
        _BRIEF_DATABASE_TIMEOUT_SECONDS,
    )
    vibe = get_vibe_provider()
    market, sectors_payload, sentiment_result, top_volume = await asyncio.gather(
        _bounded(market_overview(), {}, 4.0),
        _bounded(market_sectors(), {}, 3.0),
        _bounded(
            _get_short_term_sentiment(vibe),
            ({}, {"provider": "unavailable", "source_layer": "optional_timeout"}),
            _BRIEF_OPTIONAL_SOURCE_TIMEOUT_SECONDS,
        ),
        _bounded(
            vibe.get_top_volume_stocks(limit=20),
            [],
            _BRIEF_OPTIONAL_SOURCE_TIMEOUT_SECONDS,
        ),
    )
    sentiment_lite, sentiment_metadata = sentiment_result
    market_available = bool((market.get("_data") or {}).get("available"))
    market_regime = _market_regime_from_overview(market)
    hot_sectors = sectors_payload.get("sectors", [])[:5]
    sectors_live = bool(sectors_payload.get("is_live"))

    component_status = {
        "market": market_available,
        "sectors_live": sectors_live,
        "decision_journal": bool(decisions),
        "market_regime": bool((market or {}).get("market_regime")),
        "vibe_sentiment": bool(sentiment_lite),
        "native_sentiment": sentiment_metadata.get("provider") == "eastmoney",
        "vibe_volume": bool(top_volume),
    }
    from src.infrastructure.storage.market_database import market_db

    pipeline_audit = await _bounded(
        asyncio.to_thread(market_db.get_latest_pipeline_run_audit),
        {},
        _BRIEF_DATABASE_TIMEOUT_SECONDS,
    )
    pipeline_acceptance = {}
    if isinstance(pipeline_audit, dict):
        pipeline_acceptance = {
            "run_id": pipeline_audit.get("run_id", ""),
            "acceptance_status": pipeline_audit.get("acceptance_status", "unverified"),
            "process_status": pipeline_audit.get("process_status", "unverified"),
            "persistence_status": pipeline_audit.get("persistence_status", "unverified"),
            "evidence_status": pipeline_audit.get("evidence_status", "unverified"),
            "research_status": pipeline_audit.get("research_status", "unverified"),
            "execution_status": pipeline_audit.get("execution_status", "unverified"),
            "learning_status": pipeline_audit.get("learning_status", "unverified"),
            "reason_codes": pipeline_audit.get("reason_codes") or [],
            "target_trade_date": pipeline_audit.get("target_trade_date", ""),
        }
        component_status["pipeline_acceptance"] = (
            pipeline_acceptance.get("acceptance_status") == "pass"
        )

    sentiment = _sentiment_from_market(market)
    data_state = _brief_data_state(component_status, pipeline_acceptance)
    opportunities = []
    watchlist = []
    risks = []
    considered_stocks = []
    for d in decisions[:10]:
        score = float(d.get("ai_score") or 50)
        direction = str(d.get("direction") or "neutral")
        stored_recommendation = str(d.get("recommendation") or "").strip()
        market_price = float(d.get("market_price") or 0)
        market_pre_close = float(d.get("market_pre_close") or 0)
        reference_price = market_price if market_price > 0 else market_pre_close
        analysis = str(
            d.get("deep_analysis")
            or d.get("deep_thesis")
            or d.get("final_review_reason")
            or d.get("evidence")
            or stored_recommendation
            or "暂无可用分析"
        ).strip()
        item = {
            "stock_code": d.get("stock_code", ""),
            "stock_name": d.get("stock_name", ""),
            "score": round(score, 1),
            "direction": direction,
            "decision_status": d.get("decision_status", "unknown"),
            "raw_score": round(float(d.get("raw_ai_score") or score), 1),
            "score_guard_reasons": d.get("score_guard_reasons") or [],
            # Preserve the pipeline's final decision.  Rebuilding a BUY from
            # score alone turns a deliberate neutral/观望 decision into a
            # misleading buy badge in the dashboard.
            "recommendation": (
                stored_recommendation
                if stored_recommendation
                else recommendation_from_score(score, direction)
            ),
            "reason": d.get("recommendation") or d.get("evidence") or "Pipeline decision",
            "decision_date": d.get("decision_date", ""),
            "deep_rating": d.get("deep_rating", ""),
            "deep_analysis": d.get("deep_analysis", ""),
            "deep_analysis_available": bool(d.get("deep_analysis_available")),
            "analysis": analysis,
            "reference_price": round(reference_price, 3) if reference_price > 0 else None,
            "reference_price_date": d.get("market_price_date", ""),
            "reference_price_source": d.get("market_price_source", ""),
            "ranking_score": round(float(d.get("ranking_score") or score), 1),
            "primary_score": round(float(d.get("primary_score") or score), 1),
            "display_state": d.get("display_state", ""),
        }
        if len(considered_stocks) < 5 and not bool(d.get("publication_blocked")):
            considered_stocks.append(item)
        if score >= 65 and direction == "buy":
            opportunities.append(item)
        elif score >= 65 and direction == "neutral":
            watchlist.append(item)
        elif score < 50 or direction == "sell":
            display_name = item["stock_name"] or item["stock_code"]
            risks.append(f"{display_name}: score {score:.0f}, {direction}")

    if opportunities:
        top = opportunities[0]
        one_liner = (
            f"Top buy candidate: {top['stock_name']} "
            f"scores {top['score']:.0f}."
        )
    elif watchlist:
        one_liner = (
            f"今日暂无买入级机会；最高仅观察 {watchlist[0]['stock_name']}，"
            f"评分 {watchlist[0]['score']:.0f}。"
        )
    elif decisions:
        one_liner = "Pipeline has decisions, but no buy-grade opportunity is above 65 today."
    else:
        one_liner = "No real pipeline decisions yet. Run POST /ai-os/run-pipeline first."

    result = {
        "date": today,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "data_source": "decision_journal + market_overview + vibe_research",
        "data_status": {
            "available": any(component_status.values()),
            "degraded": not all(component_status.values()),
            "state": data_state,
            "components": component_status,
            "sentiment_source": sentiment_metadata.get("provider", ""),
            "pipeline_acceptance": pipeline_acceptance,
        },
        "pipeline_acceptance": pipeline_acceptance,
        "market_sentiment": sentiment,
        "market_regime": market_regime,
        "market_summary": (
            f"Market breadth: {market.get('market_breadth', {}).get('up', 0)} up / "
            f"{market.get('market_breadth', {}).get('down', 0)} down."
        ),
        "hot_sectors": hot_sectors,
        "top_opportunities": opportunities[:8],
        "considered_stocks": considered_stocks,
        "watchlist": watchlist[:8],
        "risk_warnings": risks[:5],
        "one_liner": one_liner,
        "portfolio": {
            "avg_score": round(
                sum(float(d.get("ai_score") or 50) for d in decisions) / len(decisions),
                1,
            )
            if decisions else 0,
            "position_count": len(decisions),
            "items": opportunities[:8],
        },
        "score_changes": {"upgraded": opportunities[:5], "downgraded": [], "stable": []},
        "market": {
            "sentiment_stars": sentiment["stars"],
            "sentiment_label": sentiment["label"],
            "sentiment_score": sentiment["score"],
            "up_count": market.get("market_breadth", {}).get("up", 0),
            "down_count": market.get("market_breadth", {}).get("down", 0),
            "total_volume": market.get("total_volume", 0),
            "northbound": market.get("northbound", {}),
            "indices": market.get("indices", {}),
            "market_regime": market_regime,
        },
        "recommendations": opportunities[:5],
        # Vibe Research 短线数据（客观公开榜单，非推荐）
        "short_term_sentiment": sentiment_lite,
        "top_volume_stocks": top_volume,
        "cached": False,
    }
    _brief_cache = (monotonic(), today, result)
    return result


async def build_real_brief(force_refresh: bool = False) -> dict:
    """Reuse one in-flight build so Dashboard and Daily Brief do not double-fetch."""
    global _brief_refresh_task
    today = brief_date()
    if (
        not force_refresh
        and _brief_cache is not None
        and _brief_cache[1] == today
        and monotonic() - _brief_cache[0] < _BRIEF_CACHE_SECONDS
    ):
        return {**_brief_cache[2], "cached": True}

    if _brief_refresh_task is not None and not _brief_refresh_task.done():
        return await _brief_refresh_task

    task = asyncio.create_task(_build_real_brief_uncached(force_refresh=force_refresh))
    _brief_refresh_task = task
    try:
        return await task
    finally:
        if _brief_refresh_task is task:
            _brief_refresh_task = None
