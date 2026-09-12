"""AI Operating System routes backed by real pipeline state."""

import asyncio
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
                "summary": (
                    f"{d.get('stock_name', d.get('stock_code', ''))} "
                    f"score {score:.0f}: {d.get('recommendation', '')}"
                ),
                "related_stock": d.get("stock_code", ""),
                "timestamp": created,
                "ts": created,
                "metrics": {
                    "ai_score": score,
                    "ranking_score": d.get("ranking_score"),
                    "action_score": d.get("action_score"),
                    "research_score": d.get("research_score"),
                    "score_display": d.get("score_display") or {},
                    "score_guarded": bool(d.get("score_guarded")),
                    "score_guard_reasons": d.get("score_guard_reasons") or [],
                    "deep_rating": d.get("deep_rating") or "",
                    "final_review_verdict": d.get("final_review_verdict") or "",
                    "final_buy_approved": d.get("final_buy_approved"),
                    "evidence_enrichment": d.get("evidence_enrichment") or {},
                    "quote_enrichment_status": d.get("quote_enrichment_status"),
                    "quote_enrichment_reason": d.get("quote_enrichment_reason"),
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
    from src.ai_os.task_executor import task_executor
    from src.infrastructure.storage.market_database import market_db

    phase = get_current_phase()
    schedule = get_daily_schedule()
    tasks = get_schedule_for_phase(phase)
    today = date.today().isoformat()
    # Keep slow SQLite reads off FastAPI's event loop. A locked/large journal
    # must not make /system/health look offline to the extension.
    today_count = await asyncio.to_thread(
        market_db.count_decisions_for_date, today,
    )
    decision_stats = await asyncio.to_thread(market_db.get_decision_stats)
    latest_run_audit = await asyncio.to_thread(
        market_db.get_latest_pipeline_run_audit
    )

    # 获取任务执行器状态
    executor_status = await asyncio.to_thread(task_executor.get_status)
    recent_executions = await asyncio.to_thread(
        task_executor.get_recent_executions, 100,
    )
    today_executions = [
        execution
        for execution in recent_executions
        if str(execution.get("completed_at", "")).startswith(today)
    ]
    # get_recent_executions() is newest-first; keep the first row per task.
    latest_by_name = {}
    for execution in today_executions:
        latest_by_name.setdefault(execution["task_name"], execution)
    completed_names = {
        name for name, execution in latest_by_name.items()
        if execution.get("status") == "success"
    }
    failed_names = {
        name for name, execution in latest_by_name.items()
        if execution.get("status") in {"failed", "skipped"}
    }
    total_tasks = len(schedule.tasks)

    return {
        "current_phase": phase.value,
        "phase_label": phase.value,
        "today_progress": {
            "total_tasks": total_tasks,
            "completed": len(completed_names),
            "failed": len(failed_names),
            "completion_pct": round(len(completed_names) / total_tasks * 100, 0)
            if total_tasks else 0,
            "journal_decisions_today": today_count,
            "journal_decisions_total": decision_stats["total_decisions"],
        },
        "current_tasks": [t.name for t in tasks],
        "next_phase": _next_phase(phase.value),
        "data_source": "task_executor + decision_journal",
        "executor": {
            "is_running": executor_status["is_running"],
            "total_executions": executor_status["total_executions"],
            "task_stats": executor_status["task_stats"],
            "strategy_version": executor_status.get("strategy_version", ""),
        },
        "latest_run_audit": latest_run_audit or {
            "acceptance_status": "unverified",
            "reason_codes": ["no_pipeline_run_audit"],
        },
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
    events = await asyncio.to_thread(_journal_events, limit)
    if source:
        events = [e for e in events if e["source"] == source]
    return {"events": events, "total": len(events), "data_source": "decision_journal"}


@router.get("/memory/today")
async def get_today_memory():
    from src.infrastructure.storage.market_database import market_db
    today = date.today().isoformat()
    decisions = [
        decision
        for decision in await asyncio.to_thread(get_journal_decisions, 200)
        if str(decision.get("decision_date", "")).startswith(today)
    ]
    if not decisions:
        decisions = await asyncio.to_thread(get_journal_decisions, 30)
    p1 = [d for d in decisions if float(d.get("ai_score") or 0) >= 80]
    p2 = [d for d in decisions if 65 <= float(d.get("ai_score") or 0) < 80]
    top = decisions[0] if decisions else None
    paper = await asyncio.to_thread(market_db.get_paper_portfolio)
    learning_log = await asyncio.to_thread(market_db.get_learning_log, 50)
    learning = [x for x in learning_log if str(x.get("learning_date")) == today]
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
        "lessons_learned": " ".join(x["lesson"] for x in learning) or "今日尚未生成收盘复盘。",
        "tomorrow_preview": "下一个交易日先读取历史学习日志，再运行选股与纸面交易。",
        "paper_portfolio": paper,
        "learning_entries": learning,
        "data_source": "decision_journal + paper_account + learning_log",
    }


@router.get("/memory/week")
async def get_weekly_memory():
    decisions = await asyncio.to_thread(get_journal_decisions, 200)
    return {
        "period": "week",
        "total_events": len(decisions),
        "summary": f"{len(decisions)} pipeline decisions available in the journal.",
        "data_source": "decision_journal",
    }


@router.get("/memory/month")
async def get_monthly_memory():
    decisions = await asyncio.to_thread(get_journal_decisions, 500)
    return {
        "period": "month",
        "total_events": len(decisions),
        "summary": f"{len(decisions)} pipeline decisions available in the journal.",
        "data_source": "decision_journal",
    }


@router.get("/learning-log")
async def get_learning_log():
    from src.infrastructure.storage.market_database import market_db
    entries = await asyncio.to_thread(market_db.get_learning_log, 100)
    return {
        "learning_log": entries,
        "total_learnings": len(entries),
        "data_source": "persistent learning_log",
    }


@router.get("/strategy-performance")
async def get_strategy_performance():
    """Validated performance by decision layer for weekly strategy review."""
    from src.infrastructure.storage.market_database import market_db

    return await asyncio.to_thread(market_db.get_strategy_performance)


@router.get("/timeline")
async def get_timeline(days: int = Query(7, ge=1, le=30)):
    return {
        "events": await asyncio.to_thread(_journal_events, days * 20),
        "days": days,
        "data_source": "decision_journal",
    }


def _next_phase(current: str) -> str:
    phases = ["pre_market", "market_open", "midday", "afternoon", "market_close", "evening"]
    try:
        idx = phases.index(current)
        return phases[idx + 1] if idx + 1 < len(phases) else "pre_market"
    except ValueError:
        return "unknown"


@router.post("/run-pipeline")
async def run_ai_pipeline(
    force_reanalysis: bool = Query(
        False,
        description=(
            "显式绕过当日深度分析缓存并重新调用 AI；仅重算分析，不执行纸面交易。"
        ),
    ),
):
    """Run Scanner -> Signals -> Decisions -> Journal."""
    from src.ai_os.pipeline_runner import pipeline_runner

    result = await pipeline_runner.run_daily_pipeline(
        force_reanalysis=force_reanalysis,
        execute_paper_trades=False if force_reanalysis else None,
    )
    return {
        "status": "completed",
        "result": result.to_dict(),
        "reanalysis_mode": "forced" if force_reanalysis else "normal",
        "next": "Check /trust/journal, /alerts/today, /portfolio/overview, and /dailybrief/latest.",
    }


@router.get("/task-status")
async def get_task_executor_status():
    """获取任务执行器状态（临时端点）。"""
    from src.ai_os.scheduler import get_current_phase, get_daily_schedule
    from src.ai_os.task_executor import task_executor

    status = await asyncio.to_thread(task_executor.get_status)
    status["current_phase"] = get_current_phase().value
    schedule = get_daily_schedule()
    status["schedule_info"] = {
        "date": schedule.date,
        "total_tasks": len(schedule.tasks),
        "completed": len(schedule.executed),
    }
    return status


@router.get("/task-executions")
async def get_task_executions(limit: int = 20):
    """获取任务执行历史（临时端点）。"""
    from src.ai_os.task_executor import task_executor
    executions = await asyncio.to_thread(task_executor.get_recent_executions, limit)
    return {"executions": executions}


@router.get("/run-audit/{run_id}")
async def get_run_audit(run_id: str):
    """Return the compact, exact-run stage audit without scanning journal JSON."""
    from src.infrastructure.storage.market_database import market_db

    audit = await asyncio.to_thread(market_db.get_pipeline_run_audit, run_id)
    return audit or {
        "run_id": str(run_id or ""),
        "acceptance_status": "unverified",
        "reason_codes": ["run_audit_not_found"],
    }


@router.get("/post-backfill-rerun-status")
async def get_post_backfill_rerun_status(limit: int = 20):
    """Expose durable backfill-gate and research-only rerun state."""
    from src.infrastructure.storage.market_database import market_db

    dispatches = await asyncio.to_thread(
        market_db.get_research_rerun_dispatches, limit
    )
    return {"dispatches": dispatches}
