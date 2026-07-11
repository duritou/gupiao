"""Decision Governance — v11.0. The audit layer above the Investment Committee.

Not making decisions. Auditing them.

Every committee decision passes through 7 governance checks before execution:
  1. Risk Budget — is position within user's risk limits?
  2. Position Limit — is sector concentration acceptable?
  3. Evidence Diversity — are we relying on diverse sources?
  4. Data Trust — is underlying data trustworthy?
  5. Committee Consensus — did the committee reach a clear decision?
  6. Historical Similarity — have similar patterns succeeded before?
  7. Model Drift — has model performance degraded recently?

This is what separates "AI says buy" from "a governed decision platform
says buy, after verifying 7 independent checks."

Decision Quality from v10 distinguished good decisions from good outcomes.
Governance ensures every decision MEETS a quality bar before it's even made.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ================================================================
# Data Models
# ================================================================

@dataclass
class GovernanceCheck:
    """A single governance check result."""
    check_name: str = ""           # "Risk Budget", "Evidence Diversity", etc.
    check_id: str = ""             # "risk_budget", "evidence_diversity", ...
    category: str = ""             # risk / evidence / alignment / stability
    result: str = ""               # PASS / FAIL / WARN
    score: float = 0.0             # 0-100 for this check
    detail: str = ""               # Human-readable explanation
    recommendation: str = ""       # What to do if FAIL/WARN
    evidence_used: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "check_name": self.check_name,
            "check_id": self.check_id,
            "category": self.category,
            "result": self.result,
            "score": round(self.score, 1),
            "detail": self.detail,
            "recommendation": self.recommendation,
            "evidence_used": self.evidence_used,
        }


@dataclass
class GovernanceResult:
    """Complete governance audit of a decision."""
    stock_code: str = ""
    stock_name: str = ""
    audited_at: str = ""

    # All checks
    checks: list[GovernanceCheck] = field(default_factory=list)

    # Summary
    pass_count: int = 0
    warn_count: int = 0
    fail_count: int = 0
    overall_verdict: str = ""      # APPROVED / APPROVED_WITH_WARNINGS / REJECTED
    overall_score: float = 0.0     # 0-100 weighted composite
    audit_trail_id: str = ""       # Unique audit trace ID

    # Natural language
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "audited_at": self.audited_at[:19] if self.audited_at else "",
            "checks": [c.to_dict() for c in self.checks],
            "pass_count": self.pass_count,
            "warn_count": self.warn_count,
            "fail_count": self.fail_count,
            "overall_verdict": self.overall_verdict,
            "overall_score": round(self.overall_score, 1),
            "audit_trail_id": self.audit_trail_id,
            "summary": self.summary,
        }


# ================================================================
# Decision Governance Engine
# ================================================================

class DecisionGovernor:
    """Audits every committee decision against 7 governance checks.

    The governance layer sits ABOVE the committee. The committee votes.
    Governance verifies. Both must agree for a decision to be APPROVED.

    Governance is not advisory — a FAIL on any critical check (risk budget,
    data trust) means REJECTED regardless of what the committee says.
    """

    # Check weights for overall score (sum to 1.0)
    CHECK_WEIGHTS = {
        "risk_budget": 0.20,
        "position_limit": 0.10,
        "evidence_diversity": 0.20,
        "data_trust": 0.20,
        "committee_consensus": 0.10,
        "historical_similarity": 0.10,
        "model_drift": 0.10,
    }

    def audit(
        self,
        stock_code: str,
        stock_name: str,
        committee_decision: Any = None,     # CommitteeDecision
        user_profile: Any = None,            # UserBehaviorProfile
        decomposed_confidence: Any = None,   # DecomposedConfidence
        evidence_quality: Any = None,        # EvidenceQuality
        calibration_report: Any = None,      # CalibrationReport
        similar_cases_report: Any = None,    # CaseRetrievalReport
        position_pct: float = 0.0,
    ) -> GovernanceResult:
        """Run all seven governance checks and produce a verdict.

        Args:
            stock_code: Stock being evaluated
            stock_name: Human-readable name
            committee_decision: CommitteeDecision from InvestmentCommittee
            user_profile: UserBehaviorProfile (or None for defaults)
            decomposed_confidence: DecomposedConfidence from PortfolioIntelligence
            evidence_quality: EvidenceQuality from EvidenceGrader
            calibration_report: CalibrationReport from CalibrationEngine
            similar_cases_report: CaseRetrievalReport from CaseRetriever
            position_pct: Current position percentage (0 if not held)

        Returns:
            GovernanceResult with all checks and overall verdict
        """
        checks: list[GovernanceCheck] = []

        # 1. Risk Budget Check
        checks.append(self._check_risk_budget(user_profile, position_pct))

        # 2. Position Limit (Concentration) Check
        checks.append(self._check_position_limit(user_profile, stock_name, position_pct))

        # 3. Evidence Diversity Check
        checks.append(self._check_evidence_diversity(evidence_quality))

        # 4. Data Trust Check
        checks.append(self._check_data_trust(decomposed_confidence))

        # 5. Committee Consensus Check
        checks.append(self._check_committee_consensus(committee_decision))

        # 6. Historical Similarity Check
        checks.append(self._check_historical_similarity(similar_cases_report))

        # 7. Model Drift Check
        checks.append(self._check_model_drift(calibration_report))

        # Tally results
        pass_count = sum(1 for c in checks if c.result == "PASS")
        warn_count = sum(1 for c in checks if c.result == "WARN")
        fail_count = sum(1 for c in checks if c.result == "FAIL")

        # Overall verdict
        if fail_count > 0:
            verdict = "REJECTED"
        elif warn_count > 0:
            verdict = "APPROVED_WITH_WARNINGS"
        else:
            verdict = "APPROVED"

        # Overall score: weighted average (FAIL checks contribute 0 to their dimension)
        overall = 0.0
        for check in checks:
            weight = self.CHECK_WEIGHTS.get(check.check_id, 0.10)
            if check.result == "PASS":
                overall += check.score * weight
            elif check.result == "WARN":
                overall += check.score * weight * 0.5
            # FAIL contributes 0

        # Generate audit trail ID
        trail_id = hashlib.md5(
            f"{stock_code}:{datetime.now().isoformat()}:{verdict}".encode()
        ).hexdigest()[:16]

        # Summary
        summary = self._generate_summary(verdict, pass_count, warn_count, fail_count, checks)

        return GovernanceResult(
            stock_code=stock_code,
            stock_name=stock_name,
            audited_at=datetime.now().isoformat(),
            checks=checks,
            pass_count=pass_count,
            warn_count=warn_count,
            fail_count=fail_count,
            overall_verdict=verdict,
            overall_score=overall,
            audit_trail_id=trail_id,
            summary=summary,
        )

    # ================================================================
    # Check 1: Risk Budget
    # ================================================================

    def _check_risk_budget(
        self, user_profile: Any, position_pct: float
    ) -> GovernanceCheck:
        """Verify position is within user's risk tolerance."""
        # Determine user's max position from profile or use defaults
        max_position = 25.0  # Default moderate
        risk_level = "moderate"

        if user_profile and hasattr(user_profile, 'risk_profile') and user_profile.risk_profile:
            rp = user_profile.risk_profile
            max_position = getattr(rp, 'max_position_size_pct', 25.0)
            risk_level = getattr(rp, 'level', '稳健型')

            # Map risk levels to limits
            risk_limits = {"保守型": 15.0, "稳健型": 20.0, "积极型": 30.0, "激进型": 40.0}
            max_position = risk_limits.get(risk_level, 25.0)

        pct_used = (position_pct / max_position * 100) if max_position > 0 else 100

        if position_pct <= max_position * 0.7:
            result = "PASS"
            score = 100.0
            detail = f"仓位{position_pct:.0f}%在风险预算内（上限{max_position:.0f}%），使用率{pct_used:.0f}%。"
            rec = ""
        elif position_pct <= max_position:
            result = "WARN"
            score = 70.0
            detail = f"仓位{position_pct:.0f}%接近上限{max_position:.0f}%（使用率{pct_used:.0f}%），加仓空间有限。"
            rec = f"建议控制仓位不超过{max_position:.0f}%。如果坚持加仓，考虑分批执行并设 tighter stop-loss。"
        else:
            result = "FAIL"
            score = 20.0
            detail = f"仓位{position_pct:.0f}%已超过{risk_level}投资者的风险上限{max_position:.0f}%。继续加仓违反风险纪律。"
            rec = f"强烈建议先减仓至{max_position:.0f}%以下再考虑新增头寸。这不是对股票的判断，是对风险纪律的遵守。"

        return GovernanceCheck(
            check_name="风险预算", check_id="risk_budget", category="risk",
            result=result, score=score, detail=detail, recommendation=rec,
            evidence_used=[f"用户风险等级: {risk_level}", f"仓位上限: {max_position:.0f}%"],
        )

    # ================================================================
    # Check 2: Position Limit (Concentration)
    # ================================================================

    def _check_position_limit(
        self, user_profile: Any, stock_name: str, position_pct: float
    ) -> GovernanceCheck:
        """Verify sector concentration is acceptable."""
        from src.explain.evidence_quality import _guess_sector
        sector = _guess_sector(stock_name)

        # Check if user already has heavy exposure to this sector
        sector_exposure = 0.0
        if user_profile and hasattr(user_profile, 'sector_affinities'):
            for aff in user_profile.sector_affinities:
                if hasattr(aff, 'sector') and aff.sector == sector:
                    sector_exposure = getattr(aff, 'affinity_score', 0) * 100
                    break

        # Concentration risk assessment
        if sector_exposure < 30:
            result = "PASS"
            score = 95.0
            detail = f"{sector}行业敞口{sector_exposure:.0f}%，分散度良好。"
            rec = ""
        elif sector_exposure < 50:
            result = "WARN"
            score = 70.0
            detail = f"{sector}行业敞口{sector_exposure:.0f}%，存在一定集中度风险。"
            rec = f"考虑分散到其他行业以降低{sector}单一行业风险。"
        else:
            result = "FAIL"
            score = 30.0
            detail = f"{sector}行业敞口{sector_exposure:.0f}%，过度集中于单一行业。一旦行业轮动将面临重大回撤。"
            rec = f"强烈建议降低{sector}行业配置，分散到至少3个不同行业。"

        return GovernanceCheck(
            check_name="仓位集中度", check_id="position_limit", category="risk",
            result=result, score=score, detail=detail, recommendation=rec,
            evidence_used=[f"行业: {sector}", f"敞口: {sector_exposure:.0f}%"],
        )

    # ================================================================
    # Check 3: Evidence Diversity
    # ================================================================

    def _check_evidence_diversity(self, evidence_quality: Any) -> GovernanceCheck:
        """Verify evidence comes from diverse source types."""
        if evidence_quality is None:
            return GovernanceCheck(
                check_name="证据多样性", check_id="evidence_diversity", category="evidence",
                result="WARN", score=50.0,
                detail="无法获取证据质量数据。假设证据来源单一。",
                recommendation="等待数据质量评估完成后再做决策。",
                evidence_used=["证据质量数据缺失"],
            )

        official = getattr(evidence_quality, 'official_sources', 0)
        commercial = getattr(evidence_quality, 'commercial_sources', 0)
        community = getattr(evidence_quality, 'community_sources', 0)
        news = getattr(evidence_quality, 'news_sources', 0)
        cross_verified = getattr(evidence_quality, 'cross_verified_count', 0)

        # Count distinct source types with data
        source_types = sum(1 for s in [official, commercial, community, news] if s > 0)
        grade = str(getattr(evidence_quality, 'grade', 'C'))

        evidence_detail = f"官方{official}个, 商业{commercial}个, 社区{community}个, 新闻{news}个, 交叉验证{cross_verified}项"

        if source_types >= 3 and cross_verified >= 3:
            result = "PASS"
            score = 95.0
            detail = f"证据来源多样化（{source_types}类来源），{cross_verified}项交叉验证。{evidence_detail}"
            rec = ""
        elif source_types >= 2 and cross_verified >= 2:
            result = "PASS"
            score = 80.0
            detail = f"证据来源基本多样（{source_types}类来源），{cross_verified}项交叉验证。{evidence_detail}"
            rec = ""
        elif source_types >= 1 and cross_verified >= 1:
            result = "WARN"
            score = 55.0
            detail = f"证据来源有限（仅{source_types}类来源），{cross_verified}项交叉验证。{evidence_detail}"
            rec = "建议等待更多独立来源确认后再做重大仓位决策。单一来源的证据容易被单一数据供应商的偏差影响。"
        else:
            result = "FAIL"
            score = 20.0
            detail = f"证据来源严重不足。{evidence_detail}"
            rec = "证据不足，不应执行任何操作。等待至少2个独立来源交叉验证后再评估。"

        return GovernanceCheck(
            check_name="证据多样性", check_id="evidence_diversity", category="evidence",
            result=result, score=score, detail=detail, recommendation=rec,
            evidence_used=[f"证据等级: {grade}", evidence_detail],
        )

    # ================================================================
    # Check 4: Data Trust
    # ================================================================

    def _check_data_trust(self, decomposed_confidence: Any) -> GovernanceCheck:
        """Verify underlying data is trustworthy."""
        if decomposed_confidence is None:
            return GovernanceCheck(
                check_name="数据可信度", check_id="data_trust", category="evidence",
                result="WARN", score=50.0,
                detail="无法获取数据可信度评估。假设数据质量中等。",
                recommendation="等待数据可信度评估完成。",
                evidence_used=["置信度分解数据缺失"],
            )

        data_trust = getattr(decomposed_confidence, 'data_trust', 0.5)
        model_trust = getattr(decomposed_confidence, 'model_trust', 0.5)
        signal_agreement = getattr(decomposed_confidence, 'signal_agreement', 0.5)

        if data_trust >= 0.80:
            result = "PASS"
            score = 95.0
            detail = f"数据可信度{data_trust:.0%}，高度可信。模型可信度{model_trust:.0%}，信号一致性{signal_agreement:.0%}。"
            rec = ""
        elif data_trust >= 0.60:
            result = "PASS"
            score = 75.0
            detail = f"数据可信度{data_trust:.0%}，基本可信。模型可信度{model_trust:.0%}，信号一致性{signal_agreement:.0%}。"
            rec = ""
        elif data_trust >= 0.40:
            result = "WARN"
            score = 50.0
            detail = f"数据可信度仅{data_trust:.0%}，存在数据质量风险。模型可信度{model_trust:.0%}。"
            rec = "数据质量偏低，AI建议仅供参考。建议核实关键数据点后再决策。不要依据低质量数据做重仓操作。"
        else:
            result = "FAIL"
            score = 15.0
            detail = f"数据可信度严重不足（{data_trust:.0%}）。数据可能包含错误或过期信息。"
            rec = "数据不可信，AI建议不应执行。等待数据质量改善后再重新评估。"

        return GovernanceCheck(
            check_name="数据可信度", check_id="data_trust", category="evidence",
            result=result, score=score, detail=detail, recommendation=rec,
            evidence_used=[
                f"数据信任度: {data_trust:.0%}",
                f"模型信任度: {model_trust:.0%}",
                f"信号一致性: {signal_agreement:.0%}",
            ],
        )

    # ================================================================
    # Check 5: Committee Consensus
    # ================================================================

    def _check_committee_consensus(self, committee_decision: Any) -> GovernanceCheck:
        """Verify the committee reached a clear, quality decision."""
        if committee_decision is None:
            return GovernanceCheck(
                check_name="委员会共识", check_id="committee_consensus", category="alignment",
                result="WARN", score=50.0,
                detail="未进行委员会评估。单点AI判断缺乏多方验证。",
                recommendation="建议运行完整的委员会评估流程。",
                evidence_used=["委员会数据缺失"],
            )

        vote_result = getattr(committee_decision, 'vote_result', 'split')
        yes_votes = getattr(committee_decision, 'yes_votes', 0)
        no_votes = getattr(committee_decision, 'no_votes', 0)
        abstain = getattr(committee_decision, 'abstain_votes', 0)
        dq_grade = getattr(committee_decision, 'decision_quality_grade', 'C')
        dq_score = getattr(committee_decision, 'decision_quality_score', 50.0)

        if vote_result == "passed" and dq_grade in ("A", "B") and yes_votes >= 4:
            result = "PASS"
            score = 95.0
            detail = f"委员会{yes_votes}:{no_votes}高共识通过。决策质量{dq_grade}级（{dq_score:.0f}分）。分析师意见高度一致。"
            rec = ""
        elif vote_result == "passed" and dq_grade in ("A", "B"):
            result = "PASS"
            score = 82.0
            detail = f"委员会{yes_votes}:{no_votes}通过。决策质量{dq_grade}级（{dq_score:.0f}分）。"
            rec = ""
        elif vote_result == "passed":
            result = "WARN"
            score = 60.0
            detail = f"委员会{yes_votes}:{no_votes}通过但决策质量仅{dq_grade}级（{dq_score:.0f}分）。{abstain}位弃权。"
            rec = f"委员会虽然通过但信心不足。建议小仓位试探，等待更多确认信号。"
        elif vote_result == "split":
            result = "WARN"
            score = 40.0
            detail = f"委员会意见分歧（{yes_votes}支持:{no_votes}反对:{abstain}弃权）。分析师之间缺乏共识。"
            rec = "委员会未能形成共识。建议观望，等待更多信号使方向更明确后再决策。"
        else:
            result = "FAIL"
            score = 15.0
            detail = f"委员会{no_votes}:{yes_votes}否决。多数分析师认为不应执行此操作。"
            rec = "委员会明确反对。除非有新的关键信息出现，建议尊重委员会判断。"

        return GovernanceCheck(
            check_name="委员会共识", check_id="committee_consensus", category="alignment",
            result=result, score=score, detail=detail, recommendation=rec,
            evidence_used=[
                f"投票: {yes_votes}支持/{no_votes}反对/{abstain}弃权",
                f"决策质量: {dq_grade}级 ({dq_score:.0f}分)",
            ],
        )

    # ================================================================
    # Check 6: Historical Similarity
    # ================================================================

    def _check_historical_similarity(
        self, similar_cases_report: Any
    ) -> GovernanceCheck:
        """Verify similar historical cases show positive outcomes."""
        if similar_cases_report is None:
            return GovernanceCheck(
                check_name="历史相似性", check_id="historical_similarity", category="stability",
                result="WARN", score=50.0,
                detail="未检索历史相似案例。无法通过历史证据验证当前判断。",
                recommendation="建议运行相似案例检索以获取历史参考。",
                evidence_used=["案例检索数据缺失"],
            )

        total = getattr(similar_cases_report, 'total_similar', 0)
        win_rate = getattr(similar_cases_report, 'aggregate_win_rate', 0)
        avg_return = getattr(similar_cases_report, 'aggregate_avg_return', 0)

        if total >= 20 and win_rate >= 0.65:
            result = "PASS"
            score = 90.0
            detail = f"找到{total}个历史相似案例，胜率{win_rate:.0%}，平均收益{avg_return:+.1f}%。历史证据支持当前判断。"
            rec = ""
        elif total >= 10 and win_rate >= 0.55:
            result = "PASS"
            score = 75.0
            detail = f"找到{total}个相似案例，胜率{win_rate:.0%}，平均收益{avg_return:+.1f}%。历史证据温和支持。"
            rec = ""
        elif total >= 5 and win_rate >= 0.50:
            result = "WARN"
            score = 55.0
            detail = f"仅有{total}个相似案例（胜率{win_rate:.0%}），样本量不足以形成强结论。"
            rec = "相似案例有限，建议参考但不要过度依赖历史模式。更多依靠当前证据质量判断。"
        elif total < 5:
            result = "WARN"
            score = 40.0
            detail = f"仅{total}个相似案例，无法形成统计学上有意义的结论。这可能是一个新的信号模式。"
            rec = "这是AI未曾见过的新模式。建议极度谨慎，小仓位试探，将此次作为一个新的Research Case记录。"
        else:
            result = "FAIL"
            score = 25.0
            detail = f"找到{total}个相似案例但胜率仅{win_rate:.0%}，平均收益{avg_return:+.1f}%。历史证据不支持当前判断。"
            rec = "历史上类似模式表现不佳。除非当前有历史案例中不存在的新增有利因素，否则建议不执行。"

        return GovernanceCheck(
            check_name="历史相似性", check_id="historical_similarity", category="stability",
            result=result, score=score, detail=detail, recommendation=rec,
            evidence_used=[
                f"相似案例: {total}个",
                f"历史胜率: {win_rate:.0%}",
                f"平均收益: {avg_return:+.1f}%",
            ],
        )

    # ================================================================
    # Check 7: Model Drift
    # ================================================================

    def _check_model_drift(self, calibration_report: Any) -> GovernanceCheck:
        """Verify model performance hasn't degraded recently."""
        if calibration_report is None:
            return GovernanceCheck(
                check_name="模型漂移", check_id="model_drift", category="stability",
                result="WARN", score=50.0,
                detail="无法获取模型校准数据。假设模型性能稳定。",
                recommendation="定期运行校准评估以监控模型漂移。",
                evidence_used=["校准数据缺失"],
            )

        cal_score = getattr(calibration_report, 'overall_calibration_score', 0.5)
        is_calibrated = getattr(calibration_report, 'is_well_calibrated', False)

        if cal_score >= 0.85:
            result = "PASS"
            score = 95.0
            detail = f"模型校准优秀（{cal_score:.0%}）。AI置信度与实际准确率高度一致。"
            rec = ""
        elif cal_score >= 0.70:
            result = "PASS"
            score = 78.0
            detail = f"模型校准良好（{cal_score:.0%}）。AI置信度基本反映实际准确率。"
            rec = ""
        elif cal_score >= 0.50:
            result = "WARN"
            score = 55.0
            detail = f"模型校准一般（{cal_score:.0%}）。AI可能存在过度自信或信心不足的倾向。"
            rec = "AI的置信度数字可能不够准确。建议参考置信度区间而非单点数字，同时结合自己的判断。"
        else:
            result = "FAIL"
            score = 25.0
            detail = f"模型校准差（{cal_score:.0%}）。AI置信度与实际结果严重偏离。可能存在模型漂移。"
            rec = "模型可能需要重新训练或调整。在模型校准改善之前，AI建议仅作参考，不可作为主要决策依据。"

        return GovernanceCheck(
            check_name="模型漂移", check_id="model_drift", category="stability",
            result=result, score=score, detail=detail, recommendation=rec,
            evidence_used=[
                f"校准评分: {cal_score:.0%}",
                f"是否校准良好: {is_calibrated}",
            ],
        )

    # ================================================================
    # Summary
    # ================================================================

    def _generate_summary(
        self, verdict: str, pass_count: int, warn_count: int,
        fail_count: int, checks: list[GovernanceCheck],
    ) -> str:
        """Generate natural language summary of the governance audit."""
        if verdict == "APPROVED":
            return (
                f"✅ 治理审核通过。全部{len(checks)}项检查通过，"
                f"该决策符合风险预算、证据标准和投资纪律。可以执行。"
            )
        elif verdict == "APPROVED_WITH_WARNINGS":
            warnings = [c for c in checks if c.result == "WARN"]
            warn_names = "、".join(c.check_name for c in warnings[:3])
            return (
                f"⚠️ 治理审核有条件通过。{pass_count}项通过，{warn_count}项警告（{warn_names}）。"
                f"可以在注意上述警告的前提下执行，但建议降低仓位或等待警告解除。"
            )
        else:
            failures = [c for c in checks if c.result == "FAIL"]
            fail_names = "、".join(c.check_name for c in failures)
            return (
                f"🚫 治理审核未通过。{fail_count}项检查不通过（{fail_names}）。"
                f"建议暂不执行此决策，先解决上述不通过项后再重新提交审核。"
            )


# Singleton
governance_engine = DecisionGovernor()
