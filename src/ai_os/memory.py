"""AI Memory — the system's accumulated experience over time.

Every event, every recommendation, every outcome is logged here.
Over days/weeks/months, this becomes the most valuable asset — not code,
but accumulated real-world experience that no competitor can replicate.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any


class EventSource(str, Enum):
    """Where an event originated."""
    MARKET = "market"
    SCANNER = "scanner"
    SIGNAL = "signal"
    ALERT = "alert"
    PORTFOLIO = "portfolio"
    RESEARCH = "research"
    USER = "user"
    TRUST = "trust"
    AI_OS = "ai_os"
    SYSTEM = "system"


@dataclass
class LogEntry:
    """A single event log entry — the atomic unit of AI Memory."""
    id: str = ""
    timestamp: str = ""
    source: str = ""           # EventSource
    event_type: str = ""       # e.g. "scanner.completed", "alert.generated"
    summary: str = ""          # Human-readable one-liner
    detail: dict[str, Any] = field(default_factory=dict)
    related_stock: str = ""    # stock_code if applicable
    metrics: dict[str, float] = field(default_factory=dict)  # Numeric data for later analysis

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "source": self.source,
            "event_type": self.event_type,
            "summary": self.summary,
            "detail": self.detail,
            "related_stock": self.related_stock,
            "metrics": self.metrics,
        }


@dataclass
class DailyMemory:
    """One day's accumulated events and AI reflections."""
    date: str = ""
    day_of_week: str = ""
    entries: list[LogEntry] = field(default_factory=list)

    # Computed
    total_events: int = 0
    recommendations_made: int = 0
    alerts_fired: int = 0
    user_actions: int = 0
    outcomes_recorded: int = 0

    # AI's end-of-day reflection
    daily_summary: str = ""
    lessons_learned: str = ""
    tomorrow_preview: str = ""

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "day_of_week": self.day_of_week,
            "entries": [e.to_dict() for e in self.entries],
            "total_events": self.total_events,
            "recommendations_made": self.recommendations_made,
            "alerts_fired": self.alerts_fired,
            "user_actions": self.user_actions,
            "outcomes_recorded": self.outcomes_recorded,
            "daily_summary": self.daily_summary,
            "lessons_learned": self.lessons_learned,
            "tomorrow_preview": self.tomorrow_preview,
        }


@dataclass
class WeeklyMemory:
    """One week's review — trend analysis and learnings."""
    week_start: str = ""
    week_end: str = ""

    # Stats
    total_recommendations: int = 0
    correct_recommendations: int = 0
    accuracy: float = 0.0
    ai_alpha_pct: float = 0.0
    user_actions: int = 0

    # Insights
    top_performing_strategy: str = ""
    worst_performing_strategy: str = ""
    best_sector: str = ""
    user_behavior_change: str = ""     # e.g. "信任度+8%"
    ai_improvement: str = ""           # e.g. "AI准确率+3%"

    # Summary
    weekly_summary: str = ""
    learning_log: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "week_start": self.week_start,
            "week_end": self.week_end,
            "total_recommendations": self.total_recommendations,
            "correct_recommendations": self.correct_recommendations,
            "accuracy": round(self.accuracy, 2),
            "ai_alpha_pct": round(self.ai_alpha_pct, 2),
            "user_actions": self.user_actions,
            "top_performing_strategy": self.top_performing_strategy,
            "worst_performing_strategy": self.worst_performing_strategy,
            "best_sector": self.best_sector,
            "user_behavior_change": self.user_behavior_change,
            "ai_improvement": self.ai_improvement,
            "weekly_summary": self.weekly_summary,
            "learning_log": self.learning_log,
        }


@dataclass
class MonthlyMemory:
    """One month's review — evolution and growth."""
    month: str = ""

    # Big numbers
    total_recommendations: int = 0
    accuracy: float = 0.0
    ai_alpha_pct: float = 0.0
    user_follow_rate: float = 0.0

    # Evolution
    accuracy_trend: str = ""           # "improving" / "stable" / "declining"
    user_trust_trend: str = ""
    ai_version_jump: str = ""          # e.g. "v5.0 → v6.0: +8% accuracy"

    # Highlights
    best_recommendation: str = ""      # Stock that made the most money
    worst_recommendation: str = ""     # Stock that lost the most
    user_milestone: str = ""           # e.g. "首次连续10次跟随AI"

    # Summary
    monthly_summary: str = ""
    growth_insights: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "month": self.month,
            "total_recommendations": self.total_recommendations,
            "accuracy": round(self.accuracy, 2),
            "ai_alpha_pct": round(self.ai_alpha_pct, 2),
            "user_follow_rate": round(self.user_follow_rate, 2),
            "accuracy_trend": self.accuracy_trend,
            "user_trust_trend": self.user_trust_trend,
            "ai_version_jump": self.ai_version_jump,
            "best_recommendation": self.best_recommendation,
            "worst_recommendation": self.worst_recommendation,
            "user_milestone": self.user_milestone,
            "monthly_summary": self.monthly_summary,
            "growth_insights": self.growth_insights,
        }


class AIMemory:
    """The system's accumulated memory — grows more valuable over time."""

    def __init__(self):
        self._logs: list[LogEntry] = []
        self._daily_memories: dict[str, DailyMemory] = {}
        self._weekly_memories: dict[str, WeeklyMemory] = {}
        self._monthly_memories: dict[str, MonthlyMemory] = {}

    # ================================================================
    # Event Logging
    # ================================================================

    def log(self, source: str, event_type: str, summary: str,
            detail: dict | None = None, related_stock: str = "",
            metrics: dict | None = None) -> LogEntry:
        """Record a single event. Called by every subsystem."""
        now = datetime.now()
        entry = LogEntry(
            id=f"evt_{now.strftime('%Y%m%d_%H%M%S')}_{len(self._logs):04d}",
            timestamp=now.isoformat(),
            source=source,
            event_type=event_type,
            summary=summary,
            detail=detail or {},
            related_stock=related_stock,
            metrics=metrics or {},
        )
        self._logs.append(entry)
        return entry

    def log_batch(self, entries: list[dict]) -> list[LogEntry]:
        """Batch log multiple events at once."""
        results = []
        for e in entries:
            results.append(self.log(
                source=e.get("source", "system"),
                event_type=e.get("event_type", "unknown"),
                summary=e.get("summary", ""),
                detail=e.get("detail"),
                related_stock=e.get("related_stock", ""),
                metrics=e.get("metrics"),
            ))
        return results

    # ================================================================
    # Query
    # ================================================================

    def get_logs(self, source: str = "", limit: int = 100,
                 since: str = "") -> list[LogEntry]:
        """Query event logs with optional filters."""
        logs = self._logs
        if source:
            logs = [l for l in logs if l.source == source]
        if since:
            logs = [l for l in logs if l.timestamp >= since]
        return sorted(logs, key=lambda l: l.timestamp, reverse=True)[:limit]

    def get_today_logs(self) -> list[LogEntry]:
        """Get all events from today."""
        today = datetime.now().strftime("%Y-%m-%d")
        return [l for l in self._logs if l.timestamp.startswith(today)]

    # ================================================================
    # Daily / Weekly / Monthly Memory Generation
    # ================================================================

    def generate_daily_memory(self, trust_data: dict | None = None) -> DailyMemory:
        """Generate today's memory — what happened, what was learned."""
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        today_logs = self.get_today_logs()

        memory = DailyMemory(
            date=today_str,
            day_of_week=["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()],
            entries=today_logs,
            total_events=len(today_logs),
            recommendations_made=sum(1 for l in today_logs if l.event_type.startswith("scanner")),
            alerts_fired=sum(1 for l in today_logs if l.source == "alert"),
            user_actions=sum(1 for l in today_logs if l.source == "user"),
            outcomes_recorded=sum(1 for l in today_logs if l.source == "trust"),
        )

        # Generate AI's daily reflection
        if trust_data:
            recs = trust_data.get("total_recommendations", 0)
            acc = trust_data.get("accuracy", 0)
            alpha = trust_data.get("ai_alpha_pct", 0)
            memory.daily_summary = (
                f"今日AI共发出{recs}条建议，准确率{acc:.0%}。"
                f"AI Alpha {alpha:+.1f}%。"
            )
            if trust_data.get("accuracy_available") or trust_data.get("verified_count"):
                memory.lessons_learned = (
                    "今日结果已写入学习记录。"
                    + ("验证样本暂时为正收益。" if alpha > 0 else "当前没有可确认的正超额收益。")
                )
            else:
                memory.lessons_learned = "今日验证样本不足，暂不生成板块或策略结论。"
            memory.tomorrow_preview = "明日继续等待真实行情与可验证信号，缺失数据时不执行交易。"

        self._daily_memories[today_str] = memory
        return memory

    def generate_weekly_memory(self, trust_data: dict | None = None) -> WeeklyMemory:
        """Generate weekly review from accumulated daily memories."""
        now = datetime.now()
        week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
        week_end = now.strftime("%Y-%m-%d")

        # Aggregate from daily memories this week
        week_days = [
            d for d in self._daily_memories.values()
            if week_start <= d.date <= week_end
        ]

        total_recs = sum(d.recommendations_made for d in week_days)
        total_alerts = sum(d.alerts_fired for d in week_days)
        total_user_acts = sum(d.user_actions for d in week_days)

        acc = float(trust_data.get("accuracy") or 0) if trust_data else 0.0
        alpha = float(trust_data.get("ai_alpha_pct") or 0) if trust_data else 0.0
        verified_count = int(
            (trust_data or {}).get("decisive_verified_decisions")
            or (trust_data or {}).get("verified_count")
            or 0
        )
        has_verified = verified_count > 0
        accuracy_text = f"{acc:.0%}" if has_verified else "暂无"

        memory = WeeklyMemory(
            week_start=week_start, week_end=week_end,
            total_recommendations=total_recs,
            correct_recommendations=int(total_recs * acc) if has_verified else 0,
            accuracy=acc if has_verified else 0.0, ai_alpha_pct=alpha if has_verified else 0.0,
            user_actions=total_user_acts,
            top_performing_strategy="数据不足" if not has_verified else "待按策略标签统计",
            worst_performing_strategy="数据不足" if not has_verified else "待按策略标签统计",
            best_sector="数据不足" if not has_verified else "待按行业标签统计",
            user_behavior_change="数据不足" if total_user_acts == 0 else f"记录到{total_user_acts}次用户操作",
            ai_improvement=(f"本周已验证准确率{accuracy_text}" if has_verified else "暂无足够已验证样本"),
        )

        memory.weekly_summary = (
            f"本周AI共记录{total_recs}条推荐，"
            f"准确率{accuracy_text}，"
            f"AI Alpha {'%+.1f%%' % alpha if has_verified else '暂无'}。"
        )
        memory.learning_log = [
            f"✓ 已记录{total_recs}条推荐和{total_user_acts}次用户操作",
            "✓ 仅使用已验证结果更新准确率和 Alpha" if has_verified else "⚠ 已验证结果不足，不更新策略排名",
            "⚠ 行业和策略表现需要更多带标签的成交结果",
            "→ 下周继续积累真实行情、成交和结果数据",
        ]

        self._weekly_memories[week_start] = memory
        return memory

    def generate_monthly_memory(self) -> MonthlyMemory:
        """Generate monthly review — the AI's growth story."""
        now = datetime.now()
        month = now.strftime("%Y-%m")

        # Aggregate all weekly memories this month
        month_weeks = [
            w for w in self._weekly_memories.values()
            if w.week_start[:7] == month
        ]
        total_recs = sum(w.total_recommendations for w in month_weeks)
        verified_weeks = [w for w in month_weeks if w.total_recommendations and w.accuracy > 0]
        avg_acc = (sum(w.accuracy for w in verified_weeks) / len(verified_weeks)) if verified_weeks else 0.0
        avg_alpha = (sum(w.ai_alpha_pct for w in verified_weeks) / len(verified_weeks)) if verified_weeks else 0.0
        total_actions = sum(w.user_actions for w in month_weeks)

        # Determine trend
        if len(month_weeks) >= 3:
            first_half_acc = sum(w.accuracy for w in month_weeks[:len(month_weeks)//2]) / (len(month_weeks)//2)
            second_half_acc = sum(w.accuracy for w in month_weeks[len(month_weeks)//2:]) / (len(month_weeks) - len(month_weeks)//2)
            trend = "improving" if second_half_acc > first_half_acc + 0.02 else (
                "declining" if second_half_acc < first_half_acc - 0.02 else "stable"
            )
        elif verified_weeks:
            trend = "stable"
        else:
            trend = "insufficient_data"
        accuracy_label = f"{avg_acc:.0%}" if verified_weeks else "暂无"
        alpha_label = f"{avg_alpha:+.1f}%" if verified_weeks else "暂无"

        memory = MonthlyMemory(
            month=month,
            total_recommendations=total_recs,
            accuracy=avg_acc,
            ai_alpha_pct=avg_alpha,
            user_follow_rate=(total_actions / total_recs if total_recs else 0.0),
            accuracy_trend=trend,
            user_trust_trend="数据不足" if not verified_weeks else "待观察",
            ai_version_jump="",
            best_recommendation="暂无已验证推荐" if not verified_weeks else "待按实际收益统计",
            worst_recommendation="暂无已验证推荐" if not verified_weeks else "待按实际收益统计",
            user_milestone="" if total_actions < 10 else f"本月记录{total_actions}次操作",
        )

        memory.monthly_summary = (
            f"{month}月AI共记录{total_recs}条推荐，"
            f"准确率{accuracy_label}，AI Alpha {alpha_label}。"
            f"准确率趋势：{'上升中' if trend == 'improving' else '稳定' if trend == 'stable' else '数据不足'}。"
        )
        memory.growth_insights = [
            f"本月记录{total_recs}条推荐和{total_actions}次用户操作",
            "仅使用有结果的样本更新准确率" if verified_weeks else "没有足够结果样本，不生成策略成长结论",
            "行业和策略收益需要更多可追溯的成交结果",
        ]

        self._monthly_memories[month] = memory
        return memory

    # ================================================================
    # Learning Log (shown in UI)
    # ================================================================

    def get_learning_log(self) -> list[str]:
        """Get the AI's accumulated learning log — 'what I learned this month'."""
        logs: list[str] = []

        # Collect from all weekly memories
        for w in sorted(self._weekly_memories.values(),
                       key=lambda w: w.week_start, reverse=True):
            logs.extend(w.learning_log)

        # Add monthly insights
        for m in sorted(self._monthly_memories.values(),
                       key=lambda m: m.month, reverse=True):
            logs.extend(m.growth_insights)

        return logs[:20]

    def get_timeline(self, days: int = 7) -> list[dict]:
        """Get a chronological timeline of recent events."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        logs = [l for l in self._logs if l.timestamp >= cutoff]
        return [l.to_dict() for l in sorted(logs, key=lambda l: l.timestamp)]


# Singleton
_memory: AIMemory | None = None


def get_ai_memory() -> AIMemory:
    global _memory
    if _memory is None:
        _memory = AIMemory()
    return _memory
