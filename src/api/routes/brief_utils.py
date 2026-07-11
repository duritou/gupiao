"""Brief builders backed by real journal and market data."""

from __future__ import annotations

from datetime import datetime

from src.api.routes.journal_utils import brief_date, get_journal_decisions, recommendation_from_score


def _sentiment_from_market(market: dict) -> dict:
    breadth = market.get("market_breadth") or {}
    up = int(breadth.get("up") or 0)
    down = int(breadth.get("down") or 0)
    total = up + down
    score = round((up / total) * 100, 1) if total else 0
    if score >= 65:
        label = "positive"
    elif score >= 45:
        label = "neutral"
    elif score > 0:
        label = "weak"
    else:
        label = "unknown"
    stars = 5 if score >= 80 else 4 if score >= 65 else 3 if score >= 45 else 2 if score > 0 else 0
    return {"score": score, "label": label, "stars": stars}


async def build_real_brief() -> dict:
    from src.api.routes.market_routes import market_overview, market_sectors

    decisions = get_journal_decisions(limit=30)
    try:
        market = await market_overview()
    except Exception:
        market = {}
    try:
        sectors_payload = await market_sectors()
        hot_sectors = sectors_payload.get("sectors", [])[:5]
    except Exception:
        hot_sectors = []

    sentiment = _sentiment_from_market(market)
    opportunities = []
    risks = []
    for d in decisions[:10]:
        score = float(d.get("ai_score") or 50)
        direction = str(d.get("direction") or "neutral")
        item = {
            "stock_code": d.get("stock_code", ""),
            "stock_name": d.get("stock_name", ""),
            "score": round(score, 1),
            "direction": direction,
            "recommendation": recommendation_from_score(score, direction),
            "reason": d.get("recommendation") or d.get("evidence") or "Pipeline decision",
            "decision_date": d.get("decision_date", ""),
        }
        if score >= 65 and direction != "sell":
            opportunities.append(item)
        elif score < 50 or direction == "sell":
            risks.append(f"{item['stock_name'] or item['stock_code']}: score {score:.0f}, {direction}")

    top = opportunities[0] if opportunities else None
    if top:
        one_liner = f"Top pipeline focus: {top['stock_name']} scores {top['score']:.0f}."
    elif decisions:
        one_liner = "Pipeline has decisions, but no buy-grade opportunity is above 65 today."
    else:
        one_liner = "No real pipeline decisions yet. Run POST /ai-os/run-pipeline first."

    return {
        "date": brief_date(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "data_source": "decision_journal + market_overview",
        "market_sentiment": sentiment,
        "market_summary": (
            f"Market breadth: {market.get('market_breadth', {}).get('up', 0)} up / "
            f"{market.get('market_breadth', {}).get('down', 0)} down."
        ),
        "hot_sectors": hot_sectors,
        "top_opportunities": opportunities[:8],
        "risk_warnings": risks[:5],
        "one_liner": one_liner,
        "portfolio": {
            "avg_score": round(sum(float(d.get("ai_score") or 50) for d in decisions) / len(decisions), 1)
            if decisions else 0,
            "position_count": len(decisions),
            "items": opportunities[:8],
        },
        "score_changes": {"upgraded": opportunities[:5], "downgraded": [], "stable": []},
        "market": {
            "sentiment_stars": sentiment["stars"],
            "sentiment_label": sentiment["label"],
            "sentiment_score": sentiment["score"],
            "up_count": market.get("market_breadth", {}).get("up", 0),
            "down_count": market.get("market_breadth", {}).get("down", 0),
            "total_volume": market.get("total_volume", 0),
            "northbound": market.get("northbound", {}),
            "indices": market.get("indices", {}),
        },
        "recommendations": opportunities[:5],
    }
