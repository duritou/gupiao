"""OutcomeTracker — 研究报告结果跟踪

记录研究报告的预测 vs 实际表现，形成反馈闭环。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TrackedOutcome:
    """单次跟踪结果"""

    report_id: str = ""
    stock_code: str = ""
    stock_name: str = ""

    # 预测
    predicted_score: float = 0.0
    predicted_direction: str = "neutral"
    predicted_at: str = ""

    # 实际表现
    price_at_report: float = 0.0
    price_1w: float = 0.0
    price_1m: float = 0.0
    price_3m: float = 0.0
    return_1w_pct: float = 0.0
    return_1m_pct: float = 0.0
    return_3m_pct: float = 0.0

    # 验证
    direction_correct: bool = False      # 方向判断是否正确
    score_accuracy: str = ""             # "accurate" / "close" / "wrong"


@dataclass
class OutcomeSummary:
    """跟踪汇总"""

    total_tracked: int = 0
    direction_accuracy_pct: float = 0.0    # 方向准确率
    avg_return_1w_pct: float = 0.0
    avg_return_1m_pct: float = 0.0
    avg_return_3m_pct: float = 0.0
    score_correlation: float = 0.0         # 评分与实际收益的相关性
    best_prediction: TrackedOutcome | None = None
    worst_prediction: TrackedOutcome | None = None
    outcomes: list[TrackedOutcome] = field(default_factory=list)


class OutcomeTracker:
    """结果跟踪器 — 验证研究质量

    核心指标:
      - 方向准确率: 预测方向与实际涨跌是否一致
      - 评分相关性: 高评分是否对应高收益
      - 收益跟踪: 1周/1月/3月后的实际表现
    """

    def __init__(self):
        self._outcomes: list[TrackedOutcome] = []

    def track(
        self,
        report_id: str,
        stock_code: str,
        stock_name: str,
        predicted_score: float,
        predicted_direction: str,
        predicted_at: str,
        price_at_report: float,
        price_1w: float = 0.0,
        price_1m: float = 0.0,
        price_3m: float = 0.0,
    ) -> TrackedOutcome:
        """记录一次跟踪"""
        ret_1w = (price_1w / price_at_report - 1) * 100 if price_1w > 0 else 0
        ret_1m = (price_1m / price_at_report - 1) * 100 if price_1m > 0 else 0
        ret_3m = (price_3m / price_at_report - 1) * 100 if price_3m > 0 else 0

        # 方向判断
        actual_direction = "buy" if ret_1m > 0 else "sell"
        direction_correct = predicted_direction == actual_direction

        # 评分准确性
        if abs(predicted_score - 50) < 5:
            score_accuracy = "neutral"
        elif direction_correct:
            score_accuracy = "accurate"
        elif abs(ret_1m) < 2:
            score_accuracy = "close"
        else:
            score_accuracy = "wrong"

        outcome = TrackedOutcome(
            report_id=report_id,
            stock_code=stock_code,
            stock_name=stock_name,
            predicted_score=predicted_score,
            predicted_direction=predicted_direction,
            predicted_at=predicted_at,
            price_at_report=price_at_report,
            price_1w=price_1w,
            price_1m=price_1m,
            price_3m=price_3m,
            return_1w_pct=round(ret_1w, 2),
            return_1m_pct=round(ret_1m, 2),
            return_3m_pct=round(ret_3m, 2),
            direction_correct=direction_correct,
            score_accuracy=score_accuracy,
        )
        self._outcomes.append(outcome)
        return outcome

    def summarize(self) -> OutcomeSummary:
        """汇总统计"""
        if not self._outcomes:
            return OutcomeSummary()

        total = len(self._outcomes)
        correct = sum(1 for o in self._outcomes if o.direction_correct)
        accuracy = correct / total * 100 if total else 0

        avg_1w = sum(o.return_1w_pct for o in self._outcomes) / total
        avg_1m = sum(o.return_1m_pct for o in self._outcomes) / total
        avg_3m = sum(o.return_3m_pct for o in self._outcomes) / total

        # 评分与收益的简单相关性（方向一致率）
        high_score = [o for o in self._outcomes if o.predicted_score >= 70]
        if high_score:
            high_correct = sum(1 for o in high_score if o.direction_correct)
            correlation = high_correct / len(high_score) * 100
        else:
            correlation = 0

        # 最佳/最差
        sorted_by_return = sorted(self._outcomes, key=lambda o: o.return_1m_pct, reverse=True)

        return OutcomeSummary(
            total_tracked=total,
            direction_accuracy_pct=round(accuracy, 1),
            avg_return_1w_pct=round(avg_1w, 2),
            avg_return_1m_pct=round(avg_1m, 2),
            avg_return_3m_pct=round(avg_3m, 2),
            score_correlation=round(correlation, 1),
            best_prediction=sorted_by_return[0] if sorted_by_return else None,
            worst_prediction=sorted_by_return[-1] if sorted_by_return else None,
            outcomes=list(self._outcomes),
        )

    @property
    def count(self) -> int:
        return len(self._outcomes)
