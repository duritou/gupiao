"""AI Scheduler — daily automated workflow definitions.

Defines WHEN the AI does WHAT, without user intervention.

Daily Rhythm:
  08:30 → Morning Routine (pre-market prep)
  09:25 → Market Open Watch (first 5 min)
  11:30 → Midday Check (morning session review)
  14:30 → Afternoon Scan (pre-close opportunities)
  15:00 → Market Close (EOD processing)
  20:00 → Evening Review (daily journal + trust update)

Weekly:
  Saturday 10:00 → Weekly Review
  Sunday 20:00 → Next Week Preview

Monthly:
  1st 09:00 → Monthly Review + AI Evolution Check
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from typing import Any, Callable


class SchedulePhase(str, Enum):
    PRE_MARKET = "pre_market"        # 08:30
    MARKET_OPEN = "market_open"      # 09:25
    MIDDAY = "midday"                # 11:30
    AFTERNOON = "afternoon"          # 14:30
    MARKET_CLOSE = "market_close"    # 15:00
    EVENING = "evening"              # 20:00
    WEEKLY = "weekly"                # Saturday
    MONTHLY = "monthly"              # 1st of month


@dataclass
class ScheduledTask:
    """A single automated task in the AI's daily workflow."""
    phase: SchedulePhase
    name: str
    description: str
    event_type: str = ""             # Emitted event type
    depends_on: list[str] = field(default_factory=list)  # Task names that must complete first
    is_critical: bool = False        # P0/P1 alerts if this fails


@dataclass
class DailySchedule:
    """Complete daily AI workflow definition."""
    date: str = ""
    tasks: list[ScheduledTask] = field(default_factory=list)
    executed: list[str] = field(default_factory=list)  # Completed task names
    failed: list[str] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""

    @property
    def completion_pct(self) -> float:
        if not self.tasks:
            return 0
        return len(self.executed) / len(self.tasks)


# ================================================================
# Workflow Definitions
# ================================================================

MORNING_ROUTINE = [
    ScheduledTask(
        phase=SchedulePhase.PRE_MARKET, name="sync_market_data",
        description="同步今日行情数据、指数、板块",
        event_type="ai_os.market.synced", is_critical=True,
    ),
    ScheduledTask(
        phase=SchedulePhase.PRE_MARKET, name="update_portfolio",
        description="刷新持仓市值、盈亏、AI评分",
        event_type="ai_os.portfolio.updated",
        depends_on=["sync_market_data"],
    ),
    ScheduledTask(
        phase=SchedulePhase.PRE_MARKET, name="run_scanner",
        description="全市场扫描，发现今日机会",
        event_type="ai_os.scanner.completed",
        depends_on=["sync_market_data"],
    ),
    ScheduledTask(
        phase=SchedulePhase.PRE_MARKET, name="generate_morning_brief",
        description="生成今日晨报",
        event_type="ai_os.brief.generated",
        depends_on=["update_portfolio", "run_scanner"],
        is_critical=True,
    ),
    ScheduledTask(
        phase=SchedulePhase.PRE_MARKET, name="check_alerts",
        description="检测预警条件，生成P0/P1预警",
        event_type="ai_os.alerts.checked",
        depends_on=["update_portfolio", "run_scanner"],
    ),
]

MARKET_HOURS_MONITOR = [
    ScheduledTask(
        phase=SchedulePhase.MARKET_OPEN, name="market_open_check",
        description="开盘5分钟：检测异常波动、大幅跳空",
        event_type="ai_os.market.open_checked",
    ),
    ScheduledTask(
        phase=SchedulePhase.MIDDAY, name="midday_review",
        description="午间检查：上午涨跌统计、Alert回顾",
        event_type="ai_os.midday.reviewed",
    ),
    ScheduledTask(
        phase=SchedulePhase.AFTERNOON, name="afternoon_scan",
        description="午盘机会扫描：尾盘异动、突破信号",
        event_type="ai_os.afternoon.scanned",
        depends_on=["midday_review"],
    ),
]

EOD_PROCESSING = [
    ScheduledTask(
        phase=SchedulePhase.MARKET_CLOSE, name="close_positions_check",
        description="收盘：更新所有持仓的收盘价和当日盈亏",
        event_type="ai_os.market.closed", is_critical=True,
    ),
    ScheduledTask(
        phase=SchedulePhase.MARKET_CLOSE, name="update_outcomes",
        description="更新推荐快照的7d/30d/90d结果",
        event_type="ai_os.outcomes.updated",
        depends_on=["close_positions_check"],
    ),
    ScheduledTask(
        phase=SchedulePhase.MARKET_CLOSE, name="update_trust_metrics",
        description="更新Track Record、AI Alpha",
        event_type="ai_os.trust.updated",
        depends_on=["update_outcomes"],
    ),
    ScheduledTask(
        phase=SchedulePhase.EVENING, name="generate_daily_journal",
        description="生成本日决策日志总结",
        event_type="ai_os.journal.generated",
        depends_on=["update_trust_metrics"],
    ),
    ScheduledTask(
        phase=SchedulePhase.EVENING, name="update_user_model",
        description="更新用户行为画像",
        event_type="ai_os.user_model.updated",
        depends_on=["update_trust_metrics"],
    ),
    ScheduledTask(
        phase=SchedulePhase.EVENING, name="ai_reflection",
        description="AI自我复盘：今日推荐回顾",
        event_type="ai_os.reflection.completed",
        depends_on=["generate_daily_journal"],
    ),
]

WEEKLY_TASKS = [
    ScheduledTask(
        phase=SchedulePhase.WEEKLY, name="weekly_review",
        description="本周AI表现总结：准确率、收益、策略回顾",
        event_type="ai_os.weekly.reviewed",
    ),
    ScheduledTask(
        phase=SchedulePhase.WEEKLY, name="weekly_user_insights",
        description="本周用户行为洞察",
        event_type="ai_os.weekly.user_insights",
        depends_on=["weekly_review"],
    ),
    ScheduledTask(
        phase=SchedulePhase.WEEKLY, name="weekly_learning_log",
        description="AI学习日志：本周学到了什么",
        event_type="ai_os.weekly.learning_log",
        depends_on=["weekly_review"],
    ),
]

MONTHLY_TASKS = [
    ScheduledTask(
        phase=SchedulePhase.MONTHLY, name="monthly_review",
        description="本月AI Alpha、策略演变、用户成长",
        event_type="ai_os.monthly.reviewed",
    ),
    ScheduledTask(
        phase=SchedulePhase.MONTHLY, name="model_evolution_check",
        description="检查AI版本准确率趋势",
        event_type="ai_os.monthly.evolution",
        depends_on=["monthly_review"],
    ),
]

ALL_TASKS = (
    MORNING_ROUTINE + MARKET_HOURS_MONITOR +
    EOD_PROCESSING + WEEKLY_TASKS + MONTHLY_TASKS
)


def get_schedule_for_phase(phase: SchedulePhase) -> list[ScheduledTask]:
    """Get all tasks for a given phase."""
    phase_map = {
        SchedulePhase.PRE_MARKET: MORNING_ROUTINE,
        SchedulePhase.MARKET_OPEN: [MARKET_HOURS_MONITOR[0]],
        SchedulePhase.MIDDAY: [MARKET_HOURS_MONITOR[1]],
        SchedulePhase.AFTERNOON: [MARKET_HOURS_MONITOR[2]],
        SchedulePhase.MARKET_CLOSE: [t for t in EOD_PROCESSING if t.phase == SchedulePhase.MARKET_CLOSE],
        SchedulePhase.EVENING: [t for t in EOD_PROCESSING if t.phase == SchedulePhase.EVENING],
        SchedulePhase.WEEKLY: WEEKLY_TASKS,
        SchedulePhase.MONTHLY: MONTHLY_TASKS,
    }
    return phase_map.get(phase, [])


def get_daily_schedule() -> DailySchedule:
    """Get today's complete schedule."""
    today = datetime.now().strftime("%Y-%m-%d")
    daily_tasks = MORNING_ROUTINE + MARKET_HOURS_MONITOR + [
        t for t in EOD_PROCESSING if t.phase in (SchedulePhase.MARKET_CLOSE, SchedulePhase.EVENING)
    ]
    return DailySchedule(date=today, tasks=daily_tasks)


def get_current_phase() -> SchedulePhase:
    """Determine which phase the AI should be in based on current time."""
    now = datetime.now().time()
    weekday = datetime.now().weekday()  # 0=Monday, 6=Sunday

    if weekday >= 5:  # Weekend
        if weekday == 5 and time(10, 0) <= now <= time(11, 0):
            return SchedulePhase.WEEKLY
        return SchedulePhase.WEEKLY  # Default weekend to weekly available

    # Trading day phases (Mon-Fri)
    if now < time(9, 0):
        return SchedulePhase.PRE_MARKET
    elif now < time(9, 30):
        return SchedulePhase.MARKET_OPEN
    elif now < time(11, 30):
        return SchedulePhase.MIDDAY  # Actually during morning session, but next scheduled checkpoint
    elif now < time(13, 0):
        return SchedulePhase.MIDDAY
    elif now < time(14, 30):
        return SchedulePhase.AFTERNOON
    elif now < time(15, 10):
        return SchedulePhase.MARKET_CLOSE
    else:
        return SchedulePhase.EVENING


# Singleton
_scheduler_state: dict[str, DailySchedule] = {}


def get_scheduler_state() -> dict:
    return _scheduler_state
