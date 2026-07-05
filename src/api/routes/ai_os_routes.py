"""AI Operating System Routes — v7.0.

  GET  /ai-os/status       — Current scheduler phase + task progress
  GET  /ai-os/schedule     — Today's full schedule
  GET  /ai-os/events       — Event log query
  GET  /ai-os/memory/today — Today's memory
  GET  /ai-os/memory/week  — Weekly review
  GET  /ai-os/memory/month — Monthly review
  GET  /ai-os/learning-log — Accumulated AI learnings
  GET  /ai-os/timeline     — Recent event timeline
  POST /ai-os/tick         — Trigger next scheduled phase
"""

from fastapi import APIRouter, Query

from src.ai_os.memory import get_ai_memory
from src.ai_os.scheduler import (
    get_current_phase,
    get_daily_schedule,
    get_schedule_for_phase,
)

router = APIRouter(tags=["ai-os"], prefix="/ai-os")


def _seed_memory():
    """Seed AI memory with simulated events if empty."""
    memory = get_ai_memory()
    if memory._logs:
        return memory

    # Generate a realistic day's worth of events
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")

    events = [
        # Pre-market
        {"source": "ai_os", "event_type": "ai_os.started", "summary": "AI操作系统启动", "ts": f"{today}T08:30:00"},
        {"source": "market", "event_type": "market.synced", "summary": "同步行情数据完成：上证+0.3%，深证+0.5%", "ts": f"{today}T08:30:05"},
        {"source": "portfolio", "event_type": "portfolio.updated", "summary": "刷新5只持仓：总市值¥128.5万，日盈亏+1.2%", "ts": f"{today}T08:30:08", "metrics": {"total_value": 1285000, "daily_pl_pct": 1.2}},
        {"source": "scanner", "event_type": "scanner.completed", "summary": "全市场扫描完成：扫描30只，发现8只候选", "ts": f"{today}T08:30:12", "metrics": {"scanned": 30, "candidates": 8}},
        {"source": "ai_os", "event_type": "brief.generated", "summary": "晨报生成：今日情绪积极72分，热点半导体+机器人", "ts": f"{today}T08:30:15"},
        {"source": "alert", "event_type": "alert.generated", "summary": "生成P1预警：寒武纪AI评分92·强烈买入", "related_stock": "688256.SH", "ts": f"{today}T08:30:18"},
        {"source": "alert", "event_type": "alert.generated", "summary": "生成P1预警：中际旭创AI评分90·强烈买入", "related_stock": "300308.SZ", "ts": f"{today}T08:30:19"},
        # Market open
        {"source": "market", "event_type": "market.opened", "summary": "A股开盘：上证3220，创业板+0.8%", "ts": f"{today}T09:30:00"},
        {"source": "alert", "event_type": "alert.generated", "summary": "开盘异常波动：北方华创高开+3.2%", "related_stock": "002371.SZ", "ts": f"{today}T09:30:15"},
        # Midday
        {"source": "ai_os", "event_type": "midday.reviewed", "summary": "午间回顾：上午涨2865家/跌876家，半导体领涨", "ts": f"{today}T11:30:00"},
        {"source": "portfolio", "event_type": "portfolio.check", "summary": "午间持仓检查：寒武纪+5.2%，茅台-1.1%", "ts": f"{today}T11:30:05"},
        # Afternoon
        {"source": "scanner", "event_type": "afternoon.scanned", "summary": "尾盘扫描：发现1只突破信号（沪硅产业）", "related_stock": "688126.SH", "ts": f"{today}T14:30:00"},
        {"source": "user", "event_type": "user.clicked", "summary": "用户查看寒武纪研究页面", "related_stock": "688256.SH", "ts": f"{today}T14:35:00"},
        {"source": "user", "event_type": "user.action", "summary": "用户买入寒武纪500股@¥218.5", "related_stock": "688256.SH", "ts": f"{today}T14:38:00", "metrics": {"shares": 500, "price": 218.5}},
        # Market close
        {"source": "market", "event_type": "market.closed", "summary": "收盘：上证+0.6%，深证+1.2%，创业板+1.8%", "ts": f"{today}T15:00:00"},
        {"source": "portfolio", "event_type": "portfolio.closed", "summary": "收盘持仓更新：总市值¥131.2万，日盈亏+3.4%", "ts": f"{today}T15:05:00", "metrics": {"total_value": 1312000, "daily_pl_pct": 3.4}},
        {"source": "trust", "event_type": "outcomes.updated", "summary": "更新30天结果：3条推荐到期，2条正确+1条错误", "ts": f"{today}T15:10:00"},
        {"source": "trust", "event_type": "trust.updated", "summary": "更新AI Track Record：30天准确率82%，AI Alpha +40.4%", "ts": f"{today}T15:10:05"},
        # Evening
        {"source": "ai_os", "event_type": "journal.generated", "summary": "生成今日决策日志：5条新记录", "ts": f"{today}T20:00:00"},
        {"source": "ai_os", "event_type": "user_model.updated", "summary": "更新用户画像：跟随率+2%，半导体优势确认", "ts": f"{today}T20:00:05"},
        {"source": "ai_os", "event_type": "reflection.completed", "summary": "AI自我复盘：今日2条推荐被采纳，盘后+1.8%", "ts": f"{today}T20:00:10"},
    ]

    for e in events:
        entry = memory.log(
            source=e["source"],
            event_type=e["event_type"],
            summary=e["summary"],
            related_stock=e.get("related_stock", ""),
            metrics=e.get("metrics", {}),
        )
        # Override timestamp with the simulated time
        entry.timestamp = e["ts"]
        entry.id = f"evt_{e['ts'].replace(':', '').replace('-', '')}_{len(memory._logs):04d}"

    # Also seed yesterday for weekly context
    yesterday = datetime.now() - __import__('datetime').timedelta(days=1)
    yday = yesterday.strftime("%Y-%m-%d")
    e1 = memory.log("ai_os", "ai_os.started", f"AI操作系统启动 ({yday})")
    e1.timestamp = f"{yday}T08:30:00"
    e2 = memory.log("market", "market.closed", f"收盘 ({yday}): 上证-0.3%")
    e2.timestamp = f"{yday}T15:00:00"
    e3 = memory.log("trust", "trust.updated", f"更新AI Track Record ({yday})")
    e3.timestamp = f"{yday}T15:10:00"

    return memory


@router.get("/status")
async def get_ai_os_status():
    """Current AI OS phase and task progress."""
    phase = get_current_phase()
    schedule = get_daily_schedule()
    tasks = get_schedule_for_phase(phase)

    return {
        "current_phase": phase.value,
        "phase_label": {
            "pre_market": "盘前准备", "market_open": "开盘监控",
            "midday": "午间检查", "afternoon": "尾盘扫描",
            "market_close": "收盘处理", "evening": "晚间复盘",
            "weekly": "周度回顾", "monthly": "月度总结",
        }.get(phase.value, phase.value),
        "today_progress": {
            "total_tasks": len(schedule.tasks),
            "completed": len(schedule.executed),
            "failed": len(schedule.failed),
            "completion_pct": round(schedule.completion_pct * 100, 0),
        },
        "current_tasks": [t.name for t in tasks],
        "next_phase": _next_phase(phase),
    }


@router.get("/schedule")
async def get_schedule():
    """Today's full AI workflow schedule."""
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
async def get_events(
    source: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
):
    """Query event log."""
    memory = _seed_memory()
    logs = memory.get_logs(source=source, limit=limit)
    return {
        "events": [l.to_dict() for l in logs],
        "total": len(memory._logs),
    }


@router.get("/memory/today")
async def get_today_memory():
    """Today's AI memory — what happened and what was learned."""
    memory = _seed_memory()
    daily = memory.generate_daily_memory()
    return daily.to_dict()


@router.get("/memory/week")
async def get_weekly_memory():
    """Weekly AI review."""
    memory = _seed_memory()
    # Ensure we have a daily memory first
    if not memory._daily_memories:
        memory.generate_daily_memory()
    weekly = memory.generate_weekly_memory()
    return weekly.to_dict()


@router.get("/memory/month")
async def get_monthly_memory():
    """Monthly AI review."""
    memory = _seed_memory()
    if not memory._weekly_memories:
        memory.generate_daily_memory()
        memory.generate_weekly_memory()
    monthly = memory.generate_monthly_memory()
    return monthly.to_dict()


@router.get("/learning-log")
async def get_learning_log():
    """AI's accumulated learning log — 'what I learned this month'."""
    memory = _seed_memory()
    if not memory._daily_memories:
        memory.generate_daily_memory()
        memory.generate_weekly_memory()
        memory.generate_monthly_memory()
    logs = memory.get_learning_log()
    return {"learning_log": logs, "total_learnings": len(logs)}


@router.get("/timeline")
async def get_timeline(days: int = Query(7, ge=1, le=30)):
    """Recent event timeline for visualization."""
    memory = _seed_memory()
    events = memory.get_timeline(days=days)
    return {"events": events, "days": days}


def _next_phase(current: str) -> str:
    """Predict the next phase."""
    phases = ["pre_market", "market_open", "midday", "afternoon", "market_close", "evening"]
    try:
        idx = phases.index(current)
        return phases[idx + 1] if idx + 1 < len(phases) else "pre_market"
    except ValueError:
        return "unknown"
