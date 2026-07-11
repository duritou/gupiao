"""Pre-mortem Analysis — v11.0. "If I'm wrong, WHY am I most likely wrong?"

Before executing any BUY/SELL decision, this engine identifies the most
likely failure modes with estimated probabilities, specific trigger conditions,
and early warning signals.

This is the opposite of a post-mortem. A post-mortem explains what went wrong
after the fact. A pre-mortem imagines the decision has already failed and asks:
"What caused it?"

Five failure mode categories:
  1. Earnings Miss — fundamental deterioration
  2. Sector Rotation — macro-driven capital reallocation
  3. Technical False Signal — indicator whipsaw
  4. Capital Flow Reversal — hot money exits
  5. Systemic Market Risk — broad market collapse

Each failure mode comes with:
  - Estimated probability (driven by current conditions)
  - Specific trigger conditions (what to watch for)
  - Early warning signals (what appears BEFORE the failure)
  - Impact estimate (how bad it could be)
  - Mitigation suggestion (what to do to limit damage)

This transforms "risk: 趋势偏弱" into actionable intelligence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ================================================================
# Data Models
# ================================================================

@dataclass
class FailureMode:
    """A specific way this decision could go wrong."""
    failure_name: str = ""           # "财报低于预期"
    failure_id: str = ""             # "earnings_miss"
    category: str = ""               # fundamental / technical / macro / flow / systemic
    probability_pct: float = 0.0     # Estimated likelihood (0-100)
    severity: str = ""               # HIGH / MEDIUM / LOW

    # What to watch for
    trigger_conditions: list[str] = field(default_factory=list)
    # e.g. "Q2营收增速<10%", "毛利率连续两季下滑"

    early_warning_signals: list[str] = field(default_factory=list)
    # e.g. "至少2家券商下调评级", "同行业龙头财报miss"

    # Impact
    impact_estimate: str = ""        # "可能导致-15%~-25%的短期亏损"

    # What drives this probability
    driving_factors: list[str] = field(default_factory=list)
    # e.g. "当前PE处于历史90%分位", "证据等级仅C级"

    # Mitigation
    mitigation: str = ""             # "设置-8%止损线"

    def to_dict(self) -> dict:
        return {
            "failure_name": self.failure_name,
            "failure_id": self.failure_id,
            "category": self.category,
            "probability_pct": round(self.probability_pct, 1),
            "severity": self.severity,
            "trigger_conditions": self.trigger_conditions,
            "early_warning_signals": self.early_warning_signals,
            "impact_estimate": self.impact_estimate,
            "driving_factors": self.driving_factors,
            "mitigation": self.mitigation,
        }


@dataclass
class PreMortemReport:
    """Complete pre-mortem analysis of a decision."""
    stock_code: str = ""
    stock_name: str = ""
    generated_at: str = ""
    direction: str = ""              # The recommendation being analyzed

    # Failure modes sorted by probability (highest first)
    failure_modes: list[FailureMode] = field(default_factory=list)

    # Overall risk assessment
    total_risk_score: float = 0.0    # 0-100, higher = riskier
    overall_risk_level: str = ""     # LOW / MODERATE / ELEVATED / HIGH
    resilience_score: float = 0.0    # 0-100, higher = more resilient

    # Key insight
    top_risk: str = ""               # Name of highest-probability failure
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "generated_at": self.generated_at[:19] if self.generated_at else "",
            "direction": self.direction,
            "failure_modes": [f.to_dict() for f in self.failure_modes],
            "total_risk_score": round(self.total_risk_score, 1),
            "overall_risk_level": self.overall_risk_level,
            "resilience_score": round(self.resilience_score, 1),
            "top_risk": self.top_risk,
            "summary": self.summary,
        }


# ================================================================
# Pre-mortem Engine
# ================================================================

class PreMortemAnalyzer:
    """Identifies most likely failure modes before executing a decision.

    Rule-based analysis driven by signal, sector, and committee context.
    Each failure mode's probability is computed from the conditions that
    make that particular failure more likely — not a generic risk score.
    """

    def analyze(
        self,
        stock_code: str,
        stock_name: str,
        committee_decision: Any = None,     # CommitteeDecision
        ai_score: float = 70.0,
        direction: str = "buy",
        signals: dict[str, float] | None = None,
        macro_context: dict[str, float] | None = None,
        evidence_grade: str = "B",
    ) -> PreMortemReport:
        """Run pre-mortem analysis on a prospective decision.

        Args:
            stock_code: Stock being evaluated
            stock_name: Human-readable name
            committee_decision: Optional CommitteeDecision for richer analysis
            ai_score: AI fusion score (0-100)
            direction: buy / sell / hold
            signals: Signal scores dict {"MACD": 72, "RSI": 65, ...}
            macro_context: Macro context {"PMI": 65, "sector_momentum": 70, ...}
            evidence_grade: A / B / C / D

        Returns:
            PreMortemReport with top 5 failure modes
        """
        signals = signals or {"MACD": 72, "RSI": 65, "MA": 70, "Volume": 68, "KDJ": 60}
        macro_context = macro_context or {"PMI": 65, "sector_momentum": 70, "policy_support": 75}

        # Extract richer data from committee decision if available
        if committee_decision:
            direction = getattr(committee_decision, 'composite_direction', direction)
            ai_score = getattr(committee_decision, 'composite_score', ai_score)
            # Extract per-analyst scores if available
            reports = getattr(committee_decision, 'reports', [])
            tech_report = next((r for r in reports if getattr(r, 'role', '') == '技术分析师'), None)
            fund_report = next((r for r in reports if getattr(r, 'role', '') == '基本面分析师'), None)
            macro_report = next((r for r in reports if getattr(r, 'role', '') == '宏观分析师'), None)
            if tech_report:
                tech_score = getattr(tech_report, 'score', 50)
            else:
                tech_score = signals.get("MACD", 50)
            if fund_report:
                fund_score = getattr(fund_report, 'score', 50)
            else:
                fund_score = 50
            if macro_report:
                macro_score = getattr(macro_report, 'score', 50)
            else:
                macro_score = macro_context.get("sector_momentum", 50)
        else:
            tech_score = signals.get("MACD", 50)
            fund_score = 50
            macro_score = macro_context.get("sector_momentum", 50)

        failure_modes: list[FailureMode] = []

        # 1. Earnings Miss (fundamental)
        failure_modes.append(self._earnings_miss_risk(
            stock_name, ai_score, fund_score, evidence_grade, direction
        ))

        # 2. Sector Rotation (macro)
        failure_modes.append(self._sector_rotation_risk(
            stock_name, macro_score, macro_context, direction
        ))

        # 3. Technical False Signal (technical)
        failure_modes.append(self._technical_false_signal_risk(
            tech_score, signals, direction
        ))

        # 4. Capital Flow Reversal (flow)
        failure_modes.append(self._capital_flow_reversal_risk(
            signals, direction
        ))

        # 5. Systemic Market Risk (systemic)
        failure_modes.append(self._systemic_market_risk(
            macro_context, ai_score, direction
        ))

        # Sort by probability descending
        failure_modes.sort(key=lambda f: -f.probability_pct)

        # Overall metrics
        total_risk = sum(f.probability_pct for f in failure_modes) / len(failure_modes)
        resilience = max(0, 100 - total_risk)

        if total_risk < 10:
            risk_level = "LOW"
        elif total_risk < 20:
            risk_level = "MODERATE"
        elif total_risk < 35:
            risk_level = "ELEVATED"
        else:
            risk_level = "HIGH"

        top_risk = failure_modes[0].failure_name if failure_modes else ""

        # Generate summary
        summary = self._generate_summary(
            failure_modes, risk_level, direction, stock_name
        )

        return PreMortemReport(
            stock_code=stock_code,
            stock_name=stock_name,
            generated_at=datetime.now().isoformat(),
            direction=direction,
            failure_modes=failure_modes,
            total_risk_score=total_risk,
            overall_risk_level=risk_level,
            resilience_score=resilience,
            top_risk=top_risk,
            summary=summary,
        )

    # ================================================================
    # Failure Mode 1: Earnings Miss
    # ================================================================

    def _earnings_miss_risk(
        self, stock_name: str, ai_score: float,
        fund_score: float, evidence_grade: str, direction: str,
    ) -> FailureMode:
        """Earnings miss: fundamental analyst score is low or evidence is weak."""
        from src.explain.evidence_quality import _guess_sector
        sector = _guess_sector(stock_name)

        # Base probability: inverse of fundamental score
        base_prob = max(5, 40 - fund_score * 0.35)

        # Adjustments
        triggers: list[str] = []
        warnings: list[str] = []
        drivers: list[str] = []

        if evidence_grade in ("C", "D"):
            base_prob += 10
            drivers.append(f"证据等级仅{evidence_grade}级，财务数据可能不准确")

        if fund_score < 50:
            base_prob += 8
            drivers.append(f"基本面评分仅{fund_score:.0f}，分析师对盈利质量存疑")

        if sector in ("半导体", "科技"):
            base_prob += 3
            drivers.append(f"{sector}行业业绩波动性较高")

        # Trigger conditions
        triggers.append("季报营收增速低于分析师一致预期5%以上")
        triggers.append("毛利率连续两个季度下滑")
        if sector in ("半导体", "科技"):
            triggers.append("大客户订单取消或推迟")

        # Early warnings
        warnings.append("至少2家券商在财报前下调评级或目标价")
        warnings.append("同行业可比公司已发布业绩预警")
        warnings.append("公司高管近期减持")

        # Severity and impact
        if fund_score < 40:
            severity = "HIGH"
            impact = "可能导致-20%~-35%的剧烈下跌，尤其如果市场此前预期较高"
        elif fund_score < 60:
            severity = "MEDIUM"
            impact = "可能导致-10%~-20%的调整"
        else:
            severity = "LOW"
            impact = "可能导致-5%~-10%的温和下跌"

        prob = min(45, max(5, base_prob))

        return FailureMode(
            failure_name="财报低于预期",
            failure_id="earnings_miss",
            category="fundamental",
            probability_pct=prob,
            severity=severity,
            trigger_conditions=triggers,
            early_warning_signals=warnings,
            impact_estimate=impact,
            driving_factors=drivers,
            mitigation="财报发布前减仓至正常水平的50%。关注业绩预告，如有预警立即退出。",
        )

    # ================================================================
    # Failure Mode 2: Sector Rotation
    # ================================================================

    def _sector_rotation_risk(
        self, stock_name: str, macro_score: float,
        macro_context: dict, direction: str,
    ) -> FailureMode:
        """Sector rotation: macro conditions shift capital away from this sector."""
        from src.explain.evidence_quality import _guess_sector
        sector = _guess_sector(stock_name)
        sector_momentum = macro_context.get("sector_momentum", 50)

        # Base probability: hot sectors have higher rotation risk
        if sector_momentum > 80:
            base_prob = 25  # Very hot → rotation likely
        elif sector_momentum > 65:
            base_prob = 18
        elif sector_momentum > 50:
            base_prob = 12
        else:
            base_prob = 8   # Already cold → less rotation risk

        triggers: list[str] = []
        warnings: list[str] = []
        drivers: list[str] = []

        if sector_momentum > 75:
            drivers.append(f"{sector}行业热度{sector_momentum:.0f}分，处于高位，资金可能轮动至其他板块")

        if macro_score < 50:
            base_prob += 5
            drivers.append(f"宏观评分仅{macro_score:.0f}，政策或资金环境不利")

        # Trigger conditions
        triggers.append(f"{sector}板块指数跌破20日均线")
        triggers.append("两市成交额连续3日低于8000亿（资金退潮）")
        triggers.append(f"出现新的强势板块分流{sector}资金")

        # Early warnings
        warnings.append(f"{sector}板块中龙头股率先走弱")
        warnings.append("北向资金连续3日净流出该板块")
        warnings.append("板块内涨停家数明显减少")

        severity = "MEDIUM" if sector_momentum > 70 else "LOW"
        impact = (
            f"可能导致-10%~-20%的板块性回调"
            if severity == "MEDIUM" else
            "可能导致-5%~-10%的温和调整"
        )

        prob = min(40, max(5, base_prob))

        return FailureMode(
            failure_name=f"{sector}行业轮动",
            failure_id="sector_rotation",
            category="macro",
            probability_pct=prob,
            severity=severity,
            trigger_conditions=triggers,
            early_warning_signals=warnings,
            impact_estimate=impact,
            driving_factors=drivers,
            mitigation=f"配置不超过{sector}板块总仓位的30%。设置板块指数的跟踪止损。",
        )

    # ================================================================
    # Failure Mode 3: Technical False Signal
    # ================================================================

    def _technical_false_signal_risk(
        self, tech_score: float, signals: dict, direction: str,
    ) -> FailureMode:
        """Technical false signal: indicator whipsaw or fake breakout."""
        rsi = signals.get("RSI", 50)
        macd = signals.get("MACD", 50)
        volume = signals.get("Volume", 50)
        ma = signals.get("MA", 50)

        # Base probability from RSI extremes
        if rsi > 80:
            base_prob = 28  # Heavily overbought → pullback likely
        elif rsi > 70:
            base_prob = 20
        elif rsi < 30:
            base_prob = 22  # Oversold bounce can fake out shorts
        elif rsi < 20:
            base_prob = 25
        else:
            base_prob = 10

        triggers: list[str] = []
        warnings: list[str] = []
        drivers: list[str] = []

        # RSI
        if rsi > 75:
            drivers.append(f"RSI={rsi:.0f}处于超买区域，技术性回调风险升高")
        elif rsi < 30:
            drivers.append(f"RSI={rsi:.0f}处于超卖区域，可能是下跌中继而非底部")

        # Volume confirmation
        if volume < 50:
            base_prob += 8
            drivers.append(f"成交量评分{volume:.0f}，突破缺乏量能确认，假突破概率增大")

        # MACD reliability
        if 45 <= macd <= 55:
            base_prob += 5
            drivers.append("MACD处于临界区域，金叉/死叉信号可能为噪音")

        # MA confirmation
        if ma < 45:
            base_prob += 5
            drivers.append("均线未形成多头排列，趋势不够确认")

        # Trigger conditions
        if direction == "buy":
            triggers.append("股价跌破突破当日的K线低点（假突破确认）")
            triggers.append("MACD红柱连续3日缩短")
        else:
            triggers.append("股价重新站上5日均线")
            triggers.append("MACD绿柱开始缩短")

        # Early warnings
        warnings.append("技术指标出现顶背离或底背离")
        warnings.append("关键阻力位/支撑位反复测试不破")
        warnings.append("连续缩量（量能持续萎缩）")

        prob = min(40, max(5, base_prob))

        if rsi > 80 or rsi < 20:
            severity = "HIGH"
            impact = "假突破可能导致-10%~-20%的反向波动"
        elif rsi > 70 or rsi < 30:
            severity = "MEDIUM"
            impact = "假信号可能导致-5%~-15%的短期亏损"
        else:
            severity = "LOW"
            impact = "可能导致-3%~-8%的小幅亏损"

        return FailureMode(
            failure_name="技术指标假信号",
            failure_id="technical_false_signal",
            category="technical",
            probability_pct=prob,
            severity=severity,
            trigger_conditions=triggers,
            early_warning_signals=warnings,
            impact_estimate=impact,
            driving_factors=drivers,
            mitigation="等待放量确认后再入场。设置技术止损（跌破关键支撑即退出，不抱幻想）。",
        )

    # ================================================================
    # Failure Mode 4: Capital Flow Reversal
    # ================================================================

    def _capital_flow_reversal_risk(
        self, signals: dict, direction: str,
    ) -> FailureMode:
        """Capital flow reversal: hot money exits, northbound turns negative."""
        volume = signals.get("Volume", 50)

        # High volume = high participation = higher reversal risk when it turns
        if volume > 75:
            base_prob = 22
        elif volume > 60:
            base_prob = 15
        else:
            base_prob = 8

        triggers: list[str] = []
        warnings: list[str] = []
        drivers: list[str] = []

        if volume > 70:
            drivers.append(f"成交量评分{volume:.0f}，高活跃度意味着资金高度参与，一旦转向杀伤力大")

        if direction == "buy" and volume > 70:
            drivers.append("高成交量买入可能是短期资金跟风，而非中长期资金布局")

        # Trigger conditions
        triggers.append("北向资金单日净流出超过50亿")
        triggers.append("融资余额连续3日下降")
        triggers.append("主力资金连续2日净流出")

        # Early warnings
        warnings.append("北向资金流入速度明显放缓")
        warnings.append("龙虎榜显示游资/机构净卖出")
        warnings.append("大单资金流向由正转负")

        prob = min(30, max(5, base_prob))

        severity = "MEDIUM" if volume > 70 else "LOW"
        impact = (
            "资金转向可能导致-10%~-20%的快速下跌，尤其在高成交量环境下"
            if severity == "MEDIUM" else
            "可能导致-5%~-10%的回调"
        )

        return FailureMode(
            failure_name="资金流向逆转",
            failure_id="capital_flow_reversal",
            category="flow",
            probability_pct=prob,
            severity=severity,
            trigger_conditions=triggers,
            early_warning_signals=warnings,
            impact_estimate=impact,
            driving_factors=drivers,
            mitigation="每日监控北向资金和主力资金流向。一旦发现连续流出信号，立即减仓。",
        )

    # ================================================================
    # Failure Mode 5: Systemic Market Risk
    # ================================================================

    def _systemic_market_risk(
        self, macro_context: dict, ai_score: float, direction: str,
    ) -> FailureMode:
        """Systemic market risk: broad market collapse (black swan)."""
        pmi = macro_context.get("PMI", 50)

        # Base: always some systemic risk
        base_prob = 8

        triggers: list[str] = []
        warnings: list[str] = []
        drivers: list[str] = []

        if pmi < 50:
            base_prob += 8
            drivers.append(f"PMI={pmi:.0f}，低于荣枯线，宏观经济承压增加系统性风险")

        if ai_score > 85 and direction == "buy":
            base_prob += 2
            drivers.append("高评分可能导致忽视宏观尾部风险")

        # Trigger conditions (these are rare but catastrophic)
        triggers.append("上证指数单日跌幅超过5%")
        triggers.append("出现重大地缘政治事件或金融危机")
        triggers.append("央行意外大幅加息或收紧流动性")
        triggers.append("全球主要股指同步暴跌")

        # Early warnings
        warnings.append("VIX/恐慌指数异常升高")
        warnings.append("信用利差快速扩大")
        warnings.append("避险资产（黄金/国债）与风险资产同跌（流动性危机）")

        prob = min(20, max(3, base_prob))

        # Systemic risk is always high severity (low probability, high impact)
        severity = "HIGH"
        impact = "极端情况下可能导致-30%~-50%的系统性暴跌。虽然概率低，但后果严重。"

        return FailureMode(
            failure_name="大盘系统性风险",
            failure_id="systemic_market_risk",
            category="systemic",
            probability_pct=prob,
            severity=severity,
            trigger_conditions=triggers,
            early_warning_signals=warnings,
            impact_estimate=impact,
            driving_factors=drivers,
            mitigation="始终保持一定现金比例（≥20%）。系统性风险无法通过选股规避，只能通过仓位管理和止损纪律控制。",
        )

    # ================================================================
    # Summary
    # ================================================================

    def _generate_summary(
        self, failure_modes: list[FailureMode],
        risk_level: str, direction: str, stock_name: str,
    ) -> str:
        """Generate an actionable summary of the pre-mortem analysis."""
        if not failure_modes:
            return "无法完成预分析。数据不足。"

        top3 = failure_modes[:3]
        direction_cn = {"buy": "做多", "sell": "做空", "hold": "持有"}.get(direction, "操作")

        risk_labels = {
            "LOW": "风险较低",
            "MODERATE": "风险适中",
            "ELEVATED": "风险偏高",
            "HIGH": "高风险",
        }

        # Describe top risks
        top_descriptions = []
        for fm in top3:
            top_descriptions.append(
                f"{fm.failure_name}（{fm.probability_pct:.0f}%概率，{fm.severity}严重度）"
            )

        summary = (
            f"对{stock_name}的{direction_cn}决策进行预分析："
            f"整体风险等级为{risk_labels.get(risk_level, risk_level)}。"
            f"最大的三个失败风险是：{'；'.join(top_descriptions)}。"
        )

        # Add most important watch-point
        if failure_modes[0].trigger_conditions:
            top_trigger = failure_modes[0].trigger_conditions[0]
            summary += f"最重要的观察点是：{top_trigger}"

        return summary


# Singleton
premortem_engine = PreMortemAnalyzer()
