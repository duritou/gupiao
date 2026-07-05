"""Agent Layer 全套测试"""

import pytest

from src.agents.base import BaseAgent, AgentContext, AgentResult, AgentMode
from src.agents.builtin import AnalystAgent, ReviewerAgent, ReporterAgent
from src.agents.orchestrator import AgentOrchestrator, OrchestrationResult
from src.agents.prompt_registry import PromptRegistry, Prompt


# ===== Test Data =====

def make_candidates_with_evidence() -> list[dict]:
    return [
        {
            "stock_code": "000001.SZ", "stock_name": "平安银行",
            "fusion_score": 85.0, "direction": "buy", "confidence": 0.85, "rank": 1,
            "evidence": [
                {"source": "signal:macd", "description": "MACD金叉，DIF上穿DEA", "score_contribution": 15},
                {"source": "signal:ma", "description": "站上MA20，多头排列", "score_contribution": 10},
                {"source": "market_data", "description": "放量1.8倍突破平台", "score_contribution": 5},
                {"source": "knowledge:banking", "description": "银行业净息差企稳", "score_contribution": 3},
            ],
        },
        {
            "stock_code": "000002.SZ", "stock_name": "万科A",
            "fusion_score": 35.0, "direction": "sell", "confidence": 0.70, "rank": 2,
            "evidence": [
                {"source": "signal:rsi", "description": "RSI=25超卖区", "score_contribution": -15},
            ],
        },
    ]


def make_empty_candidates() -> list[dict]:
    return []


# ===== BaseAgent Tests =====

class TestBaseAgent:
    """BaseAgent 基础测试"""

    def test_ok_result(self):
        agent = AnalystAgent()
        result = agent._ok({"test": "value"}, "thinking...", 100)
        assert result.success is True
        assert result.output == {"test": "value"}
        assert result.thinking_trace == "thinking..."
        assert result.tokens_used == 100

    def test_fail_result(self):
        agent = AnalystAgent()
        result = agent._fail("error msg")
        assert result.success is False
        assert "error msg" in result.errors

    def test_agent_metadata(self):
        agent = AnalystAgent()
        assert agent.name == "analyst"
        assert agent.mode == AgentMode.RULE


# ===== AnalystAgent Tests =====

class TestAnalystAgent:
    """AnalystAgent 测试"""

    @pytest.mark.asyncio
    async def test_analyze_candidates(self):
        agent = AnalystAgent()
        ctx = AgentContext(
            input_data={"candidates": make_candidates_with_evidence()},
            knowledge_context="银行业: 净息差企稳",
        )
        result = await agent.execute(ctx)
        assert result.success is True
        analyses = result.output.get("analyses", [])
        assert len(analyses) == 2
        assert "平安银行" in analyses[0]["stock_name"]

    @pytest.mark.asyncio
    async def test_analyze_empty(self):
        agent = AnalystAgent()
        ctx = AgentContext(input_data={"candidates": []})
        result = await agent.execute(ctx)
        assert "无候选" in result.output.get("summary", "")

    @pytest.mark.asyncio
    async def test_reasoning_contains_evidence(self):
        agent = AnalystAgent()
        ctx = AgentContext(
            input_data={"candidates": make_candidates_with_evidence()},
        )
        result = await agent.execute(ctx)
        analysis = result.output["analyses"][0]
        assert len(analysis["reasoning"]) > 0
        assert analysis["evidence_count"] == 4

    @pytest.mark.asyncio
    async def test_high_score_has_risks_too(self):
        """高分标的也应有风险提示"""
        agent = AnalystAgent()
        ctx = AgentContext(
            input_data={"candidates": [make_candidates_with_evidence()[0]]},
        )
        result = await agent.execute(ctx)
        analysis = result.output["analyses"][0]
        assert "risks" in analysis

    @pytest.mark.asyncio
    async def test_synthesis(self):
        agent = AnalystAgent()
        ctx = AgentContext(
            input_data={"candidates": make_candidates_with_evidence()},
        )
        result = await agent.execute(ctx)
        synthesis = result.output.get("synthesis", "")
        assert "平安银行" in synthesis
        assert "1只看多" in synthesis


# ===== ReviewerAgent Tests =====

class TestReviewerAgent:
    """ReviewerAgent 测试"""

    def make_analyses(self) -> list[dict]:
        return [
            {
                "stock_code": "000001.SZ", "stock_name": "test",
                "score": 85, "direction": "buy",
                "evidence_count": 4, "risks": ["估值偏高"],
                "signal_count": 2, "market_evidence_count": 1, "knowledge_used": True,
            },
        ]

    @pytest.mark.asyncio
    async def test_passes_good_analysis(self):
        agent = ReviewerAgent()
        ctx = AgentContext(input_data={"analyses": self.make_analyses()})
        result = await agent.execute(ctx)
        assert result.success is True
        assert result.output["passed"] is True

    @pytest.mark.asyncio
    async def test_fails_no_evidence(self):
        agent = ReviewerAgent()
        analyses = [{
            "stock_code": "000001.SZ", "stock_name": "test",
            "score": 85, "direction": "buy", "evidence_count": 0, "risks": [],
        }]
        ctx = AgentContext(input_data={"analyses": analyses})
        result = await agent.execute(ctx)
        assert result.output["passed"] is False
        assert any("无证据" in i for i in result.output["issues"])

    @pytest.mark.asyncio
    async def test_flags_direction_score_mismatch(self):
        agent = ReviewerAgent()
        analyses = [{
            "stock_code": "000001.SZ", "stock_name": "test",
            "score": 40, "direction": "buy", "evidence_count": 3, "risks": ["risky"],
        }]
        ctx = AgentContext(input_data={"analyses": analyses})
        result = await agent.execute(ctx)
        # buy 但 score=40 → 不一致
        assert any("不一致" in i for i in result.output["issues"])

    @pytest.mark.asyncio
    async def test_flags_missing_risks(self):
        agent = ReviewerAgent()
        analyses = [{
            "stock_code": "000001.SZ", "stock_name": "test",
            "score": 40, "direction": "sell", "evidence_count": 1, "risks": [],
        }]
        ctx = AgentContext(input_data={"analyses": analyses})
        result = await agent.execute(ctx)
        assert any("风险" in i for i in result.output["issues"])

    @pytest.mark.asyncio
    async def test_empty_analyses_passes(self):
        agent = ReviewerAgent()
        ctx = AgentContext(input_data={"analyses": []})
        result = await agent.execute(ctx)
        assert result.output["passed"] is True


# ===== ReporterAgent Tests =====

class TestReporterAgent:
    """ReporterAgent 测试"""

    @pytest.mark.asyncio
    async def test_generates_report(self):
        agent = ReporterAgent()
        ctx = AgentContext(input_data={
            "analyses": [
                {"stock_code": "000001.SZ", "stock_name": "平安银行",
                 "score": 85.0, "direction": "buy", "evidence_count": 4,
                 "reasoning": "多项指标共振看多", "risks": ["估值偏高"]},
            ],
            "review": {"passed": True, "issues": [], "score": 95},
            "title": "研究日报",
            "summary": "今日共分析1只标的",
        })
        result = await agent.execute(ctx)
        assert result.success is True
        report = result.output["report"]
        assert "# 研究日报" in report
        assert "平安银行" in report
        assert "85.0" in report

    @pytest.mark.asyncio
    async def test_report_includes_risks(self):
        agent = ReporterAgent()
        ctx = AgentContext(input_data={
            "analyses": [
                {"stock_code": "000001.SZ", "stock_name": "test",
                 "score": 60.0, "direction": "neutral", "evidence_count": 1,
                 "reasoning": "中性", "risks": ["高风险"]},
            ],
            "review": {"passed": True, "issues": [], "score": 80},
            "title": "test",
        })
        result = await agent.execute(ctx)
        assert "风险提示" in result.output["report"]

    @pytest.mark.asyncio
    async def test_report_includes_review_issues(self):
        agent = ReporterAgent()
        ctx = AgentContext(input_data={
            "analyses": [
                {"stock_code": "000001.SZ", "stock_name": "test",
                 "score": 50, "direction": "neutral", "evidence_count": 1,
                 "reasoning": "", "risks": []},
            ],
            "review": {"passed": False, "issues": ["证据不足"], "score": 50},
            "title": "test",
        })
        result = await agent.execute(ctx)
        report = result.output["report"]
        assert "⚠️" in report or "质量审查" in report


# ===== Orchestrator Tests =====

class TestOrchestrator:
    """AgentOrchestrator 集成测试"""

    @pytest.mark.asyncio
    async def test_run_pipeline(self):
        orch = AgentOrchestrator(max_retries=1)
        result = await orch.run_pipeline(
            candidates=make_candidates_with_evidence(),
            title="研究日报",
            summary="测试摘要",
            session_id="test_001",
        )
        assert result.success is True
        assert result.analyst_result is not None
        assert result.reviewer_result is not None
        assert result.reporter_result is not None
        assert len(result.final_report) > 0

    @pytest.mark.asyncio
    async def test_analyst_output_contains_analyses(self):
        orch = AgentOrchestrator()
        result = await orch.run_pipeline(make_candidates_with_evidence())
        analyses = result.analyst_result.output["analyses"]
        assert len(analyses) == 2

    @pytest.mark.asyncio
    async def test_reviewer_passes_quality_analysis(self):
        orch = AgentOrchestrator()
        result = await orch.run_pipeline(make_candidates_with_evidence())
        assert result.reviewer_result.output["passed"] is True

    @pytest.mark.asyncio
    async def test_final_report_not_empty(self):
        orch = AgentOrchestrator()
        result = await orch.run_pipeline(make_candidates_with_evidence())
        assert len(result.final_report) > 100

    @pytest.mark.asyncio
    async def test_lite_mode(self):
        orch = AgentOrchestrator()
        result = await orch.run_lite(make_candidates_with_evidence())
        assert result.success is True
        assert result.reviewer_result is None  # lite 跳过 Reviewer

    @pytest.mark.asyncio
    async def test_empty_candidates(self):
        orch = AgentOrchestrator()
        result = await orch.run_pipeline([], title="空报告")
        assert result.success is True
        assert result.analyst_result is not None


# ===== PromptRegistry Tests =====

class TestPromptRegistry:
    """PromptRegistry 测试"""

    def test_register_and_get(self):
        reg = PromptRegistry()
        reg.register(Prompt(name="analyst", version="v1", template="分析{{stock}}"))
        p = reg.get("analyst")
        assert p is not None
        assert p.template == "分析{{stock}}"

    def test_activate_version(self):
        reg = PromptRegistry()
        reg.register(Prompt(name="analyst", version="v1", template="v1 template"))
        reg.register(Prompt(name="analyst", version="v2", template="v2 template", is_active=False))

        reg.activate("analyst", "v2")
        active = reg.get_active("analyst")
        assert active is not None
        assert active.version == "v2"

    def test_rollback(self):
        reg = PromptRegistry()
        reg.register(Prompt(name="test", version="v1", template="old"))
        reg.register(Prompt(name="test", version="v2", template="new"))
        reg.activate("test", "v2")

        prev = reg.rollback("test")
        assert prev == "v1"
        assert reg.get_active("test").version == "v1"

    def test_list_versions(self):
        reg = PromptRegistry()
        reg.register(Prompt(name="test", version="v1", template="a"))
        reg.register(Prompt(name="test", version="v2", template="b"))
        assert reg.list_versions("test") == ["v1", "v2"]

    def test_render(self):
        reg = PromptRegistry()
        reg.register(Prompt(name="test", version="v1", template="分析{{stock}}，评分{{score}}"))
        rendered = reg.render("test", {"stock": "平安银行", "score": "85"})
        assert rendered == "分析平安银行，评分85"

    def test_list_all(self):
        reg = PromptRegistry()
        reg.register(Prompt(name="analyst", version="v1", template="a"))
        reg.register(Prompt(name="reviewer", version="v1", template="b"))
        assert set(reg.list_all()) == {"analyst", "reviewer"}

    def test_get_nonexistent(self):
        reg = PromptRegistry()
        assert reg.get("nonexistent") is None

    def test_rollback_single_version(self):
        reg = PromptRegistry()
        reg.register(Prompt(name="test", version="v1", template="only"))
        assert reg.rollback("test") is None  # 只有一个版本，无法回滚
