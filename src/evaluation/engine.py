"""Evaluation Center — 系统自我验证引擎

四层验证:
  1. Data Validation — 多源交叉校验数据准确性
  2. Signal Validation — Golden Dataset 验证指标计算
  3. Research Validation — 跟踪预测 vs 实际表现
  4. Accuracy Report — 统计准确率/误报率/收益率

核心理念: 系统记录、验证、统计、建议；人决定是否调整。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date


# ============================================================
# Layer 1: Data Validation
# ============================================================

@dataclass
class DataValidationResult:
    """数据校验结果"""
    stock_code: str
    field: str                 # "close" / "volume" / ...
    sources: dict[str, float]  # {"akshare":1680,"tushare":1680,"yahoo":1679}
    consensus: float = 0.0     # 多源一致值
    max_deviation_pct: float = 0.0
    is_reliable: bool = True
    warning: str = ""


class DataValidator:
    """数据校验器 — 多源交叉验证"""

    DEVIATION_THRESHOLD = 0.5  # 0.5% 偏差阈值

    def validate(self, stock_code: str, field: str,
                 sources: dict[str, float]) -> DataValidationResult:
        if len(sources) < 2:
            values = list(sources.values())
            return DataValidationResult(
                stock_code=stock_code, field=field,
                sources=sources, consensus=values[0] if values else 0,
                warning="仅单一数据源" if sources else "无数据",
                is_reliable=len(sources) > 0,
            )

        values = list(sources.values())
        consensus = sum(values) / len(values)
        max_dev = max(abs(v - consensus) / consensus * 100 for v in values) if consensus else 0
        is_reliable = max_dev <= self.DEVIATION_THRESHOLD

        return DataValidationResult(
            stock_code=stock_code, field=field,
            sources=sources, consensus=round(consensus, 2),
            max_deviation_pct=round(max_dev, 3),
            is_reliable=is_reliable,
            warning="" if is_reliable else f"数据偏差{max_dev:.1f}%，需人工确认",
        )


# ============================================================
# Layer 2: Signal Validation (Golden Dataset)
# ============================================================

@dataclass
class SignalGoldenCase:
    """信号 Golden Dataset 条目 — 已知正确结果"""
    name: str                   # "macd_golden_cross"
    stock_code: str
    kline_data: list[dict]      # 输入K线
    expected_signal: str        # "buy" / "sell" / "neutral"
    expected_score_min: float   # 预期最低分
    expected_score_max: float   # 预期最高分
    tolerance: float = 5.0      # 容差


@dataclass
class SignalValidationResult:
    """信号校验结果"""
    case_name: str
    passed: bool
    expected_score_range: tuple[float, float]
    actual_score: float
    deviation: float = 0.0
    message: str = ""


class SignalValidator:
    """信号校验器 — Golden Dataset 验证"""

    def __init__(self):
        self._golden_cases: list[SignalGoldenCase] = []

    def add_golden_case(self, case: SignalGoldenCase) -> None:
        self._golden_cases.append(case)

    async def validate(self, signal_compute_fn) -> list[SignalValidationResult]:
        """用 Golden Dataset 校验信号计算"""
        results = []
        for case in self._golden_cases:
            result = await signal_compute_fn(case.stock_code, case.kline_data)
            score = result.score if hasattr(result, 'score') else result.get('score', 0)
            direction = result.direction.value if hasattr(result.direction, 'value') else result.get('direction', '')

            actual_score = float(score)
            in_range = case.expected_score_min - case.tolerance <= actual_score <= case.expected_score_max + case.tolerance
            expected_dir = case.expected_signal
            dir_match = direction == expected_dir

            deviation = abs(actual_score - (case.expected_score_min + case.expected_score_max) / 2)

            results.append(SignalValidationResult(
                case_name=case.name,
                passed=in_range and dir_match,
                expected_score_range=(case.expected_score_min, case.expected_score_max),
                actual_score=actual_score,
                deviation=round(deviation, 2),
                message="通过" if (in_range and dir_match) else
                        f"预期{case.expected_score_min}-{case.expected_score_max}分/方向{expected_dir}，实际{actual_score:.0f}分/{direction}",
            ))
        return results

    def golden_case_count(self) -> int:
        return len(self._golden_cases)


# ============================================================
# Layer 3: Research Validation (Prediction Tracking)
# ============================================================

@dataclass
class ResearchPrediction:
    """研究预测记录"""
    prediction_id: str
    stock_code: str
    stock_name: str
    predicted_score: float
    predicted_direction: str    # buy/sell/neutral
    predicted_at: str            # ISO date
    price_at_prediction: float

    # 后续实际表现（逐步回填）
    price_7d: float = 0.0
    price_30d: float = 0.0
    price_90d: float = 0.0
    return_7d_pct: float = 0.0
    return_30d_pct: float = 0.0
    return_90d_pct: float = 0.0

    direction_correct: bool = False
    score_grade: str = ""       # "accurate"/"close"/"wrong"

    def update_outcome(self, price_7d: float, price_30d: float = 0, price_90d: float = 0):
        self.price_7d = price_7d
        self.price_30d = price_30d
        self.price_90d = price_90d
        if self.price_at_prediction > 0:
            self.return_7d_pct = round((price_7d / self.price_at_prediction - 1) * 100, 2)
            self.return_30d_pct = round((price_30d / self.price_at_prediction - 1) * 100, 2) if price_30d else 0
            self.return_90d_pct = round((price_90d / self.price_at_prediction - 1) * 100, 2) if price_90d else 0

        # 方向判断
        actual = "buy" if self.return_30d_pct > 0 else "sell"
        self.direction_correct = (self.predicted_direction == actual)

        # 评分准确性
        if abs(self.predicted_score - 50) < 5:
            self.score_grade = "neutral"
        elif self.direction_correct:
            self.score_grade = "accurate"
        elif abs(self.return_30d_pct) < 2:
            self.score_grade = "close"
        else:
            self.score_grade = "wrong"


# ============================================================
# Layer 4: Accuracy Report
# ============================================================

@dataclass
class AccuracyReport:
    """准确率统计报告"""
    report_date: str = ""
    total_predictions: int = 0

    # 整体
    direction_accuracy_pct: float = 0.0
    avg_return_7d_pct: float = 0.0
    avg_return_30d_pct: float = 0.0

    # 按评分分档
    high_score_accuracy: float = 0.0     # Score >= 80
    mid_score_accuracy: float = 0.0      # 60 <= Score < 80
    low_score_accuracy: float = 0.0      # Score < 60

    high_score_avg_return: float = 0.0
    mid_score_avg_return: float = 0.0
    low_score_avg_return: float = 0.0

    # 建议
    suggestions: list[str] = field(default_factory=list)


class AccuracyCalculator:
    """准确率统计器"""

    def calculate(self, predictions: list[ResearchPrediction]) -> AccuracyReport:
        if not predictions:
            return AccuracyReport()

        total = len(predictions)
        correct = sum(1 for p in predictions if p.direction_correct)
        avg_7d = sum(p.return_7d_pct for p in predictions) / total
        avg_30d = sum(p.return_30d_pct for p in predictions) / total

        # 按评分分档
        high = [p for p in predictions if p.predicted_score >= 80]
        mid = [p for p in predictions if 60 <= p.predicted_score < 80]
        low = [p for p in predictions if p.predicted_score < 60]

        suggestions = []
        if high:
            high_acc = sum(1 for p in high if p.direction_correct) / len(high) * 100
            high_ret = sum(p.return_30d_pct for p in high) / len(high)
            if high_acc < 60:
                suggestions.append(f"高评分(>=80)准确率仅{high_acc:.0f}%，建议检查信号权重")
        if low:
            low_acc = sum(1 for p in low if p.direction_correct) / len(low) * 100
            if low_acc > 70:
                suggestions.append(f"低评分(<60)标的反而准确率{low_acc:.0f}%，评分阈值可能需调整")

        return AccuracyReport(
            report_date=date.today().isoformat(),
            total_predictions=total,
            direction_accuracy_pct=round(correct / total * 100, 1),
            avg_return_7d_pct=round(avg_7d, 2),
            avg_return_30d_pct=round(avg_30d, 2),
            high_score_accuracy=round(sum(1 for p in high if p.direction_correct) / len(high) * 100, 1) if high else 0,
            mid_score_accuracy=round(sum(1 for p in mid if p.direction_correct) / len(mid) * 100, 1) if mid else 0,
            low_score_accuracy=round(sum(1 for p in low if p.direction_correct) / len(low) * 100, 1) if low else 0,
            high_score_avg_return=round(sum(p.return_30d_pct for p in high) / len(high), 2) if high else 0,
            mid_score_avg_return=round(sum(p.return_30d_pct for p in mid) / len(mid), 2) if mid else 0,
            low_score_avg_return=round(sum(p.return_30d_pct for p in low) / len(low), 2) if low else 0,
            suggestions=suggestions,
        )
