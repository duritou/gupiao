"""AI Operating System routes backed by real pipeline state."""

from datetime import date

from fastapi import APIRouter, Query

from src.ai_os.scheduler import get_current_phase, get_daily_schedule, get_schedule_for_phase
from src.api.routes.journal_utils import get_journal_decisions

router = APIRouter(tags=["ai-os"], prefix="/ai-os")


def _journal_events(limit: int = 50) -> list[dict]:
    events = []
    for d in get_journal_decisions(limit=limit):
        score = float(d.get("ai_score") or 50)
        created = str(d.get("created_at") or d.get("decision_date") or "")
        events.append(
            {
                "id": f"decision-{d.get('id', len(events))}",
                "source": "decision_journal",
                "event_type": "pipeline.decision",
                "summary": f"{d.get('stock_name', d.get('stock_code', ''))} score {score:.0f}: {d.get('recommendation', '')}",
                "related_stock": d.get("stock_code", ""),
                "timestamp": created,
                "ts": created,
                "metrics": {
                    "ai_score": score,
                    "confidence": float(d.get("confidence") or 0),
                    "buy_signals": int(d.get("buy_signals") or 0),
                    "sell_signals": int(d.get("sell_signals") or 0),
                },
            }
        )
    return events


@router.get("/status")
async def get_ai_os_status():
    """Current AI OS phase and real journal progress."""
    phase = get_current_phase()
    schedule = get_daily_schedule()
    tasks = get_schedule_for_phase(phase)
    decisions = get_journal_decisions(limit=200)
    today = date.today().isoformat()
    today_count = sum(1 for d in decisions if str(d.get("decision_date", "")).startswith(today))
    return {
        "current_phase": phase.value,
        "phase_label": phase.value,
        "today_progress": {
            "total_tasks": len(schedule.tasks),
            "completed": len(schedule.executed),
            "failed": len(schedule.failed),
            "completion_pct": round(schedule.completion_pct * 100, 0),
            "journal_decisions_today": today_count,
            "journal_decisions_total": len(decisions),
        },
        "current_tasks": [t.name for t in tasks],
        "next_phase": _next_phase(phase.value),
        "data_source": "scheduler + decision_journal",
    }


@router.get("/schedule")
async def get_schedule():
    schedule = get_daily_schedule()
    return {
        "date": schedule.date,
        "tasks": [
            {
                "phase": t.phase.value,
                "name": t.name,
                "description": t.description,
                "is_critical": t.is_critical,
                "depends_on": t.depends_on,
            }
            for t in schedule.tasks
        ],
        "total_tasks": len(schedule.tasks),
    }


@router.get("/events")
async def get_events(source: str = Query(""), limit: int = Query(50, ge=1, le=200)):
    events = _journal_events(limit=limit)
    if source:
        events = [e for e in events if e["source"] == source]
    return {"events": events, "total": len(events), "data_source": "decision_journal"}


@router.get("/memory/today")
async def get_today_memory():
    today = date.today().isoformat()
    decisions = [d for d in get_journal_decisions(limit=200) if str(d.get("decision_date", "")).startswith(today)]
    if not decisions:
        decisions = get_journal_decisions(limit=30)
    p1 = [d for d in decisions if float(d.get("ai_score") or 0) >= 80]
    p2 = [d for d in decisions if 65 <= float(d.get("ai_score") or 0) < 80]
    top = decisions[0] if decisions else None
    return {
        "date": today,
        "day_of_week": date.today().strftime("%A"),
        "total_events": len(decisions),
        "recommendations_made": len(decisions),
        "alerts_fired": len(p1) + len(p2),
        "user_actions": 0,
        "outcomes_recorded": sum(1 for d in decisions if d.get("outcome_known")),
        "daily_summary": (
            f"Pipeline produced {len(decisions)} real decisions; top focus is "
            f"{top.get('stock_name')} score {float(top.get('ai_score') or 0):.0f}."
            if top else "No real pipeline decisions yet."
        ),
        "lessons_learned": "Learning is based only on verified journal outcomes.",
        "tomorrow_preview": "Run /ai-os/run-pipeline after fresh market data is available.",
        "data_source": "decision_journal",
    }


@router.get("/memory/week")
async def get_weekly_memory():
    decisions = get_journal_decisions(limit=200)
    return {
        "period": "week",
        "total_events": len(decisions),
        "summary": f"{len(decisions)} pipeline decisions available in the journal.",
        "data_source": "decision_journal",
    }


@router.get("/memory/month")
async def get_monthly_memory():
    decisions = get_journal_decisions(limit=500)
    return {
        "period": "month",
        "total_events": len(decisions),
        "summary": f"{len(decisions)} pipeline decisions available in the journal.",
        "data_source": "decision_journal",
    }


@router.get("/learning-log")
async def get_learning_log():
    decisions = get_journal_decisions(limit=500)
    verified = [d for d in decisions if d.get("outcome_known")]
    return {
        "learning_log": [
            f"Verified decisions: {len(verified)} / {len(decisions)}. Accuracy updates when outcomes are recorded."
        ],
        "total_learnings": 1 if decisions else 0,
        "data_source": "decision_journal",
    }


@router.get("/timeline")
async def get_timeline(days: int = Query(7, ge=1, le=30)):
    return {"events": _journal_events(limit=days * 20), "days": days, "data_source": "decision_journal"}


def _next_phase(current: str) -> str:
    phases = ["pre_market", "market_open", "midday", "afternoon", "market_close", "evening"]
    try:
        idx = phases.index(current)
        return phases[idx + 1] if idx + 1 < len(phases) else "pre_market"
    except ValueError:
        return "unknown"


@router.post("/run-pipeline")
async def run_ai_pipeline():
    """Run Scanner -> Signals -> Decisions -> Journal."""
    from src.ai_os.pipeline_runner import pipeline_runner

    result = await pipeline_runner.run_daily_pipeline()
    return {
        "status": "completed",
        "result": result.to_dict(),
        "next": "Check /trust/journal, /alerts/today, /portfolio/overview, and /dailybrief/latest.",
    }
