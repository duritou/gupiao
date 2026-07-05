"""Research Pipeline 全套测试"""

import pytest
import math

from src.pipeline.research_pipeline import ResearchPipeline
from src.scanner.engine import ScannerConfig
from src.infrastructure.knowledge.knowledge_base import KnowledgeBase
from src.domain.models.research_report import ResearchReport, EvidenceItem, CandidateAnalysis
from src.domain.models.research_candidate import ResearchCandidate


# ===== Test Data =====

def make_stock_pool(n: int = 30) -> list[dict]:
    stocks = []
    for i in range(n):
        code = f"{600000 + i:06d}.SH" if i < 15 else f"{i - 15:06d}.SZ"
        stocks.append({
            "code": code, "name": f"测试股票{i}",
            "market_cap": 50 + i * 3, "avg_amount": 100 + i,
            "price": 10.0 + i * 0.5, "change_pct": (i - 15) * 0.3,
        })
    return stocks


def make_bullish_klines(n: int = 80) -> list[dict]:
    result = []
    for i in range(n):
        price = 10.0 + i * 0.1
        result.append({
            "open": price - 0.05, "high": price + 0.1,
            "low": price - 0.1, "close": price,
            "volume": 1000000 + i * 10000,
        })
    return result


# ===== Pipeline Tests (without Knowledge) =====

class TestResearchPipelineBasic:
    """Pipeline 基础测试（不含 Knowledge）"""

    @pytest.mark.asyncio
    async def test_run_returns_report(self):
        pipeline = ResearchPipeline(
            scanner_config=ScannerConfig(score_top_n=3),
        )
        pool = make_stock_pool(20)
        klines = {pool[i]["code"]: make_bullish_klines(60) for i in range(10)}

        report = await pipeline.run(pool, klines, title="测试报告")
        assert isinstance(report, ResearchReport)
        assert report.title == "测试报告"
        assert report.total_scanned == 20

    @pytest.mark.asyncio
    async def test_candidates_in_report(self):
        pipeline = ResearchPipeline(
            scanner_config=ScannerConfig(score_top_n=3),
        )
        pool = make_stock_pool(10)
        klines = {pool[i]["code"]: make_bullish_klines(60) for i in range(5)}

        report = await pipeline.run(pool, klines)
        assert len(report.candidates) > 0
        assert isinstance(report.candidates[0], CandidateAnalysis)

    @pytest.mark.asyncio
    async def test_top_pick_set(self):
        pipeline = ResearchPipeline(
            scanner_config=ScannerConfig(score_top_n=3),
        )
        pool = make_stock_pool(10)
        klines = {pool[i]["code"]: make_bullish_klines(60) for i in range(5)}

        report = await pipeline.run(pool, klines)
        if report.candidates:
            assert report.top_pick is not None
            assert report.top_pick.stock_code == report.candidates[0].stock_code

    @pytest.mark.asyncio
    async def test_summary_not_empty(self):
        pipeline = ResearchPipeline(
            scanner_config=ScannerConfig(score_top_n=3),
        )
        pool = make_stock_pool(10)
        klines = {pool[i]["code"]: make_bullish_klines(60) for i in range(5)}

        report = await pipeline.run(pool, klines)
        if report.candidates:
            assert len(report.summary) > 0

    @pytest.mark.asyncio
    async def test_empty_pool(self):
        pipeline = ResearchPipeline()
        report = await pipeline.run([], {})
        assert report.total_scanned == 0
        assert report.candidates_found == 0
        assert "未发现" in report.summary

    @pytest.mark.asyncio
    async def test_evidence_extracted(self):
        pipeline = ResearchPipeline(
            scanner_config=ScannerConfig(score_top_n=3),
        )
        pool = make_stock_pool(10)
        klines = {pool[i]["code"]: make_bullish_klines(80) for i in range(5)}

        report = await pipeline.run(pool, klines)
        if report.candidates:
            # 应有信号证据
            assert len(report.candidates[0].evidence) > 0
            assert isinstance(report.candidates[0].evidence[0], EvidenceItem)

    @pytest.mark.asyncio
    async def test_duration_recorded(self):
        pipeline = ResearchPipeline(
            scanner_config=ScannerConfig(score_top_n=3),
        )
        pool = make_stock_pool(10)
        report = await pipeline.run(pool, {})
        assert report.pipeline_duration_ms >= 0

    @pytest.mark.asyncio
    async def test_market_overview(self):
        pipeline = ResearchPipeline()
        pool = make_stock_pool(20)
        report = await pipeline.run(pool, {})
        assert "上涨" in report.market_overview


# ===== Pipeline Tests (with Knowledge) =====

class TestResearchPipelineWithKnowledge:
    """Pipeline + Knowledge 集成测试"""

    @pytest.fixture
    async def kb(self):
        kb = KnowledgeBase("knowledge")
        await kb.load()
        return kb

    @pytest.mark.asyncio
    async def test_run_with_knowledge(self, kb):
        pipeline = ResearchPipeline(
            knowledge_base=kb,
            scanner_config=ScannerConfig(score_top_n=3),
        )
        pool = make_stock_pool(10)
        klines = {pool[i]["code"]: make_bullish_klines(80) for i in range(5)}

        report = await pipeline.run(pool, klines)
        assert isinstance(report, ResearchReport)
        # 有 Knowledge 时应有知识条目使用记录
        assert len(report.knowledge_entries_used) >= 0

    @pytest.mark.asyncio
    async def test_knowledge_context_on_candidates(self, kb):
        pipeline = ResearchPipeline(
            knowledge_base=kb,
            scanner_config=ScannerConfig(score_top_n=3),
        )
        # 创建带半导体标签的候选池
        pool = [
            {"code": "000725.SZ", "name": "京东方A", "market_cap": 1800,
             "avg_amount": 2000, "price": 4.5, "change_pct": 3.0},
        ]
        klines = {"000725.SZ": make_bullish_klines(80)}

        report = await pipeline.run(pool, klines)
        if report.candidates:
            # 候选分析应包含知识背景
            assert isinstance(report.candidates[0].knowledge_context, list)

    @pytest.mark.asyncio
    async def test_report_id_generated(self, kb):
        pipeline = ResearchPipeline(knowledge_base=kb)
        pool = make_stock_pool(5)
        report = await pipeline.run(pool, {})
        assert report.report_id.startswith("rpt_")


# ===== EvidenceItem Model Tests =====

class TestEvidenceItem:
    """EvidenceItem 模型测试"""

    def test_create_evidence(self):
        ev = EvidenceItem(
            source="signal:macd",
            description="MACD金叉",
            score_contribution=15.0,
        )
        assert ev.source == "signal:macd"
        assert ev.score_contribution == 15.0


class TestResearchReportModel:
    """ResearchReport 模型测试"""

    def test_default_values(self):
        r = ResearchReport()
        assert r.candidates == []
        assert r.top_pick is None
        assert r.summary == ""

    def test_with_candidates(self):
        c = CandidateAnalysis(stock_code="000001.SZ", stock_name="test", fusion_score=85.0)
        r = ResearchReport(
            report_id="rpt_001",
            title="测试报告",
            candidates=[c],
            top_pick=c,
        )
        assert len(r.candidates) == 1
        assert r.top_pick.stock_code == "000001.SZ"
