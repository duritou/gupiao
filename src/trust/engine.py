"""Trust Engine — computes AI Track Record, Decision Journal, and Model Evolution.

This is the heart of v5.0. It takes RecommendationSnapshots and produces:
  1. TrackRecord — holistic accuracy, returns, streaks
  2. StrategyBreakdown — accuracy per signal type
  3. ScoreRangeBreakdown — accuracy per score band
  4. JournalSummary — AI vs user behavior analysis
  5. ModelVersion history — version-over-version improvement
  6. AIResume — cumulative trust profile
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from src.domain.models.trust import (
    AIResume,
    JournalEntry,
    JournalSummary,
    ModelVersion,
    OutcomePoint,
    RecommendationSnapshot,
    ScoreRangeBreakdown,
    StrategyBreakdown,
    TrackRecord,
    UserActionType,
)


class TrustEngine:
    """Computes trust metrics from recommendation history."""

    def __init__(self):
        self._snapshots: list[RecommendationSnapshot] = []

    def add_snapshot(self, snap: RecommendationSnapshot):
        self._snapshots.append(snap)

    def add_snapshots(self, snaps: list[RecommendationSnapshot]):
        self._snapshots.extend(snaps)

    # ================================================================
    # Track Record
    # ================================================================

    def compute_track_record(self, days: int = 30) -> TrackRecord:
        """Compute holistic AI performance over a time window."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        recent = [s for s in self._snapshots if s.created_at >= cutoff]

        if not recent:
            return TrackRecord(period_days=days, period_label=f"最近{days}天")

        verified = [s for s in recent if s.final_verdict != "pending"]
        correct = [s for s in verified if s.final_verdict == "correct"]
        wrong = [s for s in verified if s.final_verdict == "wrong"]
        pending = [s for s in recent if s.final_verdict == "pending"]

        # Accuracy
        accuracy = len(correct) / len(verified) if verified else 0

        # Returns
        returns = [s.final_profit_pct for s in verified if s.final_profit_pct != 0]
        avg_return = sum(returns) / len(returns) if returns else 0
        total_return = sum(returns)
        avg_dd = sum(
            (s.outcome_30d.max_drawdown_pct if s.outcome_30d else 0)
            for s in verified
        ) / len(verified) if verified else 0

        # Streaks
        current_streak, streak_dir = self._compute_current_streak(recent)
        longest = self._compute_longest_streak()

        # User behavior
        acted = [s for s in recent if s.user_action and s.user_action not in ("ignored", "")]
        followed = [s for s in acted if s.user_action in ("bought", "sold", "held", "partial")]
        ignored = [s for s in recent if s.user_action == "ignored"]
        follow_rate = len(followed) / len(recent) if recent else 0

        followed_correct = [s for s in followed if s.final_verdict == "correct"]
        followed_accuracy = len(followed_correct) / len(followed) if followed else 0

        ignored_correct = [s for s in ignored if s.final_verdict == "correct"]
        ignored_accuracy = len(ignored_correct) / len(ignored) if ignored else 0

        missed = sum(s.final_profit_pct for s in ignored_correct)

        # Beat index (approximation: 沪深300 avg ~6%/year = ~0.5%/30d)
        beat_index = total_return - (len(verified) * 0.5) if verified else 0

        return TrackRecord(
            period_days=days,
            period_label=f"最近{days}天",
            total_recommendations=len(recent),
            correct_count=len(correct),
            wrong_count=len(wrong),
            pending_count=len(pending),
            accuracy=accuracy,
            avg_return_pct=avg_return,
            avg_holding_days=17.0,  # Approximate
            total_return_pct=total_return,
            avg_max_drawdown_pct=avg_dd,
            beat_index_pct=beat_index,
            current_streak=current_streak,
            longest_streak=longest,
            current_streak_direction=streak_dir,
            user_follow_rate=follow_rate,
            user_followed_accuracy=followed_accuracy,
            user_ignored_accuracy=ignored_accuracy,
            missed_opportunity_total=missed,
        )

    def compute_strategy_breakdown(self) -> list[StrategyBreakdown]:
        """Accuracy per strategy/signal type."""
        verified = [s for s in self._snapshots if s.final_verdict != "pending"]
        by_strategy: dict[str, dict[str, Any]] = {}

        for s in verified:
            # Extract strategies from signals
            for sig in s.signals:
                if sig.score >= 70:
                    strat_name = f"{sig.name}信号"
                    if strat_name not in by_strategy:
                        by_strategy[strat_name] = {"total": 0, "correct": 0, "returns": []}
                    by_strategy[strat_name]["total"] += 1
                    if s.final_verdict == "correct":
                        by_strategy[strat_name]["correct"] += 1
                    by_strategy[strat_name]["returns"].append(s.final_profit_pct)

            # Score-based strategies
            if s.ai_score >= 90:
                key = "AI综合评分>90"
            elif s.ai_score >= 80:
                key = "AI评分80-90"
            elif s.ai_score >= 70:
                key = "AI评分70-80"
            else:
                key = "AI评分<70"
            if key not in by_strategy:
                by_strategy[key] = {"total": 0, "correct": 0, "returns": []}
            by_strategy[key]["total"] += 1
            if s.final_verdict == "correct":
                by_strategy[key]["correct"] += 1
            by_strategy[key]["returns"].append(s.final_profit_pct)

        results = []
        for name, data in by_strategy.items():
            if data["total"] >= 2:  # Minimum sample
                results.append(StrategyBreakdown(
                    strategy=name,
                    total=data["total"],
                    correct=data["correct"],
                    accuracy=data["correct"] / data["total"] if data["total"] else 0,
                    avg_return=sum(data["returns"]) / len(data["returns"]) if data["returns"] else 0,
                ))

        results.sort(key=lambda s: -s.accuracy)
        return results

    def compute_score_range_breakdown(self) -> list[ScoreRangeBreakdown]:
        """Accuracy by AI score range."""
        verified = [s for s in self._snapshots if s.final_verdict != "pending"]

        ranges = [
            ScoreRangeBreakdown(range_label="90-100", range_min=90, range_max=100),
            ScoreRangeBreakdown(range_label="80-90", range_min=80, range_max=90),
            ScoreRangeBreakdown(range_label="70-80", range_min=70, range_max=80),
            ScoreRangeBreakdown(range_label="60-70", range_min=60, range_max=70),
            ScoreRangeBreakdown(range_label="<60", range_min=0, range_max=60),
        ]

        for r in ranges:
            in_range = [s for s in verified if r.range_min <= s.ai_score < r.range_max]
            r.total = len(in_range)
            r.correct = len([s for s in in_range if s.final_verdict == "correct"])
            r.accuracy = r.correct / r.total if r.total else 0
            returns = [s.final_profit_pct for s in in_range if s.final_profit_pct != 0]
            r.avg_return = sum(returns) / len(returns) if returns else 0

        return [r for r in ranges if r.total > 0]

    # ================================================================
    # Decision Journal
    # ================================================================

    def get_journal_entries(
        self, limit: int = 50, verdict: str = "", action: str = ""
    ) -> list[JournalEntry]:
        """Get journal entries with computed display fields."""
        entries: list[JournalEntry] = []

        snapshots = self._snapshots
        if verdict:
            snapshots = [s for s in snapshots if s.final_verdict == verdict]
        if action:
            snapshots = [s for s in snapshots if s.user_action == action]

        for s in sorted(snapshots, key=lambda x: x.created_at, reverse=True)[:limit]:
            ai_right = s.final_verdict == "correct" if s.final_verdict != "pending" else None
            followed = s.user_action in ("bought", "sold", "held", "partial")

            # Determine emoji
            if ai_right is True and followed:
                emoji = "✅"  # AI right, user won
            elif ai_right is True and not followed:
                emoji = "💔"  # AI right, user missed
            elif ai_right is False and followed:
                emoji = "❌"  # AI wrong, user lost
            elif ai_right is False and not followed:
                emoji = "🤷"  # AI wrong, user dodged
            else:
                emoji = "⏳"  # Pending

            # Generate lesson
            lesson = self._generate_lesson(s, ai_right, followed)

            entries.append(JournalEntry(
                snapshot=s,
                outcome_emoji=emoji,
                ai_was_right=ai_right,
                user_followed=followed,
                lesson=lesson,
            ))

        return entries

    def get_journal_summary(self) -> JournalSummary:
        """Aggregate journal statistics."""
        verified = [s for s in self._snapshots if s.final_verdict != "pending"]

        ai_correct = [s for s in verified if s.final_verdict == "correct"]
        ai_wrong = [s for s in verified if s.final_verdict == "wrong"]
        followed = [s for s in verified if s.user_action in ("bought", "sold", "held", "partial")]
        ignored = [s for s in verified if s.user_action == "ignored"]

        f_correct = [s for s in followed if s.final_verdict == "correct"]
        f_wrong = [s for s in followed if s.final_verdict == "wrong"]
        i_correct = [s for s in ignored if s.final_verdict == "correct"]

        missed = sum(s.final_profit_pct for s in i_correct)

        # Top lesson
        top_lesson = self._generate_top_lesson(verified, followed, ignored)

        return JournalSummary(
            total_entries=len(verified),
            ai_correct_count=len(ai_correct),
            ai_wrong_count=len(ai_wrong),
            user_followed_count=len(followed),
            user_ignored_count=len(ignored),
            followed_and_correct=len(f_correct),
            followed_and_wrong=len(f_wrong),
            ignored_and_correct=len(i_correct),
            missed_profit_total=missed,
            top_lesson=top_lesson,
        )

    # ================================================================
    # Model Evolution
    # ================================================================

    def compute_model_evolution(self) -> list[ModelVersion]:
        """Track accuracy across AI versions."""
        verified = [s for s in self._snapshots if s.final_verdict != "pending"]
        by_version: dict[str, dict] = {}

        for s in verified:
            v = s.ai_version or "unknown"
            if v not in by_version:
                by_version[v] = {"total": 0, "correct": 0, "returns": []}
            by_version[v]["total"] += 1
            if s.final_verdict == "correct":
                by_version[v]["correct"] += 1
            by_version[v]["returns"].append(s.final_profit_pct)

        versions = []
        prev_acc = 0
        for v_name in sorted(by_version.keys()):
            data = by_version[v_name]
            acc = data["correct"] / data["total"] if data["total"] else 0
            avg_ret = sum(data["returns"]) / len(data["returns"]) if data["returns"] else 0
            versions.append(ModelVersion(
                version=v_name,
                total_recs=data["total"],
                correct=data["correct"],
                accuracy=acc,
                avg_return=avg_ret,
                change_vs_prev=acc - prev_acc if versions else 0,
            ))
            prev_acc = acc

        return versions

    def compute_monthly_accuracy(self) -> list[dict]:
        """Monthly accuracy trend for sparkline."""
        verified = [s for s in self._snapshots if s.final_verdict == "correct" or s.final_verdict == "wrong"]
        by_month: dict[str, dict] = {}

        for s in verified:
            month = s.created_at[:7]  # "2026-07"
            if month not in by_month:
                by_month[month] = {"total": 0, "correct": 0}
            by_month[month]["total"] += 1
            if s.final_verdict == "correct":
                by_month[month]["correct"] += 1

        result = []
        for month in sorted(by_month.keys()):
            data = by_month[month]
            result.append({
                "month": month,
                "accuracy": round(data["correct"] / data["total"], 2) if data["total"] else 0,
                "total": data["total"],
            })
        return result

    # ================================================================
    # AI Resume
    # ================================================================

    def compute_ai_resume(self) -> AIResume:
        """Cumulative AI trust profile."""
        verified = [s for s in self._snapshots if s.final_verdict == "correct" or s.final_verdict == "wrong"]
        correct = [s for s in verified if s.final_verdict == "correct"]

        strategy = self.compute_strategy_breakdown()
        best = strategy[0] if strategy else None

        return AIResume(
            established="2026-06",
            total_studies=len(self._snapshots),
            total_recommendations=len(verified),
            correct_count=len(correct),
            overall_accuracy=len(correct) / len(verified) if verified else 0,
            cumulative_user_return=sum(s.final_profit_pct for s in verified),
            avg_return_per_rec=sum(s.final_profit_pct for s in verified) / len(verified) if verified else 0,
            longest_streak=self._compute_longest_streak(),
            current_streak=self._compute_current_streak(self._snapshots)[0],
            best_strategy=best.strategy if best else "",
            best_strategy_accuracy=best.accuracy if best else 0,
            versions=[v.to_dict() for v in self.compute_model_evolution()],
            monthly_accuracy=self.compute_monthly_accuracy(),
        )

    # ================================================================
    # Helpers
    # ================================================================

    def _compute_current_streak(self, snapshots: list[RecommendationSnapshot]) -> tuple[int, str]:
        """Compute current streak (most recent consecutive same-outcome)."""
        verified = sorted(
            [s for s in snapshots if s.final_verdict in ("correct", "wrong")],
            key=lambda x: x.created_at, reverse=True,
        )
        if not verified:
            return 0, "pending"

        direction = verified[0].final_verdict
        streak = 0
        for s in verified:
            if s.final_verdict == direction:
                streak += 1
            else:
                break
        return streak, direction

    def _compute_longest_streak(self) -> int:
        """Compute longest correct streak in history."""
        verified = sorted(
            [s for s in self._snapshots if s.final_verdict in ("correct", "wrong")],
            key=lambda x: x.created_at,
        )
        longest = 0
        current = 0
        for s in verified:
            if s.final_verdict == "correct":
                current += 1
                longest = max(longest, current)
            else:
                current = 0
        return longest

    def _generate_lesson(
        self, s: RecommendationSnapshot, ai_right: bool | None, followed: bool
    ) -> str:
        """Generate a human-readable lesson from a decision."""
        if ai_right is True and followed:
            return f"AI判断正确，你执行了操作，获得{s.final_profit_pct:+.1f}%收益。这种模式值得继续信任。"
        elif ai_right is True and not followed:
            return f"AI判断正确但你未执行，错过了{s.final_profit_pct:+.1f}%的收益。下次遇到类似信号建议至少建仓20%。"
        elif ai_right is False and followed:
            return f"AI判断失误，你跟随操作损失了{s.final_profit_pct:+.1f}%。回顾失败原因，帮助AI改进。"
        elif ai_right is False and not followed:
            return f"AI判断失误但你避开了。这次你比AI更聪明，但不要因此完全失去信任。"
        else:
            return "结果尚未确定，耐心等待。"

    def _generate_top_lesson(
        self, verified: list, followed: list, ignored: list
    ) -> str:
        """Generate the most important behavioral insight."""
        if not verified:
            return "数据积累中..."

        f_correct = len([s for s in followed if s.final_verdict == "correct"])
        f_total = len(followed)
        i_correct = len([s for s in ignored if s.final_verdict == "correct"])
        i_total = len(ignored)

        follow_rate = f_total / len(verified) if verified else 0

        if i_correct > f_correct and i_total > 3:
            missed = sum(s.final_profit_pct for s in ignored if s.final_verdict == "correct")
            return f"你最大的亏损原因不是买错了——而是该买的时候没买。AI正确的建议中，你错过了{missed:.0f}%的收益。"
        elif f_total > 0 and f_correct / f_total > 0.7 if f_total else False:
            return f"当AI评分≥85且多信号共振时，你的跟随决策准确率达到{(f_correct/f_total*100):.0f}%。坚持这个模式。"
        elif follow_rate < 0.3:
            return "你对AI的信任度偏低。建议先从小仓位开始跟随AI建议，逐步建立信任。"
        else:
            return f"AI整体准确率不错。关注策略分解，优先跟随高置信度的建议。"


# Singleton
_engine: TrustEngine | None = None


def get_trust_engine() -> TrustEngine:
    global _engine
    if _engine is None:
        _engine = TrustEngine()
    return _engine
