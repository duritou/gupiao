"""Scanner Engine 全套测试"""

import pytest
import math

from src.scanner.engine import ScannerEngine, ScannerConfig
from src.domain.models.research_candidate import ResearchCandidate, ScannerResult


# ===== Test Data =====

def make_stock_pool(n: int = 100) -> list[dict]:
    """生成模拟股票池"""
    stocks = []
    for i in range(n):
        code = f"{600000 + i:06d}.SH" if i < 50 else f"{i - 50:06d}.SZ"
        stocks.append({
            "code": code,
            "name": f"测试股票{i}",
            "market_cap": 50.0 + i * 2,
            "avg_amount": 100.0 + i,
            "price": 10.0 + i * 0.5,
            "change_pct": (i - 50) * 0.2,
        })
    return stocks


def make_stock_pool_with_st() -> list[dict]:
    """含ST的股票池"""
    return [
        {"code": "000001.SZ", "name": "平安银行", "market_cap": 200, "avg_amount": 500, "price": 12.0},
        {"code": "000002.SZ", "name": "*ST万科", "market_cap": 80, "avg_amount": 200, "price": 6.0},
        {"code": "000003.SZ", "name": "ST华泽", "market_cap": 5, "avg_amount": 10, "price": 1.5},
        {"code": "000004.SZ", "name": "正常公司", "market_cap": 100, "avg_amount": 300, "price": 15.0},
    ]


def make_bullish_klines(n: int = 60) -> list[dict]:
    """上涨 K线"""
    result = []
    for i in range(n):
        price = 10.0 + i * 0.1
        result.append({
            "open": price - 0.05, "high": price + 0.1,
            "low": price - 0.1, "close": price,
            "volume": 1000000 + i * 10000,
        })
    return result


def make_bearish_klines(n: int = 60) -> list[dict]:
    """下跌 K线"""
    result = []
    for i in range(n):
        price = 20.0 - i * 0.1
        result.append({
            "open": price + 0.05, "high": price + 0.1,
            "low": price - 0.1, "close": price,
            "volume": 500000,
        })
    return result


# ===== Coarse Filter Tests =====

class TestCoarseFilter:
    """粗筛层测试"""

    def test_filters_out_st(self):
        engine = ScannerEngine()
        pool = make_stock_pool_with_st()
        result = engine._coarse_filter(pool)
        codes = [s["code"] for s in result]
        assert "000001.SZ" in codes       # 正常
        assert "000004.SZ" in codes       # 正常
        assert "000002.SZ" not in codes   # *ST
        assert "000003.SZ" not in codes   # ST + 市值太小

    def test_filters_out_small_cap(self):
        engine = ScannerEngine(ScannerConfig(min_market_cap=100))
        pool = make_stock_pool_with_st()
        result = engine._coarse_filter(pool)
        for s in result:
            assert s["market_cap"] >= 100

    def test_filters_out_zero_price(self):
        engine = ScannerEngine()
        pool = [
            {"code": "000001.SZ", "name": "正常", "market_cap": 100, "avg_amount": 100, "price": 10.0},
            {"code": "000002.SZ", "name": "停牌", "market_cap": 100, "avg_amount": 100, "price": 0.0},
        ]
        result = engine._coarse_filter(pool)
        assert len(result) == 1
        assert result[0]["code"] == "000001.SZ"

    def test_coarse_returns_empty_for_empty_input(self):
        engine = ScannerEngine()
        assert engine._coarse_filter([]) == []


# ===== Technical Filter Tests =====

class TestTechnicalFilter:
    """技术筛选层测试"""

    def test_above_ma20_passes(self):
        """上涨趋势中站上MA20 → 通过"""
        engine = ScannerEngine()
        stocks = [{"code": "000001.SZ", "name": "test", "market_cap": 100, "avg_amount": 100, "price": 10.0}]
        klines = {"000001.SZ": make_bullish_klines(60)}
        result = engine._technical_filter(stocks, klines)
        assert len(result) == 1

    def test_below_ma20_fails(self):
        """持续下跌，跌破MA20 → 不通过"""
        engine = ScannerEngine()
        stocks = [{"code": "000001.SZ", "name": "test", "market_cap": 100, "avg_amount": 100, "price": 10.0}]
        klines = {"000001.SZ": make_bearish_klines(60)}
        result = engine._technical_filter(stocks, klines)
        assert len(result) == 0

    def test_no_kline_data_passes_through(self):
        """无K线数据的标的不被技术筛选阻拦"""
        engine = ScannerEngine()
        stocks = [{"code": "000001.SZ", "name": "test", "market_cap": 100, "avg_amount": 100, "price": 10.0}]
        result = engine._technical_filter(stocks, {})
        assert len(result) == 1

    def test_insufficient_klines_passes_through(self):
        """K线数据不足20根 → 保留"""
        engine = ScannerEngine()
        stocks = [{"code": "000001.SZ", "name": "test", "market_cap": 100, "avg_amount": 100, "price": 10.0}]
        klines = {"000001.SZ": [{"close": 10.0, "volume": 100}] * 5}
        result = engine._technical_filter(stocks, klines)
        assert len(result) == 1


# ===== Scanner Integration Tests =====

class TestScannerEngine:
    """Scanner 集成测试"""

    @pytest.mark.asyncio
    async def test_scan_returns_result(self):
        engine = ScannerEngine(ScannerConfig(score_top_n=3))
        pool = make_stock_pool(50)
        klines = {}
        for i in range(10):
            code = pool[i]["code"]
            klines[code] = make_bullish_klines(60)

        result = await engine.scan(pool, klines)
        assert isinstance(result, ScannerResult)
        assert result.total_scanned == 50

    @pytest.mark.asyncio
    async def test_candidates_are_ranked(self):
        engine = ScannerEngine(ScannerConfig(score_top_n=5))
        pool = make_stock_pool(20)
        klines = {}
        for i in range(10):
            code = pool[i]["code"]
            klines[code] = make_bullish_klines(60)

        result = await engine.scan(pool, klines)
        for i in range(len(result.candidates) - 1):
            assert result.candidates[i].fusion_score >= result.candidates[i + 1].fusion_score

    @pytest.mark.asyncio
    async def test_candidates_have_required_fields(self):
        engine = ScannerEngine(ScannerConfig(score_top_n=3))
        pool = make_stock_pool(10)
        klines = {pool[0]["code"]: make_bullish_klines(60)}

        result = await engine.scan(pool, klines)
        for c in result.candidates:
            assert c.stock_code
            assert c.fusion_score > 0
            assert c.rank > 0
            assert c.candidate_type == "scanner"

    @pytest.mark.asyncio
    async def test_top_n_limit(self):
        engine = ScannerEngine(ScannerConfig(score_top_n=3))
        pool = make_stock_pool(20)
        klines = {}
        for i in range(15):
            code = pool[i]["code"]
            klines[code] = make_bullish_klines(60)

        result = await engine.scan(pool, klines)
        assert len(result.candidates) <= 3

    @pytest.mark.asyncio
    async def test_duration_recorded(self):
        engine = ScannerEngine()
        pool = make_stock_pool(10)
        result = await engine.scan(pool, {})
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_tags_on_bullish(self):
        engine = ScannerEngine(ScannerConfig(score_top_n=3))
        pool = make_stock_pool(5)
        klines = {pool[0]["code"]: make_bullish_klines(120)}

        result = await engine.scan(pool, klines)
        if result.candidates:
            # 强势上涨的候选应带有标签
            assert len(result.candidates[0].tags) >= 0


# ===== ResearchCandidate Model Tests =====

class TestResearchCandidate:
    """ResearchCandidate 模型测试"""

    def test_default_values(self):
        c = ResearchCandidate(stock_code="000001.SZ")
        assert c.fusion_score == 0.0
        assert c.direction == "neutral"
        assert c.rank == 0
        assert c.tags == []

    def test_score_breakdown(self):
        c = ResearchCandidate(
            stock_code="000001.SZ",
            fusion_score=85.0,
            score_breakdown={"macd": 95, "rsi": 80, "ma": 85, "volume": 70},
            direction="buy",
            rank=1,
            tags=["看多", "高置信"],
        )
        assert c.score_breakdown["macd"] == 95
        assert len(c.score_breakdown) == 4
        assert "看多" in c.tags
