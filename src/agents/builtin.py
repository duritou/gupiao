"""内置 Agent — Analyst / Reviewer / Reporter

Analyst:  基于 Evidence 生成结构化分析
Reviewer: 检查分析质量（证据支撑/逻辑自洽/过度推断）
Reporter: 输出自然语言研究报告
"""

from __future__ import annotations

from src.agents.base import BaseAgent, AgentContext, AgentResult, AgentMode


class AnalystAgent(BaseAgent):
    """分析 Agent — 基于 Evidence 生成结构化分析

    输入: ResearchReport 中的 candidates + evidence
    输出: 每只候选标的的结构化分析（含推理过程）
    """

    name = "analyst"
    description = "基于证据链生成结构化分析"
    mode = AgentMode.RULE

    async def execute(self, context: AgentContext) -> AgentResult:
        candidates = context.input_data.get("candidates", [])
        if not candidates:
            return self._ok({"analyses": [], "summary": "无候选标的可供分析"})

        analyses = []
        for c in candidates:
            analysis = self._analyze_one(c, context.knowledge_context)
            analyses.append(analysis)

        # 生成综合分析
        summary = self._synthesize(analyses)

        return self._ok(
            output={"analyses": analyses, "synthesis": summary},
            thinking=f"分析了{len(analyses)}只候选标的，生成综合结论",
        )

    def _analyze_one(self, candidate: dict, knowledge: str) -> dict:
        """分析单只标的"""
        evidence = candidate.get("evidence", [])
        score = candidate.get("fusion_score", 50)
        direction = candidate.get("direction", "neutral")
        name = candidate.get("stock_name", candidate.get("stock_code", ""))

        # 按证据来源分组
        signal_evidence = [e for e in evidence if e.get("source", "").startswith("signal:")]
        market_evidence = [e for e in evidence if e.get("source") == "market_data"]
        knowledge_evidence = [e for e in evidence if e.get("source", "").startswith("knowledge:")]

        # 推理
        reasoning_lines = []
        if score >= 80:
            reasoning_lines.append(f"{name}综合评分{score:.0f}分，多项指标共振看多。")
        elif score >= 60:
            reasoning_lines.append(f"{name}综合评分{score:.0f}分，偏多但需关注风险。")
        elif score <= 30:
            reasoning_lines.append(f"{name}综合评分{score:.0f}分，多项指标偏空。")
        else:
            reasoning_lines.append(f"{name}综合评分{score:.0f}分，信号中性。")

        if signal_evidence:
            signals_desc = "；".join(e.get("description", "") for e in signal_evidence[:3])
            reasoning_lines.append(f"技术面: {signals_desc}。")

        if market_evidence:
            market_desc = "；".join(e.get("description", "") for e in market_evidence[:2])
            reasoning_lines.append(f"量价特征: {market_desc}。")

        if knowledge_evidence:
            reasoning_lines.append(f"行业背景: 结合知识库分析。")

        # 风险提示
        risks = []
        if score < 60:
            risks.append("评分偏低，需警惕下行风险")
        if direction == "sell":
            risks.append("信号方向偏空")
        evidence_count = len(evidence)
        if evidence_count < 2:
            risks.append("证据数量不足，结论置信度有限")

        return {
            "stock_code": candidate.get("stock_code", ""),
            "stock_name": name,
            "score": score,
            "direction": direction,
            "reasoning": "".join(reasoning_lines),
            "risks": risks,
            "evidence_count": evidence_count,
            "signal_count": len(signal_evidence),
            "market_evidence_count": len(market_evidence),
            "knowledge_used": bool(knowledge_evidence),
        }

    def _synthesize(self, analyses: list[dict]) -> str:
        """综合所有分析"""
        if not analyses:
            return ""
        buy_count = sum(1 for a in analyses if a["direction"] == "buy")
        total = len(analyses)
        top = analyses[0]

        lines = [
            f"共分析{total}只候选标的，{buy_count}只看多。",
            f"首选: {top['stock_name']}({top['stock_code']})，评分{top['score']:.0f}分。",
        ]
        return "".join(lines)


class ReviewerAgent(BaseAgent):
    """审查 Agent — 检查 Analyst 输出质量

    检查项:
      1. 结论是否有证据支撑
      2. 逻辑是否自洽
      3. 是否存在过度推断
      4. 风险是否被提及
    """

    name = "reviewer"
    description = "检查分析质量，减少幻觉和过度推断"
    mode = AgentMode.RULE

    async def execute(self, context: AgentContext) -> AgentResult:
        analyses = context.input_data.get("analyses", [])
        if not analyses:
            return self._ok({"passed": True, "issues": [], "score": 100})

        issues = []
        total_score = 100

        for a in analyses:
            # 检查证据数量
            evidence_count = a.get("evidence_count", 0)
            if evidence_count == 0:
                issues.append(f"[{a.get('stock_code')}] 无证据支撑，分析不可信")
                total_score -= 50      # 零证据是严重问题
            elif evidence_count < 2:
                issues.append(f"[{a.get('stock_code')}] 证据较少({evidence_count}条)，置信度有限")
                total_score -= 10

            # 检查风险提示
            risks = a.get("risks", [])
            if not risks and a.get("score", 50) < 70:
                issues.append(f"[{a.get('stock_code')}] 评分{a.get('score',0):.0f}但未提示风险")
                total_score -= 10

            # 检查方向一致性
            score = a.get("score", 50)
            direction = a.get("direction", "neutral")
            if direction == "buy" and score < 55:
                issues.append(f"[{a.get('stock_code')}] 方向为buy但评分仅{score:.0f}，不一致")
                total_score -= 15
            if direction == "sell" and score > 45:
                issues.append(f"[{a.get('stock_code')}] 方向为sell但评分{score:.0f}，不一致")
                total_score -= 15

        passed = total_score >= 60
        return self._ok(
            output={
                "passed": passed,
                "issues": issues,
                "score": max(0, total_score),
                "suggestion": "建议补充更多证据" if not passed else "",
            },
            thinking=f"审查完成: {'通过' if passed else '驳回'} (评分{max(0,total_score)})",
        )


class ReporterAgent(BaseAgent):
    """报告 Agent — 生成自然语言研究报告

    输入: Analyst 分析 + Reviewer 审查结果
    输出: 格式化的最终报告
    """

    name = "reporter"
    description = "生成自然语言研究报告"
    mode = AgentMode.RULE

    async def execute(self, context: AgentContext) -> AgentResult:
        analyses = context.input_data.get("analyses", [])
        review = context.input_data.get("review", {})
        title = context.input_data.get("title", "研究日报")
        summary = context.input_data.get("summary", "")

        # 构建报告
        sections = []
        sections.append(f"# {title}")
        sections.append("")

        if summary:
            sections.append("## 摘要")
            sections.append(summary)
            sections.append("")

        if review.get("issues"):
            sections.append("## 质量审查")
            for issue in review["issues"]:
                sections.append(f"- ⚠️ {issue}")
            sections.append("")

        sections.append("## 候选标的分析")
        sections.append("")

        for i, a in enumerate(analyses, 1):
            sections.append(f"### {i}. {a['stock_name']}({a['stock_code']})")
            sections.append(f"- 综合评分: **{a['score']:.1f}**  |  方向: {a['direction']}")
            sections.append(f"- 证据数量: {a.get('evidence_count', 0)}条")
            sections.append("")
            sections.append(a.get("reasoning", ""))
            sections.append("")

            risks = a.get("risks", [])
            if risks:
                sections.append("**风险提示:**")
                for r in risks:
                    sections.append(f"- {r}")
                sections.append("")

            sections.append("---")
            sections.append("")

        report = "\n".join(sections)

        return self._ok(
            output={"report": report, "sections_count": len(sections)},
            thinking=f"生成研究报告，{len(analyses)}只标的",
        )
