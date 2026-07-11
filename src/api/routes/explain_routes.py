"""Explain routes backed by real pipeline decisions."""

from fastapi import APIRouter

from src.api.routes.journal_utils import decision_scores, latest_decision_for_code
from src.explain.engine import builder, explainer

router = APIRouter(tags=["explain"], prefix="/explain")


def _missing(code: str) -> dict:
    return {
        "stock_code": code,
        "status": "not_found",
        "data_source": "decision_journal",
        "message": "No pipeline decision found for this stock. Run the daily pipeline first.",
    }


def _build_breakdown(code: str):
    decision = latest_decision_for_code(code)
    if not decision:
        return None

    score = float(decision.get("ai_score") or 50)
    confidence = float(decision.get("confidence") or 0)
    scores = decision_scores(decision)
    reasons = []
    evidence = str(decision.get("evidence") or "").strip()
    recommendation = str(decision.get("recommendation") or "").strip()
    if recommendation:
        reasons.append(recommendation)
    if evidence:
        reasons.append(evidence)

    return builder.build(
        stock_code=str(decision.get("stock_code") or code),
        stock_name=str(decision.get("stock_name") or code),
        scores=scores,
        direction=str(decision.get("direction") or "neutral"),
        confidence=confidence,
        reasons=reasons,
        knowledge_score=score,
        market_score=score,
    )


@router.get("/breakdown/{code}")
async def get_score_breakdown(code: str):
    """Get detailed score breakdown from the latest journal decision."""
    breakdown = _build_breakdown(code)
    if not breakdown:
        return _missing(code)
    result = breakdown.to_dict()
    result["data_source"] = "decision_journal (real AI pipeline)"
    return result


@router.get("/explain/{code}")
async def explain_stock(code: str):
    """Get structured explanation from the latest journal decision."""
    breakdown = _build_breakdown(code)
    if not breakdown:
        return _missing(code)
    result = explainer.explain_breakdown(breakdown)
    if isinstance(result, dict):
        result["data_source"] = "decision_journal (real AI pipeline)"
    return result
