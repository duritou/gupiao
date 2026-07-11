"""Alert Intelligence Routes — v7.6: real alerts from pipeline decisions.

Alerts are generated from real AI decisions in the journal.
Strong signals (fusion >= 80) → P1, moderate (fusion >= 65) → P2.
"""

from datetime import datetime
from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter(tags=["alerts"], prefix="/alerts")


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

def _build_alerts_from_journal():
    """Generate alerts from real pipeline decisions in the journal."""
    from src.infrastructure.storage.market_database import market_db

    decisions = market_db.get_recent_decisions(limit=30)
    alerts = []

    for d in decisions:
        score = d.get("ai_score", 50)
        level = "P1" if score >= 80 else "P2" if score >= 65 else "P3" if score >= 55 else "P4"
        if level == "P4":
            continue

        tags = []
        if d.get("macd_score", 50) >= 65: tags.append("MACD金叉")
        if d.get("rsi_score", 50) <= 35: tags.append("RSI超卖")
        if d.get("ma_score", 50) >= 65: tags.append("多头排列")
        if d.get("volume_score", 50) >= 65: tags.append("放量")
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
            "status": "new",
            "category": "signal",
            "historical_accuracy": 0,
        })

    return alerts


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
        "urgent": p1,
        "important": p2,
        "one_liner": one_liner,
    }


# ---- Routes ----

@router.get("/feed")
async def get_alert_feed():
    """Alert feed from real pipeline decisions."""
    alerts = _build_alerts_from_journal()
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
    alerts = _build_alerts_from_journal()
    if level:
        alerts = [a for a in alerts if a["level"] == level]
    return {"alerts": alerts[:limit], "total": len(alerts)}


@router.get("/today")
async def get_today_alerts():
    """Today's alert summary — for Dashboard Today Focus."""
    alerts = _build_alerts_from_journal()
    return {
        "alerts": alerts[:20],
        "total_today": len(alerts),
        "unread_count": len(alerts),
        "urgent_count": sum(1 for a in alerts if a["level"] in ("P1", "P2")),
        "today_focus": _build_today_focus(alerts),
    }


@router.get("/stats")
async def get_alert_stats():
    alerts = _build_alerts_from_journal()
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
async def get_recent_alerts():
    return {"alerts": _build_alerts_from_journal()[:10]}


@router.get("/unread-count")
async def unread_count():
    alerts = _build_alerts_from_journal()
    return {"unread": len(alerts), "urgent": sum(1 for a in alerts if a["level"] == "P1")}
