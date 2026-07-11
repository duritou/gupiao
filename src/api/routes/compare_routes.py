"""Compare routes backed by the real decision journal."""

from fastapi import APIRouter
from pydantic import BaseModel

from src.api.routes.journal_utils import (
    decision_scores,
    latest_decision_for_code,
    recommendation_from_score,
    risk_level,
    score_stars,
    top_signal,
)

router = APIRouter(tags=["compare"], prefix="/compare")


class CompareRequest(BaseModel):
    codes: list[str]


@router.post("")
async def compare_stocks(req: CompareRequest):
    """Compare stocks using their latest real pipeline decisions."""
    stocks = []
    missing = []
    for code in req.codes[:6]:
        decision = latest_decision_for_code(code)
        if not decision:
            missing.append(code)
            continue

        score = float(decision.get("ai_score") or 50)
        confidence = float(decision.get("confidence") or 0)
        direction = str(decision.get("direction") or "neutral")
        scores = decision_scores(decision)
        stocks.append(
            {
                "stock_code": decision.get("stock_code", code),
                "stock_name": decision.get("stock_name", code),
                "ai_score": round(score, 1),
                "direction": direction,
                "confidence": round(confidence, 3),
                "stars": score_stars(score),
                "macd": round(scores["macd"], 1),
                "rsi": round(scores["rsi"], 1),
                "ma": round(scores["ma"], 1),
                "volume": round(scores["volume"], 1),
                "valuation": "not_available",
                "industry_score": round(float(decision.get("kdj_score") or 50), 1),
                "recommendation": recommendation_from_score(score, direction),
                "top_signal": top_signal(decision),
                "risk_level": risk_level(confidence),
                "decision_date": decision.get("decision_date", ""),
                "data_source": "decision_journal",
            }
        )

    return {
        "stocks": stocks,
        "missing": missing,
        "data_source": "decision_journal (real AI pipeline)",
        "data_note": "Only stocks with pipeline decisions are compared.",
    }
