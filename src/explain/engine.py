"""Explain Engine v1.0 — Score Breakdown + Structured Explanation.

Architecture:
  Evidence items → ScoreBreakdown (component-level contribution tree)
  ScoreBreakdown → ExplainEngine (programmatic, template-based explanation)

AI only fills template fields. Reasoning is deterministic from data.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ============================================================
# Score Component — one contributor to the final score
# ============================================================

@dataclass
class ScoreComponent:
    """A single contributor to the AI Score."""
    name: str               # "MACD" / "MA多头排列" / "半导体周期"
    category: str           # "signal" / "knowledge" / "market" / "risk" / "backtest"
    score: float            # contribution value (-100 to +100)
    weight: float = 1.0     # relative weight
    icon: str = "check"     # "check" / "warning" / "star" / "info"
    description: str = ""   # human-readable
    detail: str = ""        # technical detail
    raw_value: float = 0.0  # original indicator value before normalization


# ============================================================
# Score Breakdown — complete component tree
# ============================================================

@dataclass
class ScoreBreakdown:
    """Full breakdown of how the AI Score was calculated."""
    stock_code: str
    stock_name: str
    final_score: float
    confidence: float
    direction: str           # "buy" / "sell" / "neutral"
    recommendation: str      # "强烈关注" / "关注" / "观望" / "减仓" / "回避"
    components: list[ScoreComponent] = field(default_factory=list)

    @property
    def by_category(self) -> dict[str, list[ScoreComponent]]:
        result: dict[str, list[ScoreComponent]] = {}
        for c in self.components:
            result.setdefault(c.category, []).append(c)
        return result

    @property
    def category_totals(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for c in self.components:
            totals[c.category] = totals.get(c.category, 0) + c.score * c.weight
        return totals

    @property
    def positive(self) -> list[ScoreComponent]:
        return [c for c in self.components if c.score > 0]

    @property
    def negative(self) -> list[ScoreComponent]:
        return [c for c in self.components if c.score < 0]

    @property
    def star_rating(self) -> int:
        if self.final_score >= 80:
            return 5
        elif self.final_score >= 65:
            return 4
        elif self.final_score >= 50:
            return 3
        elif self.final_score >= 35:
            return 2
        return 1

    def to_dict(self) -> dict:
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "final_score": round(self.final_score, 1),
            "confidence": round(self.confidence, 3),
            "direction": self.direction,
            "recommendation": self.recommendation,
            "stars": self.star_rating,
            "category_totals": {k: round(v, 1) for k, v in self.category_totals.items()},
            "components": [
                {
                    "name": c.name,
                    "category": c.category,
                    "score": round(c.score, 1),
                    "weight": round(c.weight, 2),
                    "icon": c.icon,
                    "description": c.description,
                    "detail": c.detail,
                    "raw_value": round(c.raw_value, 3),
                }
                for c in self.components
            ],
            "positive_count": len(self.positive),
            "negative_count": len(self.negative),
        }


# ============================================================
# Breakdown Builder — computes ScoreBreakdown from signals
# ============================================================

CATEGORY_LABELS: dict[str, str] = {
    "signal": "技术信号",
    "knowledge": "行业知识",
    "market": "市场环境",
    "risk": "风险评估",
    "backtest": "回测验证",
}

CATEGORY_ICONS: dict[str, str] = {
    "signal": "check",
    "knowledge": "star",
    "market": "info",
    "risk": "warning",
    "backtest": "check",
}


class BreakdownBuilder:
    """Builds ScoreBreakdown from signal results, knowledge, and market data."""

    def build(
        self,
        stock_code: str,
        stock_name: str,
        scores: dict[str, float],
        direction: str = "neutral",
        confidence: float = 0.5,
        reasons: list[str] | None = None,
        knowledge_score: float = 50.0,
        market_score: float = 50.0,
    ) -> ScoreBreakdown:
        """Build a complete ScoreBreakdown from raw inputs."""
        components: list[ScoreComponent] = []

        # ---- Signal Components ----
        signal_names = {
            "macd": ("MACD", "MACD指标信号"),
            "rsi": ("RSI", "相对强弱指标"),
            "kdj": ("KDJ", "随机指标"),
            "ma": ("MA均线", "移动平均线趋势"),
            "volume": ("成交量", "成交量分析"),
            "boll": ("BOLL", "布林带信号"),
        }

        signal_weights = {
            "macd": 1.0, "ma": 0.7, "rsi": 0.8,
            "kdj": 0.7, "volume": 0.8, "boll": 0.6,
        }

        for key, (name, desc) in signal_names.items():
            if key in scores:
                raw = scores[key]
                # Convert 0-100 score to contribution (-50 to +50, centered at 50)
                contribution = (raw - 50) * signal_weights.get(key, 1.0)
                icon = "check" if raw >= 60 else "warning" if raw <= 40 else "info"
                detail = self._describe_signal(key, raw)
                components.append(ScoreComponent(
                    name=name, category="signal",
                    score=round(contribution, 1),
                    weight=signal_weights.get(key, 1.0),
                    icon=icon, description=desc,
                    detail=detail, raw_value=raw,
                ))

        # ---- Knowledge Component ----
        if knowledge_score != 50.0:
            k_contribution = (knowledge_score - 50) * 0.9
            components.append(ScoreComponent(
                name="行业景气度", category="knowledge",
                score=round(k_contribution, 1), weight=0.9,
                icon="star",
                description="知识库行业分析",
                detail=f"行业综合评分 {knowledge_score:.0f}/100",
                raw_value=knowledge_score,
            ))

        # ---- Market Components ----
        if market_score != 50.0:
            m_contribution = (market_score - 50) * 0.7
            components.append(ScoreComponent(
                name="市场环境", category="market",
                score=round(m_contribution, 1), weight=0.7,
                icon="info",
                description="资金流向、北向资金、成交额",
                detail=f"市场综合评分 {market_score:.0f}/100",
                raw_value=market_score,
            ))

        # ---- Risk Components ----
        avg_score = sum(scores.values()) / len(scores) if scores else 50
        if avg_score >= 75:
            risk_contribution = -5.0
            risk_desc = "估值偏高、短期涨幅较大"
        elif avg_score <= 35:
            risk_contribution = -8.0
            risk_desc = "趋势偏弱、下行风险较高"
        else:
            risk_contribution = -2.0
            risk_desc = "正常波动范围"

        components.append(ScoreComponent(
            name="风险扣减", category="risk",
            score=round(risk_contribution, 1), weight=1.0,
            icon="warning", description=risk_desc,
            detail="基于估值分位和波动率",
            raw_value=abs(risk_contribution),
        ))

        # ---- Compute Final Score ----
        # Weighted average of signal scores as the base
        signal_scores = {k: v for k, v in scores.items() if k in signal_weights}
        if signal_scores:
            weighted_sum = sum(v * signal_weights[k] for k, v in signal_scores.items())
            total_w = sum(signal_weights[k] for k in signal_scores)
            base_score = weighted_sum / total_w
        else:
            base_score = 50

        # Apply knowledge and market adjustments (small modifiers)
        final_score = base_score
        final_score += (knowledge_score - 50) * 0.12
        final_score += (market_score - 50) * 0.08

        # Risk penalty
        avg_score = sum(scores.values()) / len(scores) if scores else 50
        if avg_score >= 80:
            final_score -= 2.5
        elif avg_score >= 60:
            final_score -= 1.0
        elif avg_score <= 30:
            final_score -= 5.0
        elif avg_score <= 45:
            final_score -= 3.0

        final_score = max(5, min(98, final_score))

        # Direction
        if direction == "neutral":
            buy_count = sum(1 for c in components if c.score > 5)
            sell_count = sum(1 for c in components if c.score < -5)
            if buy_count >= 3:
                direction = "buy"
            elif sell_count >= 3:
                direction = "sell"

        # Recommendation
        if final_score >= 80:
            recommendation = "强烈关注"
        elif final_score >= 65:
            recommendation = "关注"
        elif final_score >= 50:
            recommendation = "观望"
        elif final_score >= 35:
            recommendation = "减仓"
        else:
            recommendation = "回避"

        return ScoreBreakdown(
            stock_code=stock_code,
            stock_name=stock_name,
            final_score=final_score,
            confidence=round(confidence, 3),
            direction=direction,
            recommendation=recommendation,
            components=components,
        )

    @staticmethod
    def _describe_signal(key: str, value: float) -> str:
        """Generate a human-readable description of a signal value."""
        if key == "macd":
            if value >= 70:
                return "DIF上穿DEA，金叉形成，短期趋势转强"
            elif value >= 55:
                return "DIF在DEA上方，MACD偏多"
            elif value <= 30:
                return "DIF下穿DEA，死叉形成，短期走弱"
            elif value <= 45:
                return "DIF在DEA下方，MACD偏空"
            return "DIF与DEA交织，方向不明"
        elif key == "ma":
            if value >= 70:
                return "MA5>MA20>MA60，均线多头排列"
            elif value >= 55:
                return "价格站上MA20，短期偏多"
            elif value <= 30:
                return "价格跌破MA20和MA60，空头趋势"
            elif value <= 45:
                return "均线走平，方向待确认"
            return "均线交织，横盘整理"
        elif key == "rsi":
            if value >= 75:
                return "RSI超买区间，短期有回调风险"
            elif value >= 60:
                return "RSI偏强，处于健康上升区间"
            elif value <= 25:
                return "RSI超卖区间，关注反弹机会"
            elif value <= 40:
                return "RSI偏弱，动能不足"
            return "RSI中性，无明确方向"
        elif key == "kdj":
            if value >= 70:
                return "K线上穿D线，金叉信号"
            elif value >= 55:
                return "KDJ偏多，J值在安全区间"
            elif value <= 30:
                return "K线下穿D线，死叉信号"
            elif value <= 45:
                return "KDJ偏空，短期承压"
            return "KDJ中性"
        elif key == "volume":
            if value >= 70:
                return "成交量显著放大，资金入场明显"
            elif value >= 55:
                return "成交量温和放大"
            elif value <= 30:
                return "成交量萎缩，交投清淡"
            elif value <= 45:
                return "成交量偏低，观望情绪浓厚"
            return "成交量正常"
        elif key == "boll":
            if value >= 70:
                return "价格突破BOLL上轨，强势特征"
            elif value >= 55:
                return "价格在中轨上方运行"
            elif value <= 30:
                return "价格跌破BOLL下轨，弱势特征"
            elif value <= 45:
                return "价格在中轨下方运行"
            return "价格在中轨附近震荡"
        return f"{key.upper()} = {value:.1f}"


# ============================================================
# Explain Engine — structured explanation from breakdown
# ============================================================

class ExplainEngine:
    """Generates structured, programmatic explanations from ScoreBreakdown.

    Unlike AI chat, this engine produces deterministic, template-based
    explanations. LLM is only used to polish the language, not to reason.
    """

    def explain_breakdown(self, breakdown: ScoreBreakdown) -> dict:
        """Generate a complete structured explanation."""
        return {
            "summary": self._summary(breakdown),
            "strengths": self._strengths(breakdown),
            "weaknesses": self._weaknesses(breakdown),
            "key_evidence": self._key_evidence(breakdown),
            "risk_assessment": self._risk_assessment(breakdown),
            "suggestion": self._suggestion(breakdown),
        }

    def _summary(self, b: ScoreBreakdown) -> str:
        direction_cn = {"buy": "看多", "sell": "看空", "neutral": "中性"}
        dir_str = direction_cn.get(b.direction, "中性")
        pos = b.positive
        neg = b.negative

        parts = [f"{b.stock_name}({b.stock_code})综合评分{b.final_score:.0f}分，方向{dir_str}。"]

        if pos:
            top3 = sorted(pos, key=lambda c: c.score, reverse=True)[:3]
            parts.append(f"主要支撑来自: {'、'.join(c.name for c in top3)}。")

        if neg:
            top_risks = sorted(neg, key=lambda c: c.score)[:2]
            parts.append(f"主要风险: {'、'.join(c.name for c in top_risks)}。")

        return "".join(parts)

    def _strengths(self, b: ScoreBreakdown) -> list[dict]:
        strengths = sorted(b.positive, key=lambda c: c.score, reverse=True)[:5]
        return [
            {
                "name": c.name,
                "contribution": c.score,
                "description": c.detail,
                "category": c.category,
                "icon": c.icon,
            }
            for c in strengths
        ]

    def _weaknesses(self, b: ScoreBreakdown) -> list[dict]:
        weaknesses = sorted(b.negative, key=lambda c: c.score)[:3]
        return [
            {
                "name": c.name,
                "impact": c.score,
                "description": c.detail,
                "category": c.category,
            }
            for c in weaknesses
        ]

    def _key_evidence(self, b: ScoreBreakdown) -> list[dict]:
        evidence = []
        for c in b.components:
            if c.score > 5:
                evidence.append({
                    "icon": "check",
                    "title": f"{c.name}",
                    "detail": c.detail,
                    "credibility": min(0.95, 0.5 + abs(c.score) / 100),
                    "score_impact": f"+{c.score:.0f}",
                    "source": CATEGORY_LABELS.get(c.category, c.category),
                })
            elif c.score < -3:
                evidence.append({
                    "icon": "warning",
                    "title": f"{c.name}",
                    "detail": c.detail,
                    "credibility": min(0.90, 0.5 + abs(c.score) / 100),
                    "score_impact": f"{c.score:.0f}",
                    "source": CATEGORY_LABELS.get(c.category, c.category),
                })
        return sorted(evidence, key=lambda e: float(e["score_impact"]), reverse=True)

    def _risk_assessment(self, b: ScoreBreakdown) -> dict:
        risks = [c for c in b.components if c.category == "risk"]
        total_risk = sum(abs(c.score) for c in risks)
        level = "低" if total_risk < 3 else "中" if total_risk < 6 else "高"

        return {
            "level": level,
            "total_risk_score": round(total_risk, 1),
            "items": [{"name": c.name, "impact": abs(c.score), "description": c.detail} for c in risks],
        }

    def _suggestion(self, b: ScoreBreakdown) -> str:
        if b.final_score >= 80:
            if b.confidence >= 0.8:
                return "多项指标共振，AI信心较高。建议结合自身风险偏好和仓位管理做出决策。"
            return "评分较高但信号一致性一般，建议等待更多确认信号。"
        elif b.final_score >= 65:
            return "评分中等偏上。可小仓位试探，待趋势确认后加仓。"
        elif b.final_score >= 50:
            return "信号偏中性，观望为宜。等待明确方向信号出现。"
        elif b.final_score >= 35:
            return "评分偏低，短期回避。关注企稳信号和基本面变化。"
        return "多个信号提示风险，建议回避或减仓。关注后续变化。"


# ============================================================
# Singleton
# ============================================================

builder = BreakdownBuilder()
explainer = ExplainEngine()
