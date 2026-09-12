"""User profile routes backed by persisted decisions and paper actions."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query

from src.api.routes.journal_utils import latest_decision_for_code, recommended_codes
from src.user_model.journal_loader import load_user_model_from_journal

router = APIRouter(tags=["user"], prefix="/user")


async def _current_profile() -> tuple[dict, dict]:
    engine, metadata = await asyncio.to_thread(load_user_model_from_journal)
    profile = await asyncio.to_thread(engine.generate_profile)
    return profile.to_dict(), metadata


@router.get("/profile")
async def user_profile():
    profile, metadata = await _current_profile()
    return {
        "status": "live" if metadata["decision_count"] else "insufficient_data",
        **profile,
        "current_interactions": metadata["paper_action_count"],
        "verified_decisions": metadata["verified_count"],
        "observed_decisions": metadata["observed_count"],
        "neutral_observations": metadata["neutral_observed_count"],
        "data_basis": metadata["data_basis"],
    }


@router.get("/profile/summary")
async def profile_summary():
    profile, metadata = await _current_profile()
    return {
        "status": "live" if metadata["decision_count"] else "insufficient_data",
        "summary": profile.get("user_summary", ""),
        "greeting": profile.get("personalized_greeting", ""),
        "total_decisions_analyzed": profile.get("total_decisions_analyzed", 0),
        "current_interactions": metadata["paper_action_count"],
        "data_basis": metadata["data_basis"],
    }


@router.get("/adapt")
async def adapt_recommendation(
    stock_code: str = Query(""),
    base_score: float = Query(70.0, ge=0, le=100),
):
    if not stock_code:
        codes = recommended_codes(limit=1)
        stock_code = codes[0] if codes else ""
    decision = latest_decision_for_code(stock_code) if stock_code else None
    engine, metadata = await asyncio.to_thread(load_user_model_from_journal)
    adapted = await asyncio.to_thread(
        engine.adapt_recommendation,
        stock_code,
        str((decision or {}).get("stock_name") or stock_code),
        base_score,
        str((decision or {}).get("direction") or "neutral"),
        ["MACD", "RSI", "KDJ", "MA", "Volume"],
    )
    return {
        "status": "live" if metadata["decision_count"] else "insufficient_data",
        **adapted.to_dict(),
        "data_basis": metadata["data_basis"],
    }
