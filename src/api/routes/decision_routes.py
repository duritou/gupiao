"""Decision Center + Evidence Quality + Research Case Library API — v8.0."""

from fastapi import APIRouter, Query

from src.explain.decision_center import decision_center
from src.explain.evidence_quality import (
    grader, archive_case, get_case, get_case_library_stats, get_research_coverage,
)
from src.explain.portfolio_intelligence import portfolio_intelligence
from src.explain.committee import committee
from src.explain.calibration import calibration_engine
from src.shared.mock_data import STOCK_NAMES, generate_stock_pool, mock_signal_result

router = APIRouter(tags=["decision"], prefix="/decision")


@router.get("/today")
async def daily_decisions():
    """Today's prioritized decision list with Bull/Bear analysis.

    Combines portfolio positions + scanner candidates + personal history
    → ranked actionable items.
    """
    import hashlib
    import random
    from datetime import date

    today_seed = int(hashlib.md5(date.today().isoformat().encode()).hexdigest()[:8], 16)
    rng = random.Random(today_seed)

    # Generate portfolio
    portfolio = [
        {"stock_code": "688256.SH", "stock_name": "寒武纪", "ai_score": 92, "weight_pct": 25, "ai_direction": "buy"},
        {"stock_code": "002371.SZ", "stock_name": "北方华创", "ai_score": 88, "weight_pct": 20, "ai_direction": "buy"},
        {"stock_code": "300308.SZ", "stock_name": "中际旭创", "ai_score": 85, "weight_pct": 18, "ai_direction": "buy"},
        {"stock_code": "688981.SH", "stock_name": "中芯国际", "ai_score": 72, "weight_pct": 15, "ai_direction": "neutral"},
        {"stock_code": "600519.SH", "stock_name": "贵州茅台", "ai_score": 58, "weight_pct": 22, "ai_direction": "neutral"},
    ]

    # Generate scanner candidates
    pool = generate_stock_pool(20)
    candidates = []
    for i, p in enumerate(pool[:8]):
        if p["code"] in [pos["stock_code"] for pos in portfolio]:
            continue
        sig = mock_signal_result(p["code"], [])
        candidates.append({
            "stock_code": p["code"],
            "stock_name": p.get("name", STOCK_NAMES.get(p["code"], p["code"])),
            "fusion_score": sig["fusion_score"],
            "direction": sig["direction"],
        })

    # User history (simulated personal memory)
    user_history = {
        "688256.SH": {"trades": 6, "wins": 5, "last_action": "2026-06-28 买入", "total_return": 31.2},
        "002371.SZ": {"trades": 4, "wins": 3, "last_action": "2026-07-02 加仓", "total_return": 18.5},
        "600519.SH": {"trades": 8, "wins": 3, "last_action": "2026-06-15 减仓", "total_return": -12.3},
        "000725.SZ": {"trades": 2, "wins": 1, "last_action": "2026-05-20 卖出", "total_return": 5.8},
    }

    decisions = decision_center.generate_daily_decisions(
        scanner_candidates=candidates,
        portfolio_positions=portfolio,
        user_history=user_history,
    )

    return {
        "date": date.today().isoformat(),
        "total_items": len(decisions),
        "urgent_count": sum(1 for d in decisions if d.urgency == "today"),
        "decisions": [d.to_dict() for d in decisions],
        "summary": _generate_summary(decisions),
    }


def _generate_summary(decisions) -> str:
    urgent = [d for d in decisions if d.urgency == "today"]
    if urgent:
        return f"今日{len(urgent)}条紧急建议需要关注。优先级最高: {urgent[0].stock_name}。"
    return f"今日{len(decisions)}条建议，暂无紧急操作。保持现有仓位。"


@router.get("/evidence-grade/{code}")
async def evidence_grade(code: str, score: float = Query(50), direction: str = Query("buy"), confidence: float = Query(0.8)):
    """Grade the evidence quality for a specific recommendation."""
    quality, case = grader.grade_recommendation(
        stock_code=code, stock_name=STOCK_NAMES.get(code, code),
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
    """Research Case Library — all tracked AI recommendations."""
    from src.explain.evidence_quality import _case_history
    _seed_cases_if_empty()
    cases = sorted(_case_history, key=lambda c: c.created_at, reverse=True)[:limit]
    return {
        "cases": [c.to_dict() for c in cases],
        "stats": get_case_library_stats(),
        "coverage": get_research_coverage(),
    }


def _seed_cases_if_empty():
    """Seed case library with realistic historical cases for demonstration."""
    from src.explain.evidence_quality import _case_history
    if _case_history:
        return
    import hashlib, random
    from datetime import datetime, timedelta
    rng = random.Random(42)
    now = datetime.now()

    stocks = [
        ("688256.SH", "寒武纪"), ("002371.SZ", "北方华创"), ("300308.SZ", "中际旭创"),
        ("688981.SH", "中芯国际"), ("600519.SH", "贵州茅台"), ("000725.SZ", "京东方A"),
        ("300750.SZ", "宁德时代"), ("000858.SZ", "五粮液"), ("002475.SZ", "立讯精密"),
        ("000977.SZ", "浪潮信息"), ("688012.SH", "中微公司"), ("002049.SZ", "紫光国微"),
    ]

    for i, (code, name) in enumerate(stocks):
        for j in range(rng.randint(3, 8)):
            days_ago = rng.randint(3, 180)
            rec_date = now - timedelta(days=days_ago)
            score = rng.uniform(55, 95)
            direction = "buy" if score >= 70 else "sell" if score <= 45 else "hold"
            confidence = rng.uniform(0.6, 0.92)

            quality, case = grader.grade_recommendation(
                stock_code=code, stock_name=name,
                ai_score=score, direction=direction, confidence=confidence,
                official_sources=rng.randint(0, 3),
                commercial_sources=rng.randint(0, 2),
                community_sources=rng.randint(1, 2),
                cross_verified=rng.randint(1, 5),
                total_evidence=rng.randint(2, 8),
                data_consistency=rng.uniform(70, 98),
                data_age_sec=rng.uniform(1, 300),
            )
            # Override timestamp
            case.created_at = rec_date.isoformat()
            case.case_id = f"RC-{rec_date.year}-{100000 + i * 10 + j:06d}"

            # Set outcome for older cases
            if days_ago >= 30:
                case.outcome_known = True
                case.was_correct = rng.random() < (0.5 + (score - 50) / 100)
                case.actual_30d_return = rng.uniform(-15, 35) if case.was_correct else rng.uniform(-25, 5)
                case.outcome_analyzed_at = (rec_date + timedelta(days=30)).isoformat()
                case.outcome_analysis = (
                    f"推荐正确。{name}在30天内上涨{case.actual_30d_return:+.1f}%。"
                    if case.was_correct else
                    f"推荐失误。{name}在30天内下跌{abs(case.actual_30d_return):.1f}%。主要原因是行业轮动。"
                )

            archive_case(case)


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
    name = STOCK_NAMES.get(code, code)
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
        return f"核心驱动因素：{'、'.join(f.factor for f in critical)}。移除任一项将显著降低评分。"
    return f"评分由多项因素均衡支撑，没有单一决定性因素。"


@router.get("/allocate")
async def allocate_capital(cash_reserve: float = Query(20.0), risk: str = Query("moderate")):
    """Optimal capital allocation for today."""
    from src.shared.mock_data import generate_stock_pool, mock_signal_result
    import hashlib, random
    from datetime import date

    today_seed = int(hashlib.md5(date.today().isoformat().encode()).hexdigest()[:8], 16)
    rng = random.Random(today_seed)

    pool = generate_stock_pool(15)
    candidates = []
    for p in pool:
        sig = mock_signal_result(p["code"], [])
        candidates.append({
            "stock_code": p["code"],
            "stock_name": p.get("name", STOCK_NAMES.get(p["code"], p["code"])),
            "ai_score": sig["fusion_score"],
            "risk_level": rng.choice(["低", "中", "高"]),
            "user_win_rate": rng.uniform(0.4, 0.85),
        })

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
    """Confidence calibration — how well does AI confidence match reality?"""
    from src.explain.evidence_quality import _case_history
    _seed_cases_if_empty()
    report = calibration_engine.compute_calibration(_case_history)
    return report.to_dict()


@router.get("/annual-report")
async def annual_report(year: int = Query(2026)):
    """AI Annual Report — like a fund's annual performance report."""
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
    """Investment Committee — 5 AI analysts debate and vote."""
    name = STOCK_NAMES.get(code, code)

    decision = committee.evaluate(
        stock_code=code, stock_name=name,
        base_score=base_score,
        portfolio_context={"position_pct": position_pct, "concentration_risk": 55, "volatility": 45},
        user_history={"win_rate": 0.72, "trades": 5},
    )
    return decision.to_dict()


@router.get("/compare")
async def compare_opportunity(
    code_a: str = Query("688256.SH"), code_b: str = Query("688981.SH"),
    score_a: float = Query(92), score_b: float = Query(87),
):
    """Why stock A over stock B? Pairwise comparison."""
    name_a = STOCK_NAMES.get(code_a, code_a)
    name_b = STOCK_NAMES.get(code_b, code_b)
    result = portfolio_intelligence.compare_opportunity_cost(
        name_a, score_a, name_b, score_b,
    )
    return result.to_dict()
