"""Trust domain model — the foundation of AI accountability.

v5.0's single source of truth: every AI recommendation is captured as a
RecommendationSnapshot at the moment it's made, then tracked through user
action → outcome at 7d/30d/90d. This powers:
  - AI Track Record: accuracy stats, strategy breakdowns, streaks
  - Decision Journal: AI vs user — who was right?
  - Model Evolution: version-over-version accuracy trends
  - AI Resume: cumulative trust metrics
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class RecDirection(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class UserActionType(str, Enum):
    BOUGHT = "bought"        # User followed buy recommendation
    SOLD = "sold"            # User followed sell recommendation
    HELD = "held"            # User followed hold recommendation
    IGNORED = "ignored"      # User saw but didn't act
    PARTIAL = "partial"      # User acted partially (e.g. bought 50% of suggested)
    OPPOSITE = "opposite"    # User did the opposite of recommendation


class OutcomeVerdict(str, Enum):
    CORRECT = "correct"          # AI direction was right
    WRONG = "wrong"              # AI direction was wrong
    PARTIALLY_CORRECT = "partial"  # Direction right but magnitude off
    PENDING = "pending"          # Not enough time yet
    EXPIRED = "expired"          # Recommendation no longer relevant


@dataclass
class SignalSnapshot:
    """Frozen signal state at recommendation time."""
    name: str = ""            # MACD, RSI, MA, Volume, etc.
    score: float = 0.0        # 0-100
    direction: str = "neutral"

    def to_dict(self) -> dict:
        return {"name": self.name, "score": round(self.score, 1), "direction": self.direction}


@dataclass
class MarketSnapshot:
    """Frozen market context at recommendation time."""
    index_level: float = 0.0       # 上证指数
    index_change_pct: float = 0.0  # 当日涨跌幅
    market_breadth_up: int = 0
    market_breadth_down: int = 0
    northbound_flow: float = 0.0   # 北向资金净流入(亿)
    sector_score: float = 50.0     # 行业评分
    sentiment: float = 50.0        # 市场情绪 0-100

    def to_dict(self) -> dict:
        return {
            "index_level": round(self.index_level, 2),
            "index_change_pct": round(self.index_change_pct, 2),
            "market_breadth_up": self.market_breadth_up,
            "market_breadth_down": self.market_breadth_down,
            "northbound_flow": round(self.northbound_flow, 2),
            "sector_score": round(self.sector_score, 1),
            "sentiment": round(self.sentiment, 1),
        }


@dataclass
class OutcomePoint:
    """Outcome at a specific checkpoint (7d/30d/90d)."""
    days: int = 0
    price: float = 0.0
    profit_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    was_correct: bool | None = None  # None = not enough time yet
    verdict: str = "pending"

    def to_dict(self) -> dict:
        return {
            "days": self.days,
            "price": round(self.price, 2),
            "profit_pct": round(self.profit_pct, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "was_correct": self.was_correct,
            "verdict": self.verdict,
        }


@dataclass
class RecommendationSnapshot:
    """Complete snapshot of an AI recommendation — the trust data atom.

    Every time the AI makes a recommendation (via Alert, Scanner, or Portfolio),
    this snapshot is created. It captures WHAT was recommended, WHY, and what
    happened next.
    """

    id: str = ""
    created_at: str = ""

    # What was recommended
    stock_code: str = ""
    stock_name: str = ""
    direction: str = "buy"           # buy / sell / hold
    price_at_rec: float = 0.0
    ai_score: float = 50.0
    ai_confidence: float = 0.0

    # Why — frozen evidence at recommendation time
    signals: list[SignalSnapshot] = field(default_factory=list)
    market_snapshot: MarketSnapshot | None = None
    knowledge_context: str = ""      # e.g. "半导体行业景气度提升"
    recommendation_text: str = ""    # What the AI said

    # Source
    source: str = ""                 # alert / scanner / portfolio / manual
    alert_id: str = ""               # Link back to alert if from Alert Intelligence
    ai_version: str = ""             # e.g. "v4.2"
    model_info: str = ""             # e.g. "deepseek-v4-pro"

    # User response
    user_action: str = ""            # bought / sold / held / ignored / partial / opposite
    user_action_at: str = ""
    user_action_price: float = 0.0
    user_notes: str = ""             # User's reasoning at the time

    # Outcomes at checkpoints
    outcome_7d: OutcomePoint | None = None
    outcome_30d: OutcomePoint | None = None
    outcome_90d: OutcomePoint | None = None

    # Final verdict
    final_verdict: str = "pending"   # correct / wrong / partial / pending
    final_profit_pct: float = 0.0

    # Reflection (filled later by Learning Engine)
    ai_reflection: str = ""          # AI's own analysis of why it was right/wrong
    reflection_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "direction": self.direction,
            "price_at_rec": round(self.price_at_rec, 2),
            "ai_score": round(self.ai_score, 1),
            "ai_confidence": round(self.ai_confidence, 2),
            "signals": [s.to_dict() for s in self.signals],
            "market_snapshot": self.market_snapshot.to_dict() if self.market_snapshot else None,
            "knowledge_context": self.knowledge_context,
            "recommendation_text": self.recommendation_text,
            "source": self.source,
            "alert_id": self.alert_id,
            "ai_version": self.ai_version,
            "model_info": self.model_info,
            "user_action": self.user_action,
            "user_action_at": self.user_action_at,
            "user_action_price": round(self.user_action_price, 2) if self.user_action_price else 0,
            "user_notes": self.user_notes,
            "outcome_7d": self.outcome_7d.to_dict() if self.outcome_7d else None,
            "outcome_30d": self.outcome_30d.to_dict() if self.outcome_30d else None,
            "outcome_90d": self.outcome_90d.to_dict() if self.outcome_90d else None,
            "final_verdict": self.final_verdict,
            "final_profit_pct": round(self.final_profit_pct, 2),
            "ai_reflection": self.ai_reflection,
            "reflection_at": self.reflection_at,
        }


# ================================================================
# Track Record — computed statistics
# ================================================================

@dataclass
class TrackRecord:
    """AI performance statistics over a time window."""

    period_days: int = 30
    period_label: str = "最近30天"

    # Overall
    total_recommendations: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    pending_count: int = 0
    accuracy: float = 0.0              # 0-1

    # Returns
    avg_return_pct: float = 0.0
    avg_holding_days: float = 0.0
    total_return_pct: float = 0.0      # If user followed every recommendation
    avg_max_drawdown_pct: float = 0.0

    # Benchmark comparison
    beat_index_pct: float = 0.0        # How much better than 沪深300

    # Streaks
    current_streak: int = 0            # Current consecutive correct
    longest_streak: int = 0            # Best streak ever
    current_streak_direction: str = "correct"

    # User behavior
    user_follow_rate: float = 0.0      # % of recs user acted on
    user_followed_accuracy: float = 0.0  # Accuracy when user followed
    user_ignored_accuracy: float = 0.0   # Accuracy when user ignored
    missed_opportunity_total: float = 0.0  # Total % user missed by not following

    def to_dict(self) -> dict:
        return {
            "period_days": self.period_days,
            "period_label": self.period_label,
            "total_recommendations": self.total_recommendations,
            "correct_count": self.correct_count,
            "wrong_count": self.wrong_count,
            "pending_count": self.pending_count,
            "accuracy": round(self.accuracy, 2),
            "avg_return_pct": round(self.avg_return_pct, 2),
            "avg_holding_days": round(self.avg_holding_days, 1),
            "total_return_pct": round(self.total_return_pct, 2),
            "avg_max_drawdown_pct": round(self.avg_max_drawdown_pct, 2),
            "beat_index_pct": round(self.beat_index_pct, 2),
            "current_streak": self.current_streak,
            "longest_streak": self.longest_streak,
            "current_streak_direction": self.current_streak_direction,
            "user_follow_rate": round(self.user_follow_rate, 2),
            "user_followed_accuracy": round(self.user_followed_accuracy, 2),
            "user_ignored_accuracy": round(self.user_ignored_accuracy, 2),
            "missed_opportunity_total": round(self.missed_opportunity_total, 2),
        }


@dataclass
class StrategyBreakdown:
    """Accuracy breakdown by strategy/signal type."""

    strategy: str = ""           # e.g. "MACD金叉", "AI评分>90", "放量突破"
    total: int = 0
    correct: int = 0
    accuracy: float = 0.0
    avg_return: float = 0.0

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "total": self.total,
            "correct": self.correct,
            "accuracy": round(self.accuracy, 2),
            "avg_return": round(self.avg_return, 2),
        }


@dataclass
class ScoreRangeBreakdown:
    """Accuracy breakdown by AI score range."""

    range_label: str = ""        # e.g. "90-100", "80-90", "70-80", "<70"
    range_min: int = 0
    range_max: int = 100
    total: int = 0
    correct: int = 0
    accuracy: float = 0.0
    avg_return: float = 0.0

    def to_dict(self) -> dict:
        return {
            "range_label": self.range_label,
            "range_min": self.range_min,
            "range_max": self.range_max,
            "total": self.total,
            "correct": self.correct,
            "accuracy": round(self.accuracy, 2),
            "avg_return": round(self.avg_return, 2),
        }


@dataclass
class ModelVersion:
    """AI version with performance metrics."""

    version: str = ""            # e.g. "v4.0", "v4.1", "v4.2", "v5.0"
    released_at: str = ""
    total_recs: int = 0
    correct: int = 0
    accuracy: float = 0.0
    avg_return: float = 0.0
    change_vs_prev: float = 0.0  # Accuracy change from previous version

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "released_at": self.released_at,
            "total_recs": self.total_recs,
            "correct": self.correct,
            "accuracy": round(self.accuracy, 2),
            "avg_return": round(self.avg_return, 2),
            "change_vs_prev": round(self.change_vs_prev, 2),
        }


@dataclass
class AIResume:
    """Cumulative AI trust profile — the 'AI Resume' page."""

    established: str = ""
    total_studies: int = 0           # Total stocks analyzed
    total_recommendations: int = 0
    correct_count: int = 0
    overall_accuracy: float = 0.0
    cumulative_user_return: float = 0.0  # Total % return for user
    avg_return_per_rec: float = 0.0
    longest_streak: int = 0
    current_streak: int = 0
    best_strategy: str = ""          # Highest accuracy strategy
    best_strategy_accuracy: float = 0.0
    versions: list[dict] = field(default_factory=list)  # ModelVersion dicts
    monthly_accuracy: list[dict] = field(default_factory=list)  # [{month, accuracy}]

    def to_dict(self) -> dict:
        return {
            "established": self.established,
            "total_studies": self.total_studies,
            "total_recommendations": self.total_recommendations,
            "correct_count": self.correct_count,
            "overall_accuracy": round(self.overall_accuracy, 2),
            "cumulative_user_return": round(self.cumulative_user_return, 2),
            "avg_return_per_rec": round(self.avg_return_per_rec, 2),
            "longest_streak": self.longest_streak,
            "current_streak": self.current_streak,
            "best_strategy": self.best_strategy,
            "best_strategy_accuracy": round(self.best_strategy_accuracy, 2),
            "versions": self.versions,
            "monthly_accuracy": self.monthly_accuracy,
        }


# ================================================================
# Decision Journal — individual entries
# ================================================================

@dataclass
class JournalEntry:
    """A single decision journal entry — AI recommendation + user action + outcome."""

    snapshot: RecommendationSnapshot | None = None

    # Computed for display
    outcome_emoji: str = ""          # ✅ / ❌ / ⏳
    ai_was_right: bool | None = None
    user_followed: bool = False
    lesson: str = ""                 # Auto-generated lesson

    def to_dict(self) -> dict:
        return {
            "snapshot": self.snapshot.to_dict() if self.snapshot else None,
            "outcome_emoji": self.outcome_emoji,
            "ai_was_right": self.ai_was_right,
            "user_followed": self.user_followed,
            "lesson": self.lesson,
        }


@dataclass
class JournalSummary:
    """Aggregate journal statistics."""

    total_entries: int = 0
    ai_correct_count: int = 0
    ai_wrong_count: int = 0
    user_followed_count: int = 0
    user_ignored_count: int = 0
    followed_and_correct: int = 0     # AI right + user followed → win
    followed_and_wrong: int = 0       # AI wrong + user followed → loss
    ignored_and_correct: int = 0      # AI right + user ignored → missed opportunity
    missed_profit_total: float = 0.0  # Total % missed by ignoring AI
    top_lesson: str = ""              # Most important behavioral insight

    def to_dict(self) -> dict:
        return {
            "total_entries": self.total_entries,
            "ai_correct_count": self.ai_correct_count,
            "ai_wrong_count": self.ai_wrong_count,
            "user_followed_count": self.user_followed_count,
            "user_ignored_count": self.user_ignored_count,
            "followed_and_correct": self.followed_and_correct,
            "followed_and_wrong": self.followed_and_wrong,
            "ignored_and_correct": self.ignored_and_correct,
            "missed_profit_total": round(self.missed_profit_total, 2),
            "top_lesson": self.top_lesson,
        }
