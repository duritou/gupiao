"""Scanner routes — v7.5: real data from baostock.

The scanner now:
  1. Gets real stock universe from RealDataProvider
  2. Fetches real daily bars from baostock for each stock
  3. Computes signals from real OHLCV data (no random numbers)
  4. Ranks candidates by computed fusion score
"""

import asyncio
from time import monotonic
from typing import Annotated, Any

from fastapi import APIRouter, Query

router = APIRouter(tags=["scanner"], prefix="/scanner")
_SCANNER_CACHE_TTL_SECONDS = 300
_LATEST_HISTORY_ROWS = 5000
_scanner_cache: dict[tuple[int, int], tuple[float, dict[str, Any]]] = {}


def _recommendation_explanation(item: dict[str, Any]) -> dict[str, Any]:
    """Expose the persisted explanation fields needed by recommendation cards."""
    return {
        "deep_analysis": item.get("deep_analysis") or "",
        "deep_thesis": item.get("deep_thesis") or "",
        "deep_trader_plan": item.get("deep_trader_plan") or "",
        "deep_analysis_error": item.get("deep_analysis_error") or "",
        "final_review_reason": item.get("final_review_reason") or "",
        "final_review_risk": item.get("final_review_risk") or "",
        "market_evidence_reasons": item.get("market_evidence_reasons") or [],
        "technical_score": item.get("technical_score"),
    }


@router.get("/latest")
async def latest_scanner_result(
    top_n: Annotated[int, Query(ge=1, le=100, description="Return top N candidates")] = 10,
):
    """Return the latest completed scan without starting a new full-market job."""
    from src.ai_os.recommendation_quality import (
        apply_decision_display_fields,
        is_publishable_recommendation,
        sort_decisions,
    )
    from src.ai_os.continuity_watchlist import build_continuity_watchlist
    from src.api.routes.journal_utils import latest_per_stock
    from src.infrastructure.storage.market_database import market_db

    # One full-market run can exceed 5,000 rows.  Keep enough history for the
    # observation-only carry-forward window instead of truncating the prior
    # session out of the response.
    # Keep the continuity window, but do not parse the entire journal on every
    # request.  Repeated same-day runs can otherwise make this read exceed the
    # API timeout even though the latest per-stock result is small.
    decisions = market_db.get_recent_decision_summaries(limit=_LATEST_HISTORY_ROWS)
    latest_date = max((str(item.get("decision_date") or "") for item in decisions), default="")
    latest = latest_per_stock([
        item for item in decisions if str(item.get("decision_date") or "") == latest_date
    ])
    for item in latest:
        apply_decision_display_fields(item)
    latest = sort_decisions(latest)
    latest_audit = await asyncio.to_thread(
        market_db.get_latest_pipeline_run_audit
    )
    continuity_watchlist = [
        item
        for item in build_continuity_watchlist(
            decisions,
            latest,
            current_date=latest_date,
        )
        # A name already present in the current run is not a carry-forward
        # record.  Keeping it here makes older clients render a prior label
        # beside a current technical row and can look like a stale buy signal.
        if item.get("current_rank") is None
    ]
    publishable = [
        item for item in latest if is_publishable_recommendation(item)
    ]
    blocked_deep = [
        item for item in latest
        if bool(item.get("deep_analysis_available"))
        and not is_publishable_recommendation(item)
    ]
    candidates = []
    for rank, item in enumerate(publishable[:top_n], start=1):
        candidates.append({
            "rank": rank,
            "stock_code": item.get("stock_code", ""),
            "stock_name": item.get("stock_name", ""),
            "fusion_score": float(item.get("action_score") or item.get("ai_score") or 0),
            "action_score": float(item.get("action_score") or item.get("ai_score") or 0),
            "primary_score": item.get("primary_score"),
            "primary_score_label": item.get("primary_score_label", "研究评分"),
            "research_score": item.get("research_score"),
            "ranking_score_label": item.get("ranking_score_label", "机会排名分"),
            "ranking_score": float(
                item.get("ranking_score")
                or item.get("raw_ai_score")
                or item.get("ai_score")
                or 0
            ),
            "direction": item.get("direction", "neutral"),
            "confidence": float(item.get("confidence") or 0),
            "recommendation": item.get("recommendation", ""),
            "display_state": item.get("display_state", "research_pending"),
            "display_state_label": item.get("display_state_label", "分析待完成"),
            "recommendation_tier": item.get("recommendation_tier", ""),
            "decision_status": item.get("decision_status", "unknown"),
            "score_guarded": bool(item.get("score_guarded")),
            "score_guard_reasons": item.get("score_guard_reasons") or [],
            "market_evidence_sources": item.get("market_evidence_sources") or [],
            "evidence_enrichment": item.get("evidence_enrichment") or {},
            "quote_enrichment_status": item.get("quote_enrichment_status"),
            "quote_enrichment_reason": item.get("quote_enrichment_reason"),
            "score_display": item.get("score_display") or {},
            "deep_analysis_available": bool(item.get("deep_analysis_available")),
            "data_source": "decision_journal",
            "score_breakdown": {
                "macd": float(item.get("macd_score") or 50),
                "rsi": float(item.get("rsi_score") or 50),
                "kdj": float(item.get("kdj_score") or 50),
                "ma": float(item.get("ma_score") or 50),
                "volume": float(item.get("volume_score") or 50),
            },
            **_recommendation_explanation(item),
        })
    blocked_candidates = []
    for rank, item in enumerate(blocked_deep[:10], start=1):
        blocked_candidates.append({
            "rank": rank,
            "stock_code": item.get("stock_code", ""),
            "stock_name": item.get("stock_name", ""),
            "fusion_score": float(item.get("action_score") or item.get("ai_score") or 0),
            "action_score": float(item.get("action_score") or item.get("ai_score") or 0),
            "ranking_score": float(
                item.get("ranking_score")
                or item.get("raw_ai_score")
                or item.get("ai_score")
                or 0
            ),
            "primary_score": item.get("primary_score"),
            "primary_score_label": item.get("primary_score_label", "研究评分"),
            "research_score": item.get("research_score"),
            "ranking_score_label": item.get("ranking_score_label", "机会排名分"),
            "direction": item.get("direction", "neutral"),
            "confidence": float(item.get("confidence") or 0),
            "recommendation": item.get("recommendation", ""),
            "display_state": item.get("display_state", "research_pending"),
            "display_state_label": item.get("display_state_label", "分析待完成"),
            "deep_rating": item.get("deep_rating", ""),
            "decision_status": item.get("decision_status", "unknown"),
            "score_guarded": bool(item.get("score_guarded")),
            "score_guard_reasons": item.get("score_guard_reasons") or [],
            "market_evidence_sources": item.get("market_evidence_sources") or [],
            "evidence_enrichment": item.get("evidence_enrichment") or {},
            "quote_enrichment_status": item.get("quote_enrichment_status"),
            "quote_enrichment_reason": item.get("quote_enrichment_reason"),
            "score_display": item.get("score_display") or {},
            "recommendation_tier": item.get("recommendation_tier", "research_candidate"),
            "blocked_reasons": item.get("publication_block_reasons")
            or item.get("score_guard_reasons")
            or [],
            "deep_analysis_available": True,
            "data_source": "decision_journal + strategy_decision",
            "score_breakdown": {
                "macd": float(item.get("macd_score") or 50),
                "rsi": float(item.get("rsi_score") or 50),
                "kdj": float(item.get("kdj_score") or 50),
                "ma": float(item.get("ma_score") or 50),
                "volume": float(item.get("volume_score") or 50),
            },
            **_recommendation_explanation(item),
        })
    return {
        "status": "ok" if candidates else "no_valid_recommendation",
        "scan_date": latest_date,
        "total_scanned": len(latest),
        "universe_count": len(latest),
        "coverage_ratio": 1.0 if latest else 0.0,
        "coverage_complete": bool(latest),
        "ranking_scope": "latest_persisted_pipeline_decisions",
        "run_id": (latest_audit or {}).get("run_id", ""),
        "ranking_method": "raw_ranking_score_with_evidence_gate",
        "candidates_found": len(publishable),
        "recommendation_available": bool(candidates),
        "blocked_candidates_found": len(blocked_deep),
        "blocked_candidates": blocked_candidates,
        "cached": True,
        "data_source": "decision_journal",
        "data_note": (
            f"显示 {latest_date} 最近一次已完成 AI Pipeline 中通过深度分析和证据门槛的结果；"
            "数据不足或未完成深度分析的股票不会进入推荐列表。"
            if latest_date else "尚无已完成扫描结果。"
        ),
        "blocked_note": (
            "最近一次扫描没有可发布的可靠推荐：请检查市场数据新鲜度、远程数据源和深度分析状态。"
            if latest_date and not candidates else ""
        ),
        "candidates": candidates,
        "continuity_watchlist": continuity_watchlist,
        "stage_acceptance": {
            key: (latest_audit or {}).get(key, "unverified")
            for key in (
                "acceptance_status", "process_status", "persistence_status",
                "evidence_status", "research_status", "execution_status",
                "learning_status", "reason_codes", "target_trade_date",
            )
        },
    }


@router.post("/run")
async def run_scanner(
    top_n: Annotated[int, Query(ge=1, le=100, description="Return top N candidates")] = 10,
    pool_size: Annotated[int, Query(ge=1, le=6000, description="Stocks to scan")] = 50,
):
    """Run market scan on real stock data.

    Uses baostock daily bars. Data is T-1 (yesterday's close).
    This is a research system, not HFT — T-1 is sufficient for
    MACD/RSI/KDJ/MA/Volume signal computation.
    """
    from src.infrastructure.market_data.real_data_provider import real_data

    cache_key = (pool_size, top_n)
    cached = _scanner_cache.get(cache_key)
    if cached and monotonic() - cached[0] < _SCANNER_CACHE_TTL_SECONDS:
        return {**cached[1], "cached": True}

    t0 = monotonic()

    # 1. Get real stock universe
    universe = (await real_data.get_stock_universe(min_count=pool_size))[:pool_size]
    universe_count = len(universe)

    # 2. Fetch real K-line data (parallel would be better, but baostock
    #    needs sequential access to avoid connection issues)
    candidates = []
    scanned = 0

    for stock in universe:
        code = stock["code"]
        name = stock.get("name", code)

        try:
            bars = await real_data.get_daily_bars(code, days=250)
            if not bars or len(bars) < 20:
                scanned += 1
                continue

            # 3. Compute real signals from real K-lines
            sig = real_data.compute_signals(code, name, bars)
            scanned += 1

            # Only include stocks with sufficient signal strength
            if abs(sig.fusion_score - 50) < 2:
                continue

            candidates.append({
                "stock_code": sig.stock_code,
                "stock_name": sig.stock_name,
                "fusion_score": sig.fusion_score,
                "direction": sig.direction,
                "confidence": sig.confidence,
                "data_days": sig.data_days,
                "data_source": sig.data_source,
                "score_breakdown": {
                    "macd": sig.macd_score,
                    "rsi": sig.rsi_score,
                    "kdj": sig.kdj_score,
                    "ma": sig.ma_score,
                    "volume": sig.volume_score,
                    "boll": sig.boll_score,
                },
            })
        except Exception:
            scanned += 1
            continue

    # 4. Sort by fusion score
    candidates.sort(key=lambda c: c["fusion_score"], reverse=True)
    for i, c in enumerate(candidates[:top_n]):
        c["rank"] = i + 1

    elapsed_ms = int((monotonic() - t0) * 1000)

    result = {
        "total_scanned": scanned,
        "pool_size": pool_size,
        "universe_count": universe_count,
        "coverage_ratio": round(scanned / universe_count, 3) if universe_count else 0,
        "coverage_complete": universe_count > 0 and scanned >= universe_count,
        "ranking_scope": "full_local_a_share_universe",
        "ranking_method": "technical_rule_score",
        "result_type": "technical_watchlist",
        "recommendation_available": False,
        "candidates_found": len(candidates),
        "duration_ms": elapsed_ms,
        "cached": False,
        "data_source": "baostock (T-1 daily close)",
        "data_note": (
            f"本地沪深A股池共 {universe_count} 只，本次成功扫描 {scanned} 只；"
            "按最近交易日收盘后的技术规则分排序，非实时行情；"
            "这不是经过AI深度分析的推荐列表。"
        ),
        "candidates": candidates[:top_n],
    }
    _scanner_cache[cache_key] = (monotonic(), result)
    return result
