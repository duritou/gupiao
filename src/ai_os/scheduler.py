"""AI Scheduler — daily automated workflow definitions.

Defines WHEN the AI does WHAT, without user intervention.

Daily Rhythm:
  01:00 → Daily Strategy Plan (overnight research and candidate generation)
  09:35 → Market Open Watch + verified-price strategy execution
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


class SchedulePhase(str, Enum):
    PRE_MARKET = "pre_market"        # 01:00
    MARKET_OPEN = "market_open"      # 09:35
    MIDDAY = "midday"                # 11:30
    AFTERNOON = "afternoon"          # 13:30
    LATE_AFTERNOON = "late_afternoon"  # 14:30
    MARKET_CLOSE = "market_close"    # 15:00
    EVENING = "evening"              # 20:00
    WEEKLY = "weekly"                # Saturday
    MONTHLY = "monthly"              # 1st of month


# The scheduler normally fires at these checkpoints. The recovery windows
# stop before a phase would become unsafe or misleading; a missed pre-market
# scan must not suddenly place a new order at noon. Market-close
# reconciliation is safe after the close, so it remains recoverable into the
# evening and can unblock the daily review.
PHASE_SCHEDULE_TIMES: dict[SchedulePhase, time] = {
    SchedulePhase.PRE_MARKET: time(1, 0),
    SchedulePhase.MARKET_OPEN: time(9, 35),
    SchedulePhase.MIDDAY: time(11, 30),
    SchedulePhase.AFTERNOON: time(13, 30),
    SchedulePhase.LATE_AFTERNOON: time(14, 30),
    SchedulePhase.MARKET_CLOSE: time(15, 0),
    SchedulePhase.EVENING: time(20, 0),
}

PHASE_RECOVERY_WINDOWS: dict[SchedulePhase, tuple[time, time]] = {
    # The plan is generated overnight, but recovery remains safe until the
    # opening checkpoint because pre-market scanning never submits orders.
    # Leave the exact 01:00 checkpoint to the cron job.  Starting recovery one
    # minute later prevents the watchdog and the normal job from racing after
    # both become eligible at the same instant.
    SchedulePhase.PRE_MARKET: (time(1, 1), time(9, 20)),
    SchedulePhase.MARKET_OPEN: (time(9, 35), time(11, 15)),
    SchedulePhase.MIDDAY: (time(11, 30), time(13, 20)),
    SchedulePhase.AFTERNOON: (time(13, 30), time(14, 20)),
    SchedulePhase.LATE_AFTERNOON: (time(14, 30), time(14, 55)),
    # Reconciliation does not submit a new opening order and is safe to
    # recover after a late restart, including before the evening review.
    SchedulePhase.MARKET_CLOSE: (time(15, 0), time(23, 30)),
    SchedulePhase.EVENING: (time(20, 0), time(23, 59, 59)),
}


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
        phase=SchedulePhase.PRE_MARKET, name="refresh_market_news",
        description="刷新市场资讯雷达并校验新鲜度",
        event_type="ai_os.market_news.refreshed",
    ),
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
        description="全市场扫描、AI选股，入库候选并等待盘中执行",
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
        phase=SchedulePhase.MARKET_OPEN, name="execute_open_strategy",
        description="开盘后读取凌晨已入库策略，以信号后实时价执行纸面交易",
        event_type="ai_os.open_strategy.executed",
        depends_on=["market_open_check"],
        is_critical=True,
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
    ScheduledTask(
        phase=SchedulePhase.LATE_AFTERNOON, name="late_afternoon_review",
        description="14:30 lightweight market and holding-risk review",
        event_type="ai_os.afternoon.reviewed",
        depends_on=["afternoon_scan"],
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
        SchedulePhase.MARKET_OPEN: [
            task for task in MARKET_HOURS_MONITOR
            if task.phase == SchedulePhase.MARKET_OPEN
        ],
        SchedulePhase.MIDDAY: [
            task for task in MARKET_HOURS_MONITOR
            if task.phase == SchedulePhase.MIDDAY
        ],
        SchedulePhase.AFTERNOON: [
            task for task in MARKET_HOURS_MONITOR
            if task.phase == SchedulePhase.AFTERNOON
        ],
        SchedulePhase.LATE_AFTERNOON: [
            task for task in MARKET_HOURS_MONITOR
            if task.phase == SchedulePhase.LATE_AFTERNOON
        ],
        SchedulePhase.MARKET_CLOSE: [
            task for task in EOD_PROCESSING
            if task.phase == SchedulePhase.MARKET_CLOSE
        ],
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


def get_current_phase(now: datetime | None = None) -> SchedulePhase:
    """Determine which phase the AI should be in based on current time."""
    current = now or datetime.now()
    current_time = current.time()
    weekday = current.weekday()  # 0=Monday, 6=Sunday

    if weekday >= 5:  # Weekend
        if weekday == 5 and time(10, 0) <= current_time <= time(11, 0):
            return SchedulePhase.WEEKLY
        return SchedulePhase.WEEKLY  # Default weekend to weekly available

    # Trading day phases (Mon-Fri)
    if current_time < time(9, 35):
        return SchedulePhase.PRE_MARKET
    elif current_time < time(11, 30):
        return SchedulePhase.MARKET_OPEN
    elif current_time < time(13, 30):
        return SchedulePhase.MIDDAY
    elif current_time < time(14, 30):
        return SchedulePhase.AFTERNOON
    elif current_time < time(15, 0):
        return SchedulePhase.LATE_AFTERNOON
    elif current_time < time(15, 10):
        return SchedulePhase.MARKET_CLOSE
    else:
        return SchedulePhase.EVENING


def get_recoverable_phases(now: datetime | None = None) -> list[SchedulePhase]:
    """Return phases whose scheduled checkpoint may have been missed.

    This is deliberately a pure, local-time calculation. The caller still
    validates the trading calendar before executing a phase. Returning more
    than one phase matters after a late evening restart: close reconciliation
    runs first, then the journal/reflection tasks can run with dependencies
    satisfied.
    """
    current = now or datetime.now()
    if current.weekday() >= 5:
        return []

    current_time = current.time()
    return [
        phase
        for phase, (window_start, window_end) in PHASE_RECOVERY_WINDOWS.items()
        if window_start <= current_time <= window_end
    ]


# Singleton
_scheduler_state: dict[str, DailySchedule] = {}


def get_scheduler_state() -> dict:
    return _scheduler_state
