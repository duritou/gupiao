"""Alert Intelligence Routes — v7.6: real alerts from pipeline decisions.

Alerts are generated from real AI decisions in the journal.
Strong signals (fusion >= 80) → P1, moderate (fusion >= 65) → P2.
"""

import asyncio
from datetime import date
from time import monotonic

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.api.routes.journal_utils import latest_per_stock

router = APIRouter(tags=["alerts"], prefix="/alerts")

# Several desktop surfaces ask for the same alert snapshot at nearly the same
# time (Dashboard, Alert Center, and the proactive notifier).  Keep the cache
# deliberately short: this removes duplicate journal scans without changing
# alert freshness or any alert/selection rule.
_ALERT_CACHE_TTL_SECONDS = 5.0
_alert_cache: dict[str, tuple[float, list[dict]]] = {}
_alert_inflight: dict[str, asyncio.Task[list[dict]]] = {}


class ActionRequest(BaseModel):
    action_type: str = ""
    stock_code: str = ""
    quantity: int = 0
    price: float = 0.0
    notes: str = ""


class OutcomeRequest(BaseModel):
    outcome_type: str = ""
    realized_pl_pct: float = 0.0
    holding_days: int = 0
    was_correct: bool = False
    notes: str = ""


# ---- Alert builder from real journal ----

def _build_alerts_from_journal(decision_date: str = ""):
    """Generate alerts from real pipeline decisions in the journal."""
    from src.infrastructure.storage.market_database import market_db

    decisions = latest_per_stock(
        market_db.get_decisions_for_date(decision_date, limit=5000)
        if decision_date else market_db.get_recent_decisions(limit=500)
    )
    alerts = []

    for d in decisions:
        score = d.get("ai_score", 50)
        level = "P1" if score >= 80 else "P2" if score >= 65 else "P3" if score >= 55 else "P4"
        if level == "P4":
            continue

        tags = []
        if d.get("macd_score", 50) >= 65:
            tags.append("MACD金叉")
        if d.get("rsi_score", 50) <= 35:
            tags.append("RSI超卖")
        if d.get("ma_score", 50) >= 65:
            tags.append("多头排列")
        if d.get("volume_score", 50) >= 65:
            tags.append("放量")
        created = d.get("created_at", "")

        alerts.append({
            "id": f"alert-{d.get('id', 0)}",
            "level": level,
            "title": f"{d['stock_name']} AI评分{d['ai_score']:.0f}",
            "stock_code": d.get("stock_code", ""),
            "stock_name": d.get("stock_name", ""),
            "ai_confidence": round(d.get("confidence", 0), 2),
            "direction": d.get("direction", "neutral"),
            "score": round(score, 1),
            "recommendation": d.get("recommendation", ""),
            "evidence": [{"type": "signal", "description": d.get("evidence", "")}],
            "tags": tags[:3],
            "created_at": created[:19] if created else "",
            "status": "new" if decision_date == date.today().isoformat() else "historical",
            "category": "signal",
            "historical_accuracy": 0,
        })

    return sorted(alerts, key=lambda alert: alert["score"], reverse=True)


async def _get_alerts_snapshot(decision_date: str = "") -> list[dict]:
    """Share one journal scan across concurrent alert endpoints."""
    cache_key = decision_date or "__recent__"
    now = monotonic()
    cached = _alert_cache.get(cache_key)
    if cached and now - cached[0] < _ALERT_CACHE_TTL_SECONDS:
        return list(cached[1])

    pending = _alert_inflight.get(cache_key)
    if pending is None or pending.done():
        pending = asyncio.create_task(
            asyncio.to_thread(_build_alerts_from_journal, decision_date)
        )
        _alert_inflight[cache_key] = pending

    try:
        alerts = await pending
        _alert_cache[cache_key] = (monotonic(), alerts)
        return list(alerts)
    finally:
        if _alert_inflight.get(cache_key) is pending:
            _alert_inflight.pop(cache_key, None)


def _build_today_focus(alerts: list) -> dict:
    """Build today_focus section for Dashboard / Morning Brief."""
    p1 = [a for a in alerts if a["level"] == "P1"]
    p2 = [a for a in alerts if a["level"] == "P2"]

    if p1 or p2:
        one_liner = (
            f"AI发现{p1[0]['stock_name']}评分最高({p1[0]['score']:.0f}分)"
            if p1 else
            f"今日{p2[0]['stock_name']}信号值得关注({p2[0]['score']:.0f}分)"
        )
    else:
        one_liner = "AI Pipeline 产出中 — 运行 POST /ai-os/run-pipeline 更新"

    return {
        # Keep the dashboard/desktop notifier focused.  The complete counts and
        # alert feed remain available from the alert endpoints.
        "urgent": p1[:5],
        "important": p2[:8],
        "one_liner": one_liner,
    }


# ---- Routes ----

@router.get("/feed")
async def get_alert_feed():
    """Alert feed from real pipeline decisions."""
    alerts = await _get_alerts_snapshot()
    p1 = [a for a in alerts if a["level"] == "P1"]
    return {
        "alerts": alerts[:30],
        "total": len(alerts),
        "urgent_summary": {
            "has_urgent": len(p1) > 0,
            "urgent_count": len(p1),
        },
    }


@router.get("")
async def get_alerts(level: str = Query(None), limit: int = Query(50, ge=1, le=100)):
    alerts = await _get_alerts_snapshot()
    if level:
        alerts = [a for a in alerts if a["level"] == level]
    return {"alerts": alerts[:limit], "total": len(alerts)}


@router.get("/today")
async def get_today_alerts():
    """Today's alert summary — for Dashboard Today Focus."""
    today = date.today().isoformat()
    alerts = await _get_alerts_snapshot(today)
    return {
        "date": today,
        "alerts": alerts[:20],
        "total_today": len(alerts),
        "unread_count": len(alerts),
        "urgent_count": sum(1 for a in alerts if a["level"] in ("P1", "P2")),
        "today_focus": _build_today_focus(alerts),
    }


@router.get("/stats")
async def get_alert_stats():
    alerts = await _get_alerts_snapshot()
    return {
        "total_alerts": len(alerts),
        "by_level": {
            "P1": sum(1 for a in alerts if a["level"] == "P1"),
            "P2": sum(1 for a in alerts if a["level"] == "P2"),
            "P3": sum(1 for a in alerts if a["level"] == "P3"),
        },
        "data_source": "decision_journal (real pipeline)",
    }


@router.get("/recent")
async def get_recent_alerts(limit: int = Query(50, ge=1, le=100)):
    alerts = await _get_alerts_snapshot()
    return {"alerts": alerts[:limit]}


@router.get("/unread-count")
async def unread_count():
    alerts = await _get_alerts_snapshot(date.today().isoformat())
    return {"unread": len(alerts), "urgent": sum(1 for a in alerts if a["level"] == "P1")}
