"""Signal Fusion — 多信号加权融合引擎

所有信号独立计算 → Fusion 按权重融合 → 输出最终评分 + 方向 + 置信度
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.signals.base import BaseSignal, SignalResult, SignalDirection


@dataclass
class FusionResult:
    """融合结果"""

    stock_code: str
    final_score: float                                    # 0-100
    direction: SignalDirection
    confidence: float                                     # 0.0-1.0
    individual_scores: dict[str, float] = field(default_factory=dict)
    individual_directions: dict[str, str] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    buy_signals: int = 0
    sell_signals: int = 0
    neutral_signals: int = 0


class SignalFusion:
    """信号融合引擎 — 可配置权重"""

    def __init__(self, signals: list[BaseSignal] | None = None):
        self._signals: dict[str, BaseSignal] = {}
        if signals:
            for s in signals:
                self.add_signal(s)

    def add_signal(self, signal: BaseSignal) -> None:
        self._signals[signal.name] = signal

    def remove_signal(self, name: str) -> None:
        self._signals.pop(name, None)

    @property
    def signal_names(self) -> list[str]:
        return list(self._signals.keys())

    async def score(
        self,
        stock_code: str,
        data: list[dict],
        weights: dict[str, float] | None = None,
    ) -> FusionResult:
        """计算融合评分"""
        if not self._signals:
            return FusionResult(stock_code=stock_code, final_score=50.0,
                                direction=SignalDirection.NEUTRAL, confidence=0.0)

        results: list[SignalResult] = []
        for sig in self._signals.values():
            result = await sig.compute(stock_code, data)
            results.append(result)

        return self._fuse(stock_code, results, weights)

    def _fuse(
        self,
        stock_code: str,
        results: list[SignalResult],
        weights: dict[str, float] | None = None,
    ) -> FusionResult:
        """加权融合"""
        individual_scores: dict[str, float] = {}
        individual_directions: dict[str, str] = {}
        reasons: list[str] = []
        buy = sell = neutral = 0

        total_weight = 0.0
        weighted_sum = 0.0

        for r in results:
            w = (weights or {}).get(r.signal_name, self._signals[r.signal_name].default_weight)
            individual_scores[r.signal_name] = r.score
            individual_directions[r.signal_name] = r.direction.value

            weighted_sum += r.score * w
            total_weight += w

            if r.reason:
                reasons.append(f"[{r.signal_name}] {r.reason}")

            if r.direction == SignalDirection.BUY:
                buy += 1
            elif r.direction == SignalDirection.SELL:
                sell += 1
            else:
                neutral += 1

        final_score = weighted_sum / total_weight if total_weight > 0 else 50.0

        # 方向
        if buy > sell and buy >= len(results) * 0.4:
            direction = SignalDirection.BUY
        elif sell > buy and sell >= len(results) * 0.4:
            direction = SignalDirection.SELL
        else:
            direction = SignalDirection.NEUTRAL

        # 置信度：基于信号一致性和得分偏离中性的程度
        agreement = max(buy, sell, neutral) / len(results) if results else 0
        score_deviation = abs(final_score - 50) / 50
        confidence = round(agreement * 0.6 + score_deviation * 0.4, 3)

        return FusionResult(
            stock_code=stock_code,
            final_score=round(final_score, 2),
            direction=direction,
            confidence=confidence,
            individual_scores=individual_scores,
            individual_directions=individual_directions,
            reasons=reasons,
            buy_signals=buy,
            sell_signals=sell,
            neutral_signals=neutral,
        )
