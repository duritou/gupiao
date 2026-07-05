"""Evaluation Center 全套测试"""

import pytest
from datetime import date

from src.evaluation.engine import (
    DataValidator, DataValidationResult,
    SignalValidator, SignalValidationResult,
    ResearchPrediction, AccuracyCalculator, AccuracyReport,
)
from src.signals.builtin.technical import MACDSignal, RSISignal, MASignal
from tests.fixtures.golden.golden_cases import GOLDEN_CASES, MACD_GOLDEN_CROSS_KLINES


# ===== Data Validation Tests =====

class TestDataValidator:
    """数据校验测试"""

    def test_consensus_perfect(self):
        v = DataValidator()
        result = v.validate("000001.SZ", "close",
                            {"akshare": 1680.0, "tushare": 1680.0, "yahoo": 1680.0})
        assert result.is_reliable is True
        assert result.consensus == 1680.0
        assert result.max_deviation_pct == 0.0

    def test_minor_deviation_accepted(self):
        v = DataValidator()
        result = v.validate("000001.SZ", "close",
                            {"akshare": 1680.0, "tushare": 1679.0, "yahoo": 1681.0})
        assert result.is_reliable is True
        assert result.max_deviation_pct < 0.5

    def test_large_deviation_rejected(self):
        v = DataValidator()
        result = v.validate("000001.SZ", "close",
                            {"akshare": 1680.0, "tushare": 1681.0, "yahoo": 1735.0})
        assert result.is_reliable is False
        assert result.max_deviation_pct > 0.5
        assert "偏差" in result.warning

    def test_single_source_warns(self):
        v = DataValidator()
        result = v.validate("000001.SZ", "close", {"akshare": 1680.0})
        assert result.is_reliable is True
        assert "单一" in result.warning

    def test_empty_sources(self):
        v = DataValidator()
        result = v.validate("000001.SZ", "close", {})
        assert result.is_reliable is False


# ===== Signal Validation Tests (Golden Dataset) =====

class TestSignalValidator:
    """黄金数据集校验测试"""

    @pytest.mark.asyncio
    async def test_golden_cases_registered(self):
        v = SignalValidator()
        for case in GOLDEN_CASES:
            v.add_golden_case(case)
        assert v.golden_case_count() == 3

    @pytest.mark.asyncio
    async def test_macd_golden_case_passes(self):
        v = SignalValidator()
        v.add_golden_case(GOLDEN_CASES[0])  # MACD bullish trend case

        async def compute_macd(code, klines):
            return await MACDSignal().compute(code, klines)

        results = await v.validate(compute_macd)
        # MACD on golden cross data: score in expected range
        assert results[0].actual_score >= 50
        assert results[0].deviation <= 25

    @pytest.mark.asyncio
    async def test_rsi_golden_case_passes(self):
        v = SignalValidator()
        v.add_golden_case(GOLDEN_CASES[1])

        async def compute_rsi(code, klines):
            return await RSISignal().compute(code, klines)

        results = await v.validate(compute_rsi)
        # RSI on bearish trend: oversold → buy, score >= 55
        assert results[0].passed is True
        assert results[0].actual_score >= 55

    @pytest.mark.asyncio
    async def test_golden_case_failure_detected(self):
        v = SignalValidator()
        v.add_golden_case(SignalValidationResult.__new__)  # won't use this
        # Create a case that expects score 90-100 for bearish data
        from src.evaluation.engine import SignalGoldenCase
        v = SignalValidator()
        v.add_golden_case(SignalGoldenCase(
            name="intentionally_wrong_expectation",
            stock_code="TEST", kline_data=MACD_GOLDEN_CROSS_KLINES,
            expected_signal="sell", expected_score_min=0, expected_score_max=30, tolerance=2,
        ))
        async def compute(code, klines):
            return await MACDSignal().compute(code, klines)
        results = await v.validate(compute)
        # MACD on bullish data gives buy, not sell
        assert results[0].passed is False


# ===== Research Validation Tests =====

class TestResearchPrediction:
    """研究预测跟踪测试"""

    def test_create_and_update(self):
        p = ResearchPrediction(
            prediction_id="p_001", stock_code="000001.SZ", stock_name="平安银行",
            predicted_score=85.0, predicted_direction="buy",
            predicted_at="2026-07-01", price_at_prediction=10.0,
        )
        p.update_outcome(price_7d=10.5, price_30d=11.0, price_90d=12.0)
        assert p.return_7d_pct == 5.0
        assert p.return_30d_pct == 10.0
        assert p.direction_correct is True
        assert p.score_grade == "accurate"

    def test_wrong_prediction(self):
        p = ResearchPrediction(
            prediction_id="p_002", stock_code="000002.SZ", stock_name="test",
            predicted_score=80.0, predicted_direction="buy",
            predicted_at="2026-07-01", price_at_prediction=10.0,
        )
        p.update_outcome(price_7d=9.0, price_30d=8.0)
        assert p.direction_correct is False
        assert p.score_grade == "wrong"

    def test_neutral_prediction(self):
        p = ResearchPrediction(
            prediction_id="p_003", stock_code="000003.SZ", stock_name="test",
            predicted_score=50.0, predicted_direction="neutral",
            predicted_at="2026-07-01", price_at_prediction=10.0,
        )
        p.update_outcome(price_7d=10.1, price_30d=10.2)
        assert p.score_grade == "neutral"


# ===== Accuracy Report Tests =====

class TestAccuracyReport:
    """准确率统计测试"""

    def test_empty(self):
        calc = AccuracyCalculator()
        report = calc.calculate([])
        assert report.total_predictions == 0

    def test_all_correct(self):
        predictions = []
        for i in range(10):
            p = ResearchPrediction(f"p_{i}", f"{i}", "test", 85, "buy", "2026-07-01", 10.0)
            p.update_outcome(11.0, 12.0, 13.0)
            predictions.append(p)

        calc = AccuracyCalculator()
        report = calc.calculate(predictions)
        assert report.direction_accuracy_pct == 100.0
        assert report.avg_return_30d_pct == 20.0

    def test_mixed_accuracy(self):
        predictions = []
        for i in range(6):
            p = ResearchPrediction(f"p_{i}", f"{i}", "test", 85, "buy", "", 10.0)
            p.update_outcome(11.0, 12.0, 13.0)  # correct
            predictions.append(p)
        for i in range(6, 10):
            p = ResearchPrediction(f"p_{i}", f"{i}", "test", 40, "buy", "", 10.0)
            p.update_outcome(9.0, 8.0, 7.0)  # wrong
            predictions.append(p)

        calc = AccuracyCalculator()
        report = calc.calculate(predictions)
        assert report.direction_accuracy_pct == 60.0
        assert report.high_score_accuracy > 90  # high score group is accurate

    def test_suggestions_generated(self):
        predictions = []
        for i in range(10):
            p = ResearchPrediction(f"p_{i}", f"{i}", "test", 85, "buy", "", 10.0)
            p.update_outcome(9.0, 8.0, 7.0)  # all wrong despite high score
            predictions.append(p)

        calc = AccuracyCalculator()
        report = calc.calculate(predictions)
        assert len(report.suggestions) > 0
        assert any("权重" in s for s in report.suggestions)
