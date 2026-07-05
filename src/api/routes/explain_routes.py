"""Explain routes — Score Breakdown + Structured Explanation."""

from fastapi import APIRouter, Query

from src.explain.engine import builder, explainer
from src.shared.mock_data import generate_klines, mock_signal_result, get_stock_name

router = APIRouter(tags=["explain"], prefix="/explain")


@router.get("/breakdown/{code}")
async def get_score_breakdown(code: str):
    """Get detailed score breakdown for a stock."""
    klines = generate_klines(code, 80, "up")
    signal = mock_signal_result(code, klines)
    scores = signal.get("scores", {})

    # Compute knowledge and market scores from signal context
    knowledge_score = max(50, signal["fusion_score"] + min(20, (signal["fusion_score"] - 50) * 0.5))
    market_score = max(50, signal["fusion_score"] + min(15, (signal["confidence"] - 0.5) * 40))

    breakdown = builder.build(
        stock_code=code,
        stock_name=get_stock_name(code),
        scores=scores,
        direction=signal["direction"],
        confidence=signal["confidence"],
        reasons=signal.get("reasons", []),
        knowledge_score=knowledge_score,
        market_score=market_score,
    )

    return breakdown.to_dict()


@router.get("/explain/{code}")
async def explain_stock(code: str):
    """Get structured explanation for a stock."""
    klines = generate_klines(code, 80)
    signal = mock_signal_result(code, klines)
    scores = signal.get("scores", {})

    knowledge_score = max(50, signal["fusion_score"] + min(20, (signal["fusion_score"] - 50) * 0.5))
    market_score = max(50, signal["fusion_score"] + min(15, (signal["confidence"] - 0.5) * 40))

    breakdown = builder.build(
        stock_code=code,
        stock_name=get_stock_name(code),
        scores=scores,
        direction=signal["direction"],
        confidence=signal["confidence"],
        knowledge_score=knowledge_score,
        market_score=market_score,
    )

    return explainer.explain_breakdown(breakdown)
