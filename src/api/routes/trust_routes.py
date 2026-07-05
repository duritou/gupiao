"""Trust API Routes — v5.0 AI accountability layer.

Powers:
  GET /trust/track-record    — AI performance stats (accuracy, returns, streaks)
  GET /trust/strategies      — Accuracy breakdown by strategy/signal
  GET /trust/score-ranges    — Accuracy breakdown by AI score range
  GET /trust/journal         — Decision journal entries
  GET /trust/journal/summary — Aggregate journal stats
  GET /trust/model-evolution — AI version accuracy history
  GET /trust/resume          — Cumulative AI trust profile
  GET /trust/monthly         — Monthly accuracy trend data
"""

from fastapi import APIRouter, Query

from src.domain.models.trust import (
    OutcomePoint,
    RecommendationSnapshot,
    SignalSnapshot,
    MarketSnapshot,
)
from src.shared.mock_data import generate_trust_snapshots
from src.trust.engine import get_trust_engine

router = APIRouter(tags=["trust"], prefix="/trust")


def _load_snapshots(engine=None):
    """Load mock snapshots into engine and return them."""
    if engine is None:
        engine = get_trust_engine()
    if not engine._snapshots:
        mock_data = generate_trust_snapshots(60)
        snaps = []
        for d in mock_data:
            snaps.append(RecommendationSnapshot(
                id=d["id"], created_at=d["created_at"],
                stock_code=d["stock_code"], stock_name=d["stock_name"],
                direction=d["direction"], price_at_rec=d["price_at_rec"],
                ai_score=d["ai_score"], ai_confidence=d["ai_confidence"],
                signals=[SignalSnapshot(**s) for s in d["signals"]],
                market_snapshot=MarketSnapshot(**d["market_snapshot"]) if d.get("market_snapshot") else None,
                knowledge_context=d.get("knowledge_context", ""),
                recommendation_text=d.get("recommendation_text", ""),
                source=d.get("source", ""), alert_id=d.get("alert_id", ""),
                ai_version=d.get("ai_version", ""), model_info=d.get("model_info", ""),
                user_action=d.get("user_action", ""),
                user_action_at=d.get("user_action_at", ""),
                user_action_price=d.get("user_action_price", 0),
                user_notes=d.get("user_notes", ""),
                outcome_7d=OutcomePoint(**d["outcome_7d"]) if d.get("outcome_7d") else None,
                outcome_30d=OutcomePoint(**d["outcome_30d"]) if d.get("outcome_30d") else None,
                outcome_90d=OutcomePoint(**d["outcome_90d"]) if d.get("outcome_90d") else None,
                final_verdict=d.get("final_verdict", "pending"),
                final_profit_pct=d.get("final_profit_pct", 0),
                ai_reflection=d.get("ai_reflection", ""),
                reflection_at=d.get("reflection_at", ""),
            ))
        engine.add_snapshots(snaps)
    return engine


@router.get("/track-record")
async def get_track_record(days: int = Query(30, ge=7, le=365)):
    """AI Track Record — accuracy, returns, streaks, user behavior.

    This is the single most important trust metric.
    """
    engine = _load_snapshots()
    record = engine.compute_track_record(days=days)
    return record.to_dict()


@router.get("/ai-alpha")
async def get_ai_alpha(days: int = Query(90, ge=30, le=365)):
    """AI Alpha — value attribution.

    Answers: did following AI actually make money?
    Compares follow-AI returns vs self-directed returns.
    """
    engine = _load_snapshots()
    alpha = engine.compute_ai_alpha(days=days)
    return alpha.to_dict()


@router.get("/strategies")
async def get_strategy_breakdown():
    """Accuracy breakdown by strategy/signal type.

    e.g. MACD金叉 82%, 放量突破 78%, AI评分>90 91%
    """
    engine = _load_snapshots()
    breakdowns = engine.compute_strategy_breakdown()
    return {"strategies": [b.to_dict() for b in breakdowns]}


@router.get("/score-ranges")
async def get_score_range_breakdown():
    """Accuracy by AI score range.

    e.g. 90-100: 91%, 80-90: 73%, 70-80: 61%, <60: 41%
    """
    engine = _load_snapshots()
    ranges = engine.compute_score_range_breakdown()
    return {"ranges": [r.to_dict() for r in ranges]}


@router.get("/journal")
async def get_decision_journal(
    limit: int = Query(30, ge=1, le=100),
    verdict: str = Query("", description="Filter: correct/wrong/pending"),
    action: str = Query("", description="Filter: bought/sold/held/ignored/partial"),
):
    """Decision Journal — AI recommendations vs user actions vs outcomes."""
    engine = _load_snapshots()
    entries = engine.get_journal_entries(limit=limit, verdict=verdict, action=action)
    return {
        "entries": [e.to_dict() for e in entries],
        "total": len(engine._snapshots),
    }


@router.get("/journal/summary")
async def get_journal_summary():
    """Aggregate journal statistics with behavioral insights."""
    engine = _load_snapshots()
    summary = engine.get_journal_summary()
    return summary.to_dict()


@router.get("/model-evolution")
async def get_model_evolution():
    """AI version history with accuracy trends.

    Shows how AI accuracy has improved across versions.
    """
    engine = _load_snapshots()
    versions = engine.compute_model_evolution()
    return {"versions": [v.to_dict() for v in versions]}


@router.get("/resume")
async def get_ai_resume():
    """Cumulative AI trust profile — the 'AI Resume'.

    Total studies, recommendations, accuracy, streaks, best strategies.
    """
    engine = _load_snapshots()
    resume = engine.compute_ai_resume()
    return resume.to_dict()


@router.get("/monthly")
async def get_monthly_accuracy():
    """Monthly accuracy trend for sparkline charts."""
    engine = _load_snapshots()
    monthly = engine.compute_monthly_accuracy()
    return {"monthly": monthly}


@router.get("/snapshot/{snapshot_id}")
async def get_snapshot(snapshot_id: str):
    """Get a single recommendation snapshot with full detail."""
    engine = _load_snapshots()
    for s in engine._snapshots:
        if s.id == snapshot_id:
            return s.to_dict()
    return {"error": "snapshot not found", "id": snapshot_id}
