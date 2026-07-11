"""Timeline routes backed by real decision journal history."""

from fastapi import APIRouter, Query

from src.api.routes.journal_utils import get_journal_decisions

router = APIRouter(tags=["timeline"], prefix="/timeline")


@router.get("/{code}")
async def get_timeline(
    code: str,
    days: int = Query(30, ge=7, le=180, description="Number of days of history"),
):
    """Return score evolution from persisted pipeline decisions."""
    if not isinstance(days, int):
        days = 30
    normalized = code.strip().upper()
    decisions = [
        d for d in get_journal_decisions(limit=500)
        if str(d.get("stock_code", "")).upper() == normalized
    ]
    decisions = sorted(decisions, key=lambda d: str(d.get("created_at") or d.get("decision_date") or ""))
    decisions = decisions[-days:]

    entries = []
    previous_score = None
    for d in decisions:
        score = float(d.get("ai_score") or 50)
        change = 0.0 if previous_score is None else score - previous_score
        previous_score = score
        entries.append(
            {
                "date": str(d.get("decision_date") or d.get("created_at") or "")[:10],
                "score": round(score, 1),
                "change": round(change, 1),
                "direction": "up" if change > 0 else "down" if change < 0 else "flat",
                "events": [
                    {
                        "event": d.get("recommendation") or d.get("evidence") or "Pipeline decision",
                        "impact": f"{change:+.1f}",
                        "source": "decision_journal",
                    }
                ],
            }
        )

    current_score = entries[-1]["score"] if entries else None
    total_change = (entries[-1]["score"] - entries[0]["score"]) if len(entries) >= 2 else 0
    stock_name = decisions[-1].get("stock_name", code) if decisions else code

    return {
        "stock_code": code,
        "stock_name": stock_name,
        "current_score": current_score,
        "total_change": round(total_change, 1),
        "entries": entries,
        "data_source": "decision_journal (real AI pipeline)",
        "data_note": "No synthetic score history is generated.",
    }
