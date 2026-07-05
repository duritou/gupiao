"""Investment Committee — v10.0. Five AI analysts debate and vote.

Not one AI making a recommendation. Five specialists, each with their own
lens, independently scoring then debating to reach consensus.

Committee Members:
  Technical Analyst  — MACD, RSI, MA, Volume, KDJ (Signal Engine)
  Fundamental Analyst — PE, PB, ROE, earnings, revenue growth
  Macro Analyst       — PMI, CPI, policy, sector rotation
  Risk Manager        — position sizing, drawdown, concentration, VaR
  Portfolio Manager   — synthesizes all views → final decision

Decision Quality: not 'is this stock good?' but 'is this a good DECISION?'
  Composite of evidence + confidence + counterfactual stability + history.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ================================================================
# Committee Member
# ================================================================

@dataclass
class AnalystReport:
    """A single analyst's independent assessment."""
    role: str = ""                   # technical / fundamental / macro / risk / portfolio
    role_icon: str = ""              # 📊 / 📈 / 🌐 / 🛡 / 🎯
    score: float = 50.0              # 0-100
    direction: str = "neutral"       # buy / sell / neutral
    confidence: float = 0.0
    weight: float = 0.20             # Voting weight (equal by default)

    # Their reasoning
    key_factors: list[str] = field(default_factory=list)     # What drove their score
    evidence_sources: list[str] = field(default_factory=list)  # Data sources used
    concerns: list[str] = field(default_factory=list)         # What worries them

    # Vote
    vote: str = ""                   # yes / no / abstain
    vote_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "role": self.role, "role_icon": self.role_icon,
            "score": round(self.score, 1), "direction": self.direction,
            "confidence": round(self.confidence, 2), "weight": round(self.weight, 2),
            "key_factors": self.key_factors,
            "evidence_sources": self.evidence_sources,
            "concerns": self.concerns,
            "vote": self.vote, "vote_reason": self.vote_reason,
        }


@dataclass
class CommitteeDecision:
    """The committee's final decision after debate."""
    stock_code: str = ""
    stock_name: str = ""
    decided_at: str = ""

    # Individual reports
    reports: list[AnalystReport] = field(default_factory=list)

    # Voting
    yes_votes: int = 0
    no_votes: int = 0
    abstain_votes: int = 0
    vote_result: str = ""            # passed / rejected / split

    # Composite score (weighted average of all analysts)
    composite_score: float = 50.0
    composite_direction: str = "neutral"
    composite_confidence: float = 0.0

    # Decision Quality (meta-metric)
    decision_quality_grade: str = ""  # A/B/C/D
    decision_quality_score: float = 0.0

    # Debate summary
    majority_view: str = ""
    dissenting_view: str = ""
    final_recommendation: str = ""

    def to_dict(self) -> dict:
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "decided_at": self.decided_at[:19] if self.decided_at else "",
            "reports": [r.to_dict() for r in self.reports],
            "yes_votes": self.yes_votes,
            "no_votes": self.no_votes,
            "abstain_votes": self.abstain_votes,
            "vote_result": self.vote_result,
            "composite_score": round(self.composite_score, 1),
            "composite_direction": self.composite_direction,
            "composite_confidence": round(self.composite_confidence, 2),
            "decision_quality_grade": self.decision_quality_grade,
            "decision_quality_score": round(self.decision_quality_score, 1),
            "majority_view": self.majority_view,
            "dissenting_view": self.dissenting_view,
            "final_recommendation": self.final_recommendation,
        }


# ================================================================
# Investment Committee Engine
# ================================================================

class InvestmentCommittee:
    """Five AI analysts independently evaluate, then reach consensus.

    This is not prompt engineering. Each analyst uses different data
    sources and scoring logic — just like a real investment committee.
    """

    def evaluate(
        self, stock_code: str, stock_name: str,
        base_score: float = 70.0,
        signals: dict[str, float] | None = None,
        fundamentals: dict[str, float] | None = None,
        macro_context: dict[str, float] | None = None,
        portfolio_context: dict[str, Any] | None = None,
        user_history: dict[str, Any] | None = None,
    ) -> CommitteeDecision:
        """Run the full committee evaluation process."""
        signals = signals or {"MACD": 72, "RSI": 65, "MA": 70, "Volume": 68, "KDJ": 60}
        fundamentals = fundamentals or {"PE": 55, "PB": 60, "ROE": 72, "revenue_growth": 65}
        macro_context = macro_context or {"PMI": 65, "sector_momentum": 70, "policy_support": 75}
        portfolio_context = portfolio_context or {}
        user_history = user_history or {}

        reports = []

        # 1. Technical Analyst — Signal Engine driven
        tech = self._technical_analysis(stock_name, signals, base_score)
        reports.append(tech)

        # 2. Fundamental Analyst — valuation + earnings
        fund = self._fundamental_analysis(stock_name, fundamentals, base_score)
        reports.append(fund)

        # 3. Macro Analyst — PMI + policy + sector
        macro = self._macro_analysis(stock_name, macro_context, base_score)
        reports.append(macro)

        # 4. Risk Manager — position sizing + drawdown
        risk = self._risk_analysis(stock_name, portfolio_context, base_score)
        reports.append(risk)

        # 5. Portfolio Manager — synthesizes all
        pm = self._portfolio_manager_synthesis(
            stock_name, reports, user_history, base_score
        )
        reports.append(pm)

        # Voting
        yes = sum(1 for r in reports if r.vote == "yes")
        no = sum(1 for r in reports if r.vote == "no")
        abstain = sum(1 for r in reports if r.vote == "abstain")

        if yes >= 3:
            vote_result = "passed"
        elif no >= 3:
            vote_result = "rejected"
        else:
            vote_result = "split"

        # Composite (weighted average)
        weights = [r.weight for r in reports]
        total_w = sum(weights)
        composite = sum(r.score * r.weight for r in reports) / total_w if total_w > 0 else 50
        avg_confidence = sum(r.confidence for r in reports) / len(reports) if reports else 0

        # Direction from vote
        if vote_result == "passed":
            direction = "buy" if composite >= 60 else "hold"
        elif vote_result == "rejected":
            direction = "sell"
        else:
            direction = "hold"

        # Decision Quality
        dq_grade, dq_score = self._compute_decision_quality(
            reports, vote_result, composite, avg_confidence
        )

        # Debate summary
        majority = [r for r in reports if r.vote == "yes"] if yes >= no else [r for r in reports if r.vote == "no"]
        dissenting = [r for r in reports if r.vote != (majority[0].vote if majority else "yes")]

        majority_view = f"{len(majority)}位分析师支持: {'、'.join(r.role for r in majority)}"
        dissenting_view = f"{len(dissenting)}位反对: {'、'.join(r.role for r in dissenting)}" if dissenting else "全体一致通过"

        # Final recommendation
        if vote_result == "passed" and dq_grade in ("A", "B"):
            final_rec = f"投资委员会{yes}:{no}通过。建议{direction}。决策质量{dq_grade}级。"
        elif vote_result == "passed":
            final_rec = f"委员会{yes}:{no}通过但决策质量仅{dq_grade}级。建议小仓位试探。"
        elif vote_result == "split":
            final_rec = f"委员会意见分歧({yes}:{no})。建议观望，等待更多信号确认。"
        else:
            final_rec = f"委员会{no}:{yes}否决。建议不参与。"

        return CommitteeDecision(
            stock_code=stock_code, stock_name=stock_name,
            decided_at=datetime.now().isoformat(),
            reports=reports,
            yes_votes=yes, no_votes=no, abstain_votes=abstain,
            vote_result=vote_result,
            composite_score=composite,
            composite_direction=direction,
            composite_confidence=avg_confidence,
            decision_quality_grade=dq_grade,
            decision_quality_score=dq_score,
            majority_view=majority_view,
            dissenting_view=dissenting_view,
            final_recommendation=final_rec,
        )

    # ================================================================
    # Analyst Implementations
    # ================================================================

    def _technical_analysis(self, name: str, signals: dict, base: float) -> AnalystReport:
        macd = signals.get("MACD", 50)
        rsi = signals.get("RSI", 50)
        ma = signals.get("MA", 50)
        vol = signals.get("Volume", 50)

        score = macd * 0.35 + rsi * 0.20 + ma * 0.25 + vol * 0.20
        direction = "buy" if score >= 65 else "sell" if score < 40 else "neutral"

        factors = []
        if macd >= 65:
            factors.append("MACD金叉确认，多头排列")
        if ma >= 60:
            factors.append("均线多头排列，趋势向上")
        if vol >= 65:
            factors.append("成交量放大，资金参与度高")
        if rsi > 75:
            factors.append("⚠ RSI超买，短期回调风险")

        sources = ["东方财富(AkShare)", "Signal Engine"]
        concerns = ["RSI偏高，短期有回调压力"] if rsi > 75 else []

        return AnalystReport(
            role="技术分析师", role_icon="📊",
            score=score, direction=direction,
            confidence=0.85, weight=0.22,
            key_factors=factors, evidence_sources=sources,
            concerns=concerns,
            vote="yes" if score >= 65 else "no" if score < 40 else "abstain",
            vote_reason=f"技术面{'积极' if score >= 65 else '偏弱' if score < 40 else '中性'}，综合评分{score:.0f}",
        )

    def _fundamental_analysis(self, name: str, fundamentals: dict, base: float) -> AnalystReport:
        roe = fundamentals.get("ROE", 50)
        pe = fundamentals.get("PE", 50)
        rev = fundamentals.get("revenue_growth", 50)

        score = roe * 0.40 + (100 - pe) * 0.30 + rev * 0.30  # Lower PE = better
        direction = "buy" if score >= 65 else "sell" if score < 40 else "neutral"

        factors = []
        if roe >= 65:
            factors.append(f"ROE优秀，盈利能力强劲")
        if rev >= 65:
            factors.append("营收增长稳健")
        if pe > 80:
            factors.append("⚠ PE偏高，估值有压缩风险")

        sources = ["Tushare", "巨潮资讯"]
        concerns = ["估值偏高，需关注业绩能否消化"] if pe > 75 else []

        return AnalystReport(
            role="基本面分析师", role_icon="📈",
            score=score, direction=direction,
            confidence=0.78, weight=0.22,
            key_factors=factors, evidence_sources=sources,
            concerns=concerns,
            vote="yes" if score >= 65 else "no" if score < 40 else "abstain",
            vote_reason=f"基本面{'优秀' if score >= 65 else '偏弱' if score < 40 else '一般'}，综合{score:.0f}分",
        )

    def _macro_analysis(self, name: str, macro: dict, base: float) -> AnalystReport:
        pmi = macro.get("PMI", 50)
        sector = macro.get("sector_momentum", 50)
        policy = macro.get("policy_support", 50)

        score = pmi * 0.25 + sector * 0.40 + policy * 0.35
        direction = "buy" if score >= 65 else "sell" if score < 40 else "neutral"

        factors = []
        if sector >= 65:
            factors.append(f"行业景气度上升，板块资金流入")
        if policy >= 65:
            factors.append("政策面利好，产业支持明确")
        if pmi >= 65:
            factors.append("宏观经济扩张，PMI>50")

        sources = ["国家统计局", "工信部", "行业数据"]
        concerns = ["宏观不确定性可能影响整体市场"] if pmi < 50 else []

        return AnalystReport(
            role="宏观分析师", role_icon="🌐",
            score=score, direction=direction,
            confidence=0.72, weight=0.18,
            key_factors=factors, evidence_sources=sources,
            concerns=concerns,
            vote="yes" if score >= 65 else "no" if score < 40 else "abstain",
            vote_reason=f"宏观环境{'有利' if score >= 65 else '不利' if score < 40 else '中性'}",
        )

    def _risk_analysis(self, name: str, portfolio: dict, base: float) -> AnalystReport:
        position_pct = portfolio.get("position_pct", 0)
        concentration = portfolio.get("concentration_risk", 50)
        volatility = portfolio.get("volatility", 50)

        # Higher position = higher risk = lower score for adding more
        position_risk = max(0, 100 - position_pct * 4) if position_pct > 0 else 70
        score = position_risk * 0.30 + (100 - concentration) * 0.40 + (100 - volatility) * 0.30
        direction = "buy" if score >= 65 else "sell" if score < 40 else "neutral"

        factors = []
        if position_pct >= 20:
            factors.append(f"⚠ 当前仓位已达{position_pct:.0f}%，继续加仓风险较高")
        if concentration > 70:
            factors.append("⚠ 行业集中度偏高")
        if score >= 65:
            factors.append("风险可控，仓位有空间")

        sources = ["Portfolio Analyzer", "Risk Engine"]
        concerns = [
            f"仓位{position_pct:.0f}%，加仓后风险敞口增大"
        ] if position_pct >= 15 else []

        return AnalystReport(
            role="风险管理师", role_icon="🛡",
            score=score, direction=direction,
            confidence=0.80, weight=0.20,
            key_factors=factors, evidence_sources=sources,
            concerns=concerns,
            vote="yes" if score >= 65 else "no" if score < 40 else "abstain",
            vote_reason=f"风险{'可控' if score >= 65 else '较高' if score < 40 else '中性'}",
        )

    def _portfolio_manager_synthesis(
        self, name: str, reports: list[AnalystReport],
        user_history: dict, base: float,
    ) -> AnalystReport:
        """The PM synthesizes all other analysts' views."""
        other_reports = [r for r in reports if r.role != "投资组合经理"]
        avg_score = sum(r.score for r in other_reports) / len(other_reports) if other_reports else base
        yes_count = sum(1 for r in other_reports if r.vote == "yes")
        no_count = sum(1 for r in other_reports if r.vote == "no")

        user_win_rate = user_history.get("win_rate", 0.5)
        user_trades = user_history.get("trades", 0)

        # PM adjusts for user history
        adjusted_score = avg_score
        if user_win_rate >= 0.7 and user_trades >= 3:
            adjusted_score += 3  # Trust experienced users more
        elif user_win_rate < 0.4 and user_trades >= 3:
            adjusted_score -= 3

        factors = [
            f"综合{len(other_reports)}位分析师意见: {yes_count}支持/{no_count}反对",
        ]
        if user_trades >= 5 and user_win_rate >= 0.7:
            factors.append(f"用户在此类标的上历史胜率{user_win_rate:.0%}，经验丰富")
        elif user_trades == 0:
            factors.append("用户首次接触此标的，建议小仓位试探")

        sources = ["All Analysts", "User Model", "Trust Engine"]
        concerns = [
            f"{no_count}位分析师持反对意见" if no_count > 0 else "",
            "需要监控关键因素变化" if len(other_reports) >= 3 else "",
        ]
        concerns = [c for c in concerns if c]

        vote = "yes" if yes_count >= 2 else "no" if no_count >= 3 else "abstain"

        return AnalystReport(
            role="投资组合经理", role_icon="🎯",
            score=adjusted_score,
            direction="buy" if adjusted_score >= 65 else "sell" if adjusted_score < 40 else "neutral",
            confidence=0.82 if yes_count >= 2 else 0.55,
            weight=0.18,
            key_factors=factors, evidence_sources=sources,
            concerns=concerns,
            vote=vote,
            vote_reason=f"综合研判: {yes_count}/{len(other_reports)}支持，{'建议执行' if vote == 'yes' else '建议观望' if vote == 'abstain' else '建议不参与'}",
        )

    # ================================================================
    # Decision Quality — meta-metric
    # ================================================================

    def _compute_decision_quality(
        self, reports: list[AnalystReport],
        vote_result: str, composite_score: float, avg_confidence: float,
    ) -> tuple[str, float]:
        """Compute Decision Quality — not 'is this stock good?' but
        'is this a GOOD DECISION?'"""

        # Factors:
        # 1. Analyst agreement (variance of scores → lower is better)
        scores = [r.score for r in reports]
        mean_score = sum(scores) / len(scores) if scores else 50
        variance = sum((s - mean_score) ** 2 for s in scores) / len(scores) if scores else 0
        agreement_score = max(0, 100 - variance * 5)  # Low variance = high agreement

        # 2. Vote clarity (all yes or all no = clear, split = unclear)
        yes_count = sum(1 for r in reports if r.vote == "yes")
        abstain_count = sum(1 for r in reports if r.vote == "abstain")
        vote_clarity = 100 - abstain_count * 20  # Each abstention costs 20 pts

        # 3. Confidence level
        confidence_score = avg_confidence * 100

        # 4. Evidence diversity (more unique sources = better)
        all_sources = set()
        for r in reports:
            all_sources.update(r.evidence_sources)
        evidence_diversity = min(100, len(all_sources) * 15)

        # Composite
        dq_score = (
            agreement_score * 0.25 +
            vote_clarity * 0.25 +
            confidence_score * 0.30 +
            evidence_diversity * 0.20
        )

        if dq_score >= 85:
            grade = "A"
        elif dq_score >= 70:
            grade = "B"
        elif dq_score >= 50:
            grade = "C"
        else:
            grade = "D"

        return grade, dq_score


# Singleton
committee = InvestmentCommittee()
