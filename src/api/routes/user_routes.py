"""User API Routes — v6.0 Adaptive Intelligence.

All user profile data is LEARNED from behavior, never configured.
  GET  /user/profile       — Full learned behavior profile
  GET  /user/profile/summary — Compact profile for Dashboard
  POST /user/adapt         — Adapt a base recommendation for this user
"""

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.shared.mock_data import generate_trust_snapshots
from src.user_model.engine import get_user_model_engine
from src.trust.engine import get_trust_engine

router = APIRouter(tags=["user"], prefix="/user")


class AdaptRequest(BaseModel):
    stock_code: str = ""
    stock_name: str = ""
    base_score: float = 50.0
    base_direction: str = "neutral"
    signals: list[str] = []


@router.get("/profile")
async def get_user_profile():
    """Full learned user behavior profile.

    Everything here is derived from your actual decisions —
    what you bought, sold, ignored, held. Zero configuration.
    """
    # Load data from trust snapshots
    trust_engine = get_trust_engine()
    from src.shared.mock_data import generate_trust_snapshots
    from src.domain.models.trust import (
        OutcomePoint, RecommendationSnapshot, SignalSnapshot, MarketSnapshot,
    )

    if not trust_engine._snapshots:
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
        trust_engine.add_snapshots(snaps)

    # Generate user model from snapshots
    user_engine = get_user_model_engine()
    user_engine.load_snapshots(trust_engine._snapshots)
    profile = user_engine.generate_profile()

    return profile.to_dict()


@router.get("/profile/summary")
async def get_profile_summary():
    """Compact profile for Dashboard display."""
    from src.domain.models.trust import (
        OutcomePoint, RecommendationSnapshot, SignalSnapshot, MarketSnapshot,
    )
    from src.shared.mock_data import generate_trust_snapshots

    trust_engine = get_trust_engine()
    if not trust_engine._snapshots:
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
        trust_engine.add_snapshots(snaps)

    user_engine = get_user_model_engine()
    user_engine.load_snapshots(trust_engine._snapshots)
    profile = user_engine.generate_profile()

    return {
        "greeting": profile.personalized_greeting,
        "style": profile.investment_style.to_dict() if profile.investment_style else None,
        "risk": profile.risk_profile.to_dict() if profile.risk_profile else None,
        "top_sectors": [s.to_dict() for s in profile.sector_affinities[:3]],
        "best_strategy": profile.strategy_strengths[0].to_dict() if profile.strategy_strengths else None,
        "top_patterns": [p.to_dict() for p in profile.behavior_patterns[:3]],
        "ai_alignment": profile.ai_alignment.to_dict() if profile.ai_alignment else None,
        "total_decisions": profile.total_decisions_analyzed,
    }


@router.post("/adapt")
async def adapt_recommendation(req: AdaptRequest):
    """Adapt a base AI recommendation for this user.

    Same stock, different users → different output.
    """
    trust_engine = get_trust_engine()
    from src.domain.models.trust import (
        OutcomePoint, RecommendationSnapshot, SignalSnapshot, MarketSnapshot,
    )
    from src.shared.mock_data import generate_trust_snapshots

    if not trust_engine._snapshots:
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
        trust_engine.add_snapshots(snaps)

    user_engine = get_user_model_engine()
    user_engine.load_snapshots(trust_engine._snapshots)

    result = user_engine.adapt_recommendation(
        stock_code=req.stock_code,
        stock_name=req.stock_name,
        base_score=req.base_score,
        base_direction=req.base_direction,
        signals=req.signals,
    )
    return result.to_dict()
