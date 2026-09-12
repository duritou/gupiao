"""Timeline routes backed by real decision journal history."""

from fastapi import APIRouter, Query

router = APIRouter(tags=["timeline"], prefix="/timeline")


def _number(value: object, default: float = 50.0) -> float:
    """Coerce persisted numeric values without failing the whole page."""
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _decision_day(decision: dict) -> str:
    """Return the journal's trading day, with created_at as a fallback."""
    return str(decision.get("decision_date") or decision.get("created_at") or "")[:10]


@router.get("/{code}")
async def get_timeline(
    code: str,
    days: int = Query(30, ge=7, le=180, description="Number of days of history"),
):
    """Return score evolution from persisted pipeline decisions."""
    if not isinstance(days, int):
        days = 30
    normalized = code.strip().upper()
    if not normalized:
        return {
            "stock_code": "",
            "stock_name": "",
            "current_score": None,
            "total_change": 0,
            "entries": [],
            "data_source": "decision_journal (real AI pipeline)",
            "data_note": "A stock code is required.",
        }

    from src.infrastructure.storage.market_database import market_db

    # The learning pipeline may run more than once per trading day. Fetch a
    # wider bounded window, retain the newest decision for each date, and then
    # return the requested number of real daily observations.
    newest_first = market_db.get_decision_history_for_codes(
        [normalized],
        limit_per_code=min(days * 10, 1000),
    ).get(normalized, [])
    daily_newest: list[dict] = []
    seen_days: set[str] = set()
    for decision in newest_first:
        decision_day = _decision_day(decision)
        if not decision_day or decision_day in seen_days:
            continue
        seen_days.add(decision_day)
        daily_newest.append(decision)
        if len(daily_newest) >= days:
            break
    decisions = list(reversed(daily_newest))

    entries = []
    previous_score = None
    for d in decisions:
        score = _number(d.get("ai_score"))
        change = 0.0 if previous_score is None else score - previous_score
        previous_score = score
        entries.append(
            {
                "date": _decision_day(d),
                "observed_at": str(d.get("created_at") or ""),
                "score": round(score, 1),
                "change": round(change, 1),
                "direction": "up" if change > 0 else "down" if change < 0 else "flat",
                "events": [
                    {
                        "event": (
                            d.get("recommendation")
                            or d.get("evidence")
                            or "Pipeline decision"
                        ),
                        "impact": f"{change:+.1f}",
                        "source": "decision_journal",
                    }
                ],
            }
        )

    current_score = entries[-1]["score"] if entries else None
    total_change = (entries[-1]["score"] - entries[0]["score"]) if len(entries) >= 2 else 0
    stock_name = decisions[-1].get("stock_name", normalized) if decisions else normalized

    return {
        "stock_code": normalized,
        "stock_name": stock_name,
        "current_score": current_score,
        "total_change": round(total_change, 1),
        "entries": entries,
        "requested_days": days,
        "data_source": "decision_journal (real AI pipeline)",
        "data_note": (
            "Each point is the newest persisted pipeline decision for that date; "
            "no synthetic history is generated."
        ),
    }
