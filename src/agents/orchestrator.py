"""AgentOrchestrator — 编排 Agent 协作

协作模式:
  pipeline:  Analyst → Reviewer → Reporter (默认)
  retry:     Analyst → Reviewer → (驳回) → Analyst → Reviewer → Reporter
  lite:      Analyst → Reporter (跳过 Reviewer)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.agents.base import BaseAgent, AgentContext, AgentResult
from src.agents.builtin import AnalystAgent, ReviewerAgent, ReporterAgent


@dataclass
class OrchestrationResult:
    """编排结果"""

    session_id: str = ""
    success: bool = False
    analyst_result: AgentResult | None = None
    reviewer_result: AgentResult | None = None
    reporter_result: AgentResult | None = None
    final_report: str = ""
    retry_count: int = 0
    total_tokens: int = 0
    errors: list[str] = field(default_factory=list)


class AgentOrchestrator:
    """Agent 编排器

    默认管线: Analyst → Reviewer → Reporter
    如果 Reviewer 驳回 → 重试 Analyst → 再次 Reviewer（最多 max_retries 次）
    """

    def __init__(self, max_retries: int = 2):
        self.max_retries = max_retries
        self._analyst = AnalystAgent()
        self._reviewer = ReviewerAgent()
        self._reporter = ReporterAgent()

    async def run_pipeline(
        self,
        candidates: list[dict],
        title: str = "研究日报",
        summary: str = "",
        session_id: str = "",
        knowledge_context: str = "",
    ) -> OrchestrationResult:
        """运行完整管线"""
        result = OrchestrationResult(session_id=session_id)
        ctx = AgentContext(
            session_id=session_id,
            input_data={"candidates": candidates},
            knowledge_context=knowledge_context,
        )

        # Step 1: Analyst
        analyst_result = await self._analyst.execute(ctx)
        result.analyst_result = analyst_result
        result.total_tokens += analyst_result.tokens_used

        if not analyst_result.success:
            result.errors.append(f"Analyst failed: {analyst_result.errors}")
            return result

        analyses = analyst_result.output.get("analyses", [])

        # Step 2: Reviewer (with retry)
        reviewer_ctx = AgentContext(
            session_id=session_id,
            input_data={"analyses": analyses},
        )
        reviewer_result = await self._reviewer.execute(reviewer_ctx)
        result.total_tokens += reviewer_result.tokens_used

        retry_count = 0
        while (not reviewer_result.output.get("passed", True)
               and retry_count < self.max_retries):
            retry_count += 1
            # 重试: 将审查意见反馈给 Analyst
            retry_ctx = AgentContext(
                session_id=session_id,
                input_data={
                    "candidates": candidates,
                    "review_feedback": reviewer_result.output.get("issues", []),
                },
                knowledge_context=knowledge_context,
            )
            analyst_result = await self._analyst.execute(retry_ctx)
            result.total_tokens += analyst_result.tokens_used

            analyses = analyst_result.output.get("analyses", [])
            reviewer_ctx.input_data = {"analyses": analyses}
            reviewer_result = await self._reviewer.execute(reviewer_ctx)
            result.total_tokens += reviewer_result.tokens_used

        result.retry_count = retry_count
        result.reviewer_result = reviewer_result
        result.analyst_result = analyst_result

        # Step 3: Reporter
        reporter_ctx = AgentContext(
            session_id=session_id,
            input_data={
                "analyses": analyses,
                "review": reviewer_result.output,
                "title": title,
                "summary": summary,
            },
        )
        reporter_result = await self._reporter.execute(reporter_ctx)
        result.reporter_result = reporter_result
        result.total_tokens += reporter_result.tokens_used

        result.final_report = reporter_result.output.get("report", "")
        result.success = True
        return result

    async def run_lite(
        self,
        candidates: list[dict],
        title: str = "研究日报",
        session_id: str = "",
    ) -> OrchestrationResult:
        """轻量模式: 跳过 Reviewer"""
        result = OrchestrationResult(session_id=session_id)
        ctx = AgentContext(
            session_id=session_id,
            input_data={"candidates": candidates},
        )

        analyst_result = await self._analyst.execute(ctx)
        result.analyst_result = analyst_result

        reporter_ctx = AgentContext(
            session_id=session_id,
            input_data={
                "analyses": analyst_result.output.get("analyses", []),
                "review": {},
                "title": title,
            },
        )
        reporter_result = await self._reporter.execute(reporter_ctx)
        result.reporter_result = reporter_result
        result.final_report = reporter_result.output.get("report", "")
        result.success = True
        return result
