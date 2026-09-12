"""Decision Center + Evidence Quality + Research Case Library API 鈥?v8.0.

v7.5 data migration: /today now uses real baostock data.
"""

from datetime import date

# This module also exposes the auditable next-session market-learning status.
from fastapi import APIRouter, Query

from src.api.routes.journal_utils import (
    latest_per_stock,
    recommended_codes,
    stock_name_from_journal,
)
from src.explain.calibration import calibration_engine
from src.explain.case_retrieval import case_retriever
from src.explain.committee import committee
from src.explain.decision_center import decision_center
from src.explain.evidence_quality import (
    archive_case,
    get_case,
    get_case_library_stats,
    get_research_coverage,
    grader,
)
from src.explain.governance import governance_engine
from src.explain.portfolio_intelligence import portfolio_intelligence
from src.explain.premortem import premortem_engine

router = APIRouter(tags=["decision"], prefix="/decision")


@router.post("/backfill")
async def backfill_decisions(
    min_calendar_days: int = Query(9, ge=1, le=60, description="决策距今最少 N 个日历天(默认 9 ≈ 5 交易日 + 缓冲)"),
):
    """手动触发决策结果回填(后台执行,立即返回)。

    对到期未验证决策(outcome_known=0 且 decision_date 距今 >= min_calendar_days),
    对比决策后 5 个交易日真实收益(个股 vs 沪深300 基准),回填 was_correct/actual_return,
    并喂给 Calibration。幂等,可重复执行。
    """
    import asyncio

    from src.explain.outcome_backfiller import _backfill_state, backfill_async, get_backfill_status

    if _backfill_state["running"]:
        return {"status": "already_running", **get_backfill_status()}

    asyncio.create_task(backfill_async(min_calendar_days))
    return {
        "status": "started",
        "min_calendar_days": min_calendar_days,
        "n_trading_days": 5,
        "benchmark": "沪深300 (sh.000300)",
        "note": "后台回填中,用 GET /decision/backfill/status 查进度",
    }


@router.get("/backfill/status")
async def backfill_status():
    """查询决策回填进度 + 当前决策统计。"""
    from src.explain.outcome_backfiller import get_backfill_status
    from src.infrastructure.storage.market_database import market_db
    profiles = {
        str(horizon): market_db.get_market_learning_profile(horizon_days=horizon)
        for horizon in (1, 5, 20)
    }
    return {
        **get_backfill_status(),
        "decision_stats": market_db.get_decision_stats(),
        "market_learning": profiles["1"],
        "market_learning_horizons": profiles,
    }


@router.get("/market-learning")
async def market_learning_status():
    """Show what the real next-session feedback loop has actually learned."""
    from src.infrastructure.storage.market_database import market_db

    profiles = {
        horizon: market_db.get_market_learning_profile(horizon_days=horizon)
        for horizon in (1, 5, 20)
    }
    profile = profiles[1]
    recent = [
        item for item in market_db.get_learning_log(limit=20)
        if item.get("category") in {"remote_market_snapshot", "market_feedback"}
    ]
    return {
        "status": "learning" if profile["total_observations"] else "collecting_samples",
        "data_policy": "remote daily discovery; SQLite audit cache/fallback",
        "learning_policy": {
            "horizon": "next trading session vs CSI 300",
            "decisive_directions": ["buy", "sell"],
            "symbol_min_observations": 2,
            "symbol_adjustment_cap": 8,
            "source_min_observations": 3,
            "source_adjustment_cap": 3,
        },
        "profile": profile,
        "horizon_profiles": {str(horizon): value for horizon, value in profiles.items()},
        "active_horizons": [
            horizon for horizon, value in profiles.items()
            if value.get("decisive_observations", 0) >= {1: 2, 5: 20, 20: 40}[horizon]
        ],
        "recent_daily_records": recent[:6],
    }

# Configurable watchlist 鈥?user's tracked stocks
# In future, this comes from user settings / CSV import
@router.get("/today")
async def daily_decisions():
    """Today's prioritized decision list 鈥?reads from real decision journal.

    Decisions come from the AI Pipeline Runner (POST /ai-os/run-pipeline).
    Run the pipeline first to populate the journal, then this endpoint
    returns the latest decisions ranked by AI score.
    """
    from src.ai_os.recommendation_quality import (
        apply_decision_display_fields,
        is_publishable_recommendation,
        sort_decisions,
    )
    from src.infrastructure.storage.market_database import market_db

    today = date.today().isoformat()
    all_decisions = latest_per_stock(
        market_db.get_decisions_for_date(today, limit=5000)
    )
    for item in all_decisions:
        apply_decision_display_fields(item)
    decisions = sort_decisions(
        [item for item in all_decisions if is_publishable_recommendation(item)]
    )
    journal_stats = market_db.get_decision_stats()

    if not decisions:
        return {
            "date": today,
            "total_items": 0,
            "urgent_count": 0,
            "blocked_count": len(all_decisions),
            "recommendation_available": False,
            "data_source": "decision_journal (SQLite)",
            "data_note": (
                "今天没有通过深度分析和证据门槛的有效推荐；"
                "数据不足的候选仅保留在审计记录中。"
                if all_decisions else
                "No decisions were produced today. Run POST /ai-os/run-pipeline to refresh."
            ),
            "decisions": [],
            "summary": (
                "今天没有可发布的可靠推荐。"
                if all_decisions else
                "The AI decision pipeline has not produced recommendations yet."
            ),
        }

    # Format for frontend consumption
    items = []
    for d in decisions:
        score = d.get("primary_score")
        if score is None:
            score = d.get("action_score", d.get("ai_score", 50))
        if score >= 80:
            urgency = "today"
            emoji = "馃煝"
        elif score >= 65:
            urgency = "this_week"
            emoji = "馃煛"
        elif score >= 50:
            urgency = "monitor"
            emoji = "馃煚"
        else:
            urgency = "monitor"
            emoji = "馃敶"

        items.append({
            "rank": 0,
            "stock_code": d.get("stock_code", ""),
            "stock_name": d.get("stock_name", ""),
            "ai_score": round(score, 1),
            "primary_score": d.get("primary_score", score),
            "primary_score_label": d.get("primary_score_label", "研究评分"),
            "research_score": d.get("research_score"),
            "ranking_score_label": d.get("ranking_score_label", "机会排名分"),
            "scanner_score": d.get("scanner_score"),
            "ranking_score": round(
                float(d.get("ranking_score") or d.get("raw_ai_score") or score), 1
            ),
            "action_score": round(float(d.get("action_score") or score), 1),
            "score_display": d.get("score_display") or {},
            "preselection_base_score": d.get("preselection_base_score"),
            "preselection_adjusted_score": d.get("preselection_adjusted_score"),
            "deep_base_score": d.get("deep_base_score"),
            "deep_score": d.get("deep_score"),
            "deep_kline_evidence": d.get("deep_kline_evidence") or {},
            "score_lineage": d.get("score_lineage") or {},
            "recommendation": d.get("recommendation", ""),
            "display_state": d.get("display_state", "research_pending"),
            "display_state_label": d.get("display_state_label", "分析待完成"),
            "recommendation_emoji": emoji,
            "urgency": urgency,
            "direction": d.get("direction", "neutral"),
            "decision_status": d.get("decision_status", "unknown"),
            "recommendation_tier": d.get("recommendation_tier", "research_complete"),
            "score_guarded": bool(d.get("score_guarded")),
            "score_guard_reasons": d.get("score_guard_reasons") or [],
            "deep_rating": d.get("deep_rating") or "",
            "deep_analysis_available": bool(d.get("deep_analysis_available")),
            "final_review_available": bool(d.get("final_review_available")),
            "final_review_verdict": d.get("final_review_verdict") or "",
            "final_buy_approved": d.get("final_buy_approved"),
            "pre_gate_direction": d.get("pre_gate_direction", ""),
            "flow_state": d.get("flow_state", d.get("flow_status", "")),
            "flow_sources": d.get("flow_sources") or [],
            "fallback_attempted": bool(d.get("fallback_attempted")),
            "fallback_status": d.get("fallback_status", ""),
            "gate_reasons": d.get("gate_reasons") or [],
            "non_flow_gates_passed": bool(d.get("non_flow_gates_passed")),
            "execution_disposition": d.get("execution_disposition", "blocked"),
            "execution_block_reason": d.get("execution_block_reason", ""),
            "execution_status_label": d.get(
                "execution_status_label", "等待执行确认"
            ),
            "execution_quote_verified": bool(d.get("execution_quote_verified")),
            "market_evidence_sources": d.get("market_evidence_sources") or [],
            "market_evidence_reasons": d.get("market_evidence_reasons") or [],
            "evidence_enrichment": d.get("evidence_enrichment") or {},
            "quote_enrichment_status": d.get("quote_enrichment_status"),
            "quote_enrichment_reason": d.get("quote_enrichment_reason"),
            "confidence": round(d.get("confidence", 0), 2),
            "primary_reason": d.get("recommendation", ""),
            "evidence_count": sum(1 for s in [
                d.get("macd_score", 50), d.get("rsi_score", 50),
                d.get("kdj_score", 50), d.get("ma_score", 50),
                d.get("volume_score", 50),
            ] if s and abs(s - 50) > 10),
            "bull_points": [],
            "bear_points": [],
            "net_score": score - 50,
        })

    for i, item in enumerate(items):
        item["rank"] = i + 1

    return {
        "date": today,
        "total_items": len(items),
        "blocked_count": len(all_decisions) - len(decisions),
        "recommendation_available": bool(items),
        "urgent_count": sum(1 for d in items if d["urgency"] == "today"),
        "data_source": "decision_journal (SQLite, real AI pipeline)",
        "data_note": (
            f"Today's AI pipeline produced {len(items)} publishable decisions; "
            f"Journal total: {journal_stats['total_decisions']}, "
            f"verified: {journal_stats['verified_decisions']}."
        ),
        "decisions": items,
        "summary": (
            f"AI pipeline has produced {journal_stats['total_decisions']} real decisions. "
            f"Run POST /ai-os/run-pipeline to refresh today's decisions."
        ),
    }


def _generate_summary(decisions) -> str:
    urgent = [d for d in decisions if d.urgency == "today"]
    if urgent:
        return f"{len(urgent)} urgent recommendations need attention. Top priority: {urgent[0].stock_name}."
    return f"{len(decisions)} recommendations based on real daily market data."


@router.get("/evidence-grade/{code}")
async def evidence_grade(code: str, score: float = Query(50), direction: str = Query("buy"), confidence: float = Query(0.8)):
    """Grade the evidence quality for a specific recommendation."""
    quality, case = grader.grade_recommendation(
        stock_code=code, stock_name=stock_name_from_journal(code),
        ai_score=score, direction=direction, confidence=confidence,
        official_sources=1, commercial_sources=1, community_sources=1,
        cross_verified=3, total_evidence=5,
    )
    archive_case(case)
    return {
        "evidence_grade": quality.to_dict(),
        "case": case.to_dict(),
    }


@router.get("/cases")
async def case_library(limit: int = Query(30, ge=1, le=100)):
    """Research Case Library 鈥?all tracked AI recommendations."""
    from src.explain.evidence_quality import _case_history
    _seed_cases_if_empty()
    cases = sorted(_case_history, key=lambda c: c.created_at, reverse=True)[:limit]
    return {
        "cases": [c.to_dict() for c in cases],
        "stats": get_case_library_stats(),
        "coverage": get_research_coverage(),
    }


def _seed_cases_if_empty():
    """No synthetic case seeding. Case library only reflects real archived cases."""
    return

@router.get("/cases/{case_id}")
async def case_detail(case_id: str):
    """Get a single research case by ID."""
    case = get_case(case_id)
    if not case:
        return {"error": "case not found", "case_id": case_id}
    return case.to_dict()


# ================================================================
# v9.0 Portfolio Intelligence
# ================================================================

@router.get("/confidence-decomposed")
async def decomposed_confidence(
    confidence: float = Query(0.82),
    data_trust: float = Query(0.85),
    model_version: str = Query("v6.0"),
    user_win_rate: float = Query(0.65),
):
    """Decompose AI confidence into its components."""
    result = portfolio_intelligence.decompose_confidence(
        ai_confidence=confidence,
        data_trust_score=data_trust,
        model_version=model_version,
        user_win_rate=user_win_rate,
    )
    return result.to_dict()


@router.get("/counterfactual/{code}")
async def counterfactual(code: str, base_score: float = Query(85)):
    """What drives the score? Remove each factor to see impact."""
    name = stock_name_from_journal(code)
    impacts = portfolio_intelligence.counterfactual_analysis(name, base_score)
    return {
        "stock_code": code,
        "stock_name": name,
        "base_score": base_score,
        "factors": [f.to_dict() for f in impacts],
        "critical_factors": [f.factor for f in impacts if f.is_critical],
        "insight": _counterfactual_insight(impacts),
    }


def _counterfactual_insight(impacts) -> str:
    if not impacts:
        return ""
    critical = [f for f in impacts if f.is_critical]
    if critical:
        return f"Critical drivers: {', '.join(f.factor for f in critical)}. Removing any one would materially reduce the score."
    return "The score is supported by multiple balanced factors, with no single decisive driver."


@router.get("/allocate")
async def allocate_capital(cash_reserve: float = Query(20.0), risk: str = Query("moderate")):
    """Optimal capital allocation 鈥?driven by real signal scores."""
    from src.infrastructure.market_data.real_data_provider import real_data

    candidates = []
    for code in recommended_codes(limit=30):
        name = stock_name_from_journal(code)
        try:
            bars = await real_data.get_daily_bars(code, days=250)
            if bars and len(bars) >= 20:
                sig = real_data.compute_signals(code, name, bars)
                candidates.append({
                    "stock_code": code,
                    "stock_name": name,
                    "ai_score": sig.fusion_score,
                    "risk_level": "medium",
                    "user_win_rate": 0,  # No user history yet
                })
        except Exception:
            pass

    allocation = portfolio_intelligence.allocate_capital(
        candidates, cash_reserve_pct=cash_reserve, user_risk=risk,
    )
    return allocation.to_dict()


# ================================================================
# v10.0 Investment Committee
# ================================================================

# ================================================================
# Calibration + Annual Report
# ================================================================

@router.get("/calibration")
async def calibration():
    """Confidence calibration 鈥?how well does AI confidence match reality?"""
    from src.explain.evidence_quality import _case_history
    _seed_cases_if_empty()
    report = calibration_engine.compute_calibration(_case_history)
    return report.to_dict()


@router.get("/annual-report")
async def annual_report(year: int = Query(2026)):
    """AI Annual Report 鈥?like a fund's annual performance report."""
    from src.explain.evidence_quality import _case_history
    _seed_cases_if_empty()
    cal = calibration_engine.compute_calibration(_case_history)
    report = calibration_engine.generate_annual_report(_case_history, year, cal)
    return report.to_dict()


@router.get("/committee/{code}")
async def committee_evaluation(
    code: str,
    base_score: float = Query(70.0),
    position_pct: float = Query(15.0, description="Current position % if held"),
):
    """Investment Committee 鈥?5 AI analysts debate and vote."""
    name = stock_name_from_journal(code)

    decision = committee.evaluate(
        stock_code=code, stock_name=name,
        base_score=base_score,
        portfolio_context={"position_pct": position_pct, "concentration_risk": 55, "volatility": 45},
        user_history={"win_rate": 0.72, "trades": 5},
    )
    return decision.to_dict()


@router.get("/compare")
async def compare_opportunity(
    code_a: str = Query(""), code_b: str = Query(""),
    score_a: float = Query(92), score_b: float = Query(87),
):
    """Why stock A over stock B? Pairwise comparison."""
    if not code_a or not code_b:
        codes = recommended_codes(limit=2)
        if len(codes) < 2:
            return {
                "status": "insufficient_data",
                "message": "No pair of daily AI recommendations is available.",
            }
        code_a, code_b = codes[0], codes[1]
    name_a = stock_name_from_journal(code_a)
    name_b = stock_name_from_journal(code_b)
    result = portfolio_intelligence.compare_opportunity_cost(
        name_a, score_a, name_b, score_b,
    )
    return result.to_dict()


# ================================================================
# v11.0 Decision Governance 鈥?audit, pre-mortem, similar cases
# ================================================================

@router.get("/govern/{code}")
async def governance_pipeline(
    code: str,
    base_score: float = Query(70.0),
    position_pct: float = Query(15.0, description="Current position % if held"),
):
    """Full governance pipeline for a stock decision.

    Runs the complete v11.0 pipeline:
      1. Investment Committee evaluation (5 analysts debate + vote)
      2. Decision Governance audit (7 independent checks)
      3. Pre-mortem analysis (top 5 failure modes)
      4. Similar Case Retrieval (historical pattern matching)

    Returns all four components in a single response with an executive summary.
    """
    from src.explain.evidence_quality import _case_history
    from src.user_model.engine import get_user_model_engine
    _seed_cases_if_empty()

    name = stock_name_from_journal(code)

    # Step 1: Committee evaluation
    decision = committee.evaluate(
        stock_code=code, stock_name=name,
        base_score=base_score,
        portfolio_context={
            "position_pct": position_pct,
            "concentration_risk": 55, "volatility": 45,
        },
        user_history={"win_rate": 0.72, "trades": 5},
    )

    # Step 2: Build supporting data for governance
    evidence_quality, _ = grader.grade_recommendation(
        stock_code=code, stock_name=name,
        ai_score=decision.composite_score,
        direction=decision.composite_direction,
        confidence=decision.composite_confidence,
    )
    dc = portfolio_intelligence.decompose_confidence(
        ai_confidence=decision.composite_confidence,
    )
    user_engine = get_user_model_engine()
    user_profile = user_engine.generate_profile()
    cal = calibration_engine.compute_calibration(_case_history)

    # Step 3: Similar case retrieval (needed by governance)
    similar = case_retriever.find_similar(
        stock_code=code, stock_name=name,
        ai_score=decision.composite_score,
        direction=decision.composite_direction,
        evidence_grade=decision.decision_quality_grade,
    )

    # Step 4: Governance audit
    gov_result = governance_engine.audit(
        stock_code=code, stock_name=name,
        committee_decision=decision,
        user_profile=user_profile,
        decomposed_confidence=dc,
        evidence_quality=evidence_quality,
        calibration_report=cal,
        similar_cases_report=similar,
        position_pct=position_pct,
    )

    # Step 5: Pre-mortem
    pre_mortem = premortem_engine.analyze(
        stock_code=code, stock_name=name,
        committee_decision=decision,
    )

    # Executive summary
    risk_text = (
        f"Top pre-mortem risk: {pre_mortem.top_risk} "
        f"({pre_mortem.failure_modes[0].probability_pct:.0f}% probability). "
        if pre_mortem.failure_modes else ""
    )
    summary = (
        f"{name} ({code}): committee {decision.vote_result} "
        f"({decision.yes_votes}:{decision.no_votes}), composite score {decision.composite_score:.0f}. "
        f"Governance {gov_result.overall_verdict} "
        f"({gov_result.pass_count} pass/{gov_result.warn_count} warn/{gov_result.fail_count} fail). "
        f"{risk_text}"
        f"Found {similar.total_similar} similar historical cases "
        f"(win rate {similar.aggregate_win_rate:.0%})."
    )

    return {
        "stock_code": code,
        "stock_name": name,
        "pipeline_version": "v11.0",
        "generated_at": decision.decided_at,
        "committee": decision.to_dict(),
        "governance": gov_result.to_dict(),
        "pre_mortem": pre_mortem.to_dict(),
        "similar_cases": similar.to_dict(),
        "executive_summary": summary,
    }


@router.get("/premortem/{code}")
async def premortem_analysis(
    code: str,
    score: float = Query(70.0),
    direction: str = Query("buy"),
):
    """Pre-mortem analysis 鈥?identify most likely failure modes before execution.

    Returns top 5 failure modes with probabilities, trigger conditions,
    early warning signals, and mitigation suggestions.
    """
    name = stock_name_from_journal(code)
    report = premortem_engine.analyze(
        stock_code=code, stock_name=name,
        ai_score=score, direction=direction,
    )
    return report.to_dict()


@router.get("/similar-cases/{code}")
async def similar_cases(
    code: str,
    score: float = Query(70.0),
    direction: str = Query("buy"),
    top_n: int = Query(10, ge=1, le=50),
):
    """Find historically similar cases from the Research Case Library.

    Multi-dimensional similarity scoring across sector, score range,
    signal pattern, direction, and evidence quality.

    Returns top matches with known outcomes and aggregate statistics 鈥?    not AI guessing, but historical evidence.
    """
    from src.explain.evidence_quality import _case_history
    _seed_cases_if_empty()

    name = stock_name_from_journal(code)
    report = case_retriever.find_similar(
        stock_code=code, stock_name=name,
        ai_score=score, direction=direction,
        limit=top_n,
    )
    return report.to_dict()
