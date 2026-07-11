"""Helpers for API pages backed by the real decision journal."""

from __future__ import annotations

from datetime import date


def get_journal_decisions(limit: int = 50) -> list[dict]:
    """Return recent pipeline decisions sorted by score descending."""
    from src.infrastructure.storage.market_database import market_db

    decisions = market_db.get_recent_decisions(limit=limit)
    return sorted(decisions, key=lambda d: float(d.get("ai_score") or 0), reverse=True)


def latest_decision_for_code(code: str) -> dict | None:
    """Find the latest journal decision for a stock code."""
    normalized = code.strip().upper()
    for decision in get_journal_decisions(limit=200):
        if str(decision.get("stock_code", "")).upper() == normalized:
            return decision
    return None


def recommended_codes(limit: int = 30) -> list[str]:
    """Stock codes from the latest AI decisions only."""
    codes = []
    seen = set()
    for decision in get_journal_decisions(limit=limit):
        code = str(decision.get("stock_code") or "").strip()
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def stock_name_from_journal(code: str) -> str:
    """Resolve a display name from the decision journal; otherwise use code."""
    decision = latest_decision_for_code(code)
    if decision and decision.get("stock_name"):
        return str(decision["stock_name"])
    return code


def score_stars(score: float) -> int:
    return 5 if score >= 80 else 4 if score >= 65 else 3 if score >= 45 else 2


def recommendation_from_score(score: float, direction: str = "") -> str:
    if direction == "sell" or score < 40:
        return "avoid"
    if score >= 80:
        return "strong_buy"
    if score >= 65:
        return "buy"
    if score >= 50:
        return "watch"
    return "neutral"


def top_signal(decision: dict) -> str:
    scores = {
        "MACD": float(decision.get("macd_score") or 50),
        "RSI": float(decision.get("rsi_score") or 50),
        "KDJ": float(decision.get("kdj_score") or 50),
        "MA": float(decision.get("ma_score") or 50),
        "Volume": float(decision.get("volume_score") or 50),
    }
    name, value = max(scores.items(), key=lambda item: item[1])
    return f"{name} {value:.0f}"


def risk_level(confidence: float) -> str:
    if confidence >= 0.75:
        return "low"
    if confidence >= 0.55:
        return "medium"
    return "high"


async def latest_close(code: str) -> float:
    """Return the latest real close price when available."""
    try:
        from src.infrastructure.market_data.real_data_provider import real_data

        bars = await real_data.get_daily_bars(code, days=30)
        if bars:
            return float(bars[-1].get("close") or 0)
    except Exception:
        return 0.0
    return 0.0


def empty_journal_response() -> dict:
    return {
        "status": "accumulating",
        "data_source": "decision_journal",
        "data_note": "No pipeline decisions yet. Run POST /ai-os/run-pipeline first.",
    }


def decision_scores(decision: dict) -> dict:
    return {
        "macd": float(decision.get("macd_score") or 50),
        "rsi": float(decision.get("rsi_score") or 50),
        "kdj": float(decision.get("kdj_score") or 50),
        "ma": float(decision.get("ma_score") or 50),
        "volume": float(decision.get("volume_score") or 50),
    }


def brief_date() -> str:
    return date.today().isoformat()
