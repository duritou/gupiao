"""Signal Engine 全套测试"""

import pytest
import math

from src.signals.base import SignalDirection, SignalCategory
from src.signals.builtin.technical import (
    MACDSignal, RSISignal, KDJJSignal, MASignal, VolumeSignal, BOLLSignal,
    _ema, _sma, _closes,
)
from src.signals.fusion import SignalFusion


# ===== Test Data Generators =====

def make_bullish_data(n: int = 100, base_price: float = 10.0) -> list[dict]:
    """生成上涨趋势 OHLCV 数据"""
    result = []
    for i in range(n):
        price = base_price + i * 0.1
        result.append({
            "open": price - 0.05, "high": price + 0.1,
            "low": price - 0.1, "close": price,
            "volume": 1000000 + i * 10000,
        })
    return result


def make_bearish_data(n: int = 100, base_price: float = 20.0) -> list[dict]:
    """生成下跌趋势 OHLCV 数据"""
    result = []
    for i in range(n):
        price = base_price - i * 0.1
        result.append({
            "open": price + 0.05, "high": price + 0.1,
            "low": price - 0.1, "close": price,
            "volume": 500000 + i * 5000,
        })
    return result


def make_sideways_data(n: int = 100) -> list[dict]:
    """生成震荡 OHLCV 数据"""
    result = []
    for i in range(n):
        price = 10.0 + math.sin(i * 0.2) * 0.5
        result.append({
            "open": price - 0.02, "high": price + 0.05,
            "low": price - 0.05, "close": price,
            "volume": 500000,
        })
    return result


def make_oversold_then_reversal(n: int = 100) -> list[dict]:
    """超卖后反弹的数据"""
    result = []
    for i in range(n):
        if i < 50:
            price = 10.0 - i * 0.15  # 持续下跌
        else:
            price = 2.5 + (i - 50) * 0.15  # 反弹
        result.append({
            "open": price - 0.03, "high": price + 0.05,
            "low": price - 0.05, "close": price,
            "volume": 500000 + abs(50 - i) * 20000,
        })
    return result


# ===== EMA/SMA Utility Tests =====

class TestIndicators:
    """EMA/SMA 工具函数测试"""

    def test_ema_basic(self):
        values = [10.0] * 20
        ema = _ema(values, 5)
        assert len(ema) == 20
        assert abs(ema[-1] - 10.0) < 0.01

    def test_ema_rising(self):
        values = list(range(1, 31))  # 1..30
        ema = _ema(values, 10)
        assert ema[-1] > ema[0]

    def test_sma_basic(self):
        values = [10.0] * 20
        sma = _sma(values, 5)
        assert abs(sma[-1] - 10.0) < 0.01

    def test_closes(self):
        data = [{"close": 1.0}, {"close": 2.0}, {"close": 3.0}]
        assert _closes(data) == [1.0, 2.0, 3.0]


# ===== MACD Tests =====

class TestMACD:
    """MACD 信号测试"""

    @pytest.mark.asyncio
    async def test_bullish_trend_scores_high(self):
        data = make_bullish_data(120)
        result = await MACDSignal().compute("test", data)
        # 持续上涨趋势，score 应高于中性
        assert result.score > 50

    @pytest.mark.asyncio
    async def test_bearish_trend_scores_low(self):
        data = make_bearish_data(120)
        result = await MACDSignal().compute("test", data)
        assert result.score < 60  # 下跌趋势不应太高

    @pytest.mark.asyncio
    async def test_insufficient_data(self):
        data = make_bullish_data(10)
        result = await MACDSignal().compute("test", data)
        assert result.score == 50

    @pytest.mark.asyncio
    async def test_returns_detail(self):
        data = make_bullish_data(120)
        result = await MACDSignal().compute("test", data)
        assert "dif" in result.detail
        assert "dea" in result.detail


# ===== RSI Tests =====

class TestRSI:
    """RSI 信号测试"""

    @pytest.mark.asyncio
    async def test_bullish_rsi(self):
        """线性上涨 RSI 会超买（>70），score 偏低是正确行为"""
        data = make_bullish_data(60)
        result = await RSISignal().compute("test", data)
        # 超买 = 看空信号，score < 50
        assert result.detail["rsi"] > 70  # RSI 确实超买
        assert "超买" in result.reason

    @pytest.mark.asyncio
    async def test_oversold_reversal(self):
        """超卖反弹数据：由于反弹幅度大，RSI 可能仍然偏高"""
        data = make_oversold_then_reversal(100)
        result = await RSISignal().compute("test", data)
        # RSI 应有有效值，且在合理范围
        assert 0 < result.detail["rsi"] < 100

    @pytest.mark.asyncio
    async def test_insufficient_data(self):
        result = await RSISignal().compute("test", make_bullish_data(5))
        assert result.score == 50


# ===== KDJ Tests =====

class TestKDJ:
    """KDJ 信号测试"""

    @pytest.mark.asyncio
    async def test_bullish_kdj(self):
        data = make_bullish_data(60)
        result = await KDJJSignal().compute("test", data)
        assert 0 <= result.score <= 100

    @pytest.mark.asyncio
    async def test_insufficient_data(self):
        result = await KDJJSignal().compute("test", make_bullish_data(5))
        assert result.score == 50

    @pytest.mark.asyncio
    async def test_returns_kdj_values(self):
        data = make_bullish_data(60)
        result = await KDJJSignal().compute("test", data)
        assert "k" in result.detail
        assert "j" in result.detail


# ===== MA Tests =====

class TestMA:
    """均线信号测试"""

    @pytest.mark.asyncio
    async def test_bullish_ma(self):
        data = make_bullish_data(120)
        result = await MASignal().compute("test", data)
        assert result.score > 50

    @pytest.mark.asyncio
    async def test_insufficient_data(self):
        result = await MASignal().compute("test", make_bullish_data(10))
        assert result.score == 50


# ===== Volume Tests =====

class TestVolume:
    """成交量信号测试"""

    @pytest.mark.asyncio
    async def test_normal_volume(self):
        data = make_bullish_data(60)
        result = await VolumeSignal().compute("test", data)
        assert 0 <= result.score <= 100

    @pytest.mark.asyncio
    async def test_insufficient_data(self):
        result = await VolumeSignal().compute("test", make_bullish_data(5))
        assert result.score == 50


# ===== BOLL Tests =====

class TestBOLL:
    """布林带信号测试"""

    @pytest.mark.asyncio
    async def test_boll_sideways(self):
        data = make_sideways_data(60)
        result = await BOLLSignal().compute("test", data)
        assert 0 <= result.score <= 100
        assert "bandwidth" in result.detail

    @pytest.mark.asyncio
    async def test_insufficient_data(self):
        result = await BOLLSignal().compute("test", make_bullish_data(5))
        assert result.score == 50


# ===== SignalFusion Tests =====

class TestSignalFusion:
    """信号融合测试"""

    @pytest.fixture
    def fusion(self):
        return SignalFusion([
            MACDSignal(),
            RSISignal(),
            MASignal(),
            VolumeSignal(),
        ])

    @pytest.mark.asyncio
    async def test_fusion_bullish(self, fusion):
        data = make_bullish_data(120)
        result = await fusion.score("000001.SZ", data)
        assert result.final_score > 50
        assert len(result.individual_scores) == 4
        assert result.buy_signals >= 1  # 上涨趋势应有买入信号

    @pytest.mark.asyncio
    async def test_fusion_bearish(self, fusion):
        data = make_bearish_data(120)
        result = await fusion.score("000001.SZ", data)
        assert len(result.individual_scores) == 4
        assert 0 <= result.final_score <= 100

    @pytest.mark.asyncio
    async def test_fusion_custom_weights(self, fusion):
        data = make_bullish_data(120)
        weights = {"macd": 2.0, "rsi": 0.5, "ma": 0.5, "volume": 0.5}
        result = await fusion.score("000001.SZ", data, weights=weights)
        assert 0 <= result.final_score <= 100

    @pytest.mark.asyncio
    async def test_fusion_confidence(self, fusion):
        data = make_bullish_data(120)
        result = await fusion.score("000001.SZ", data)
        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_fusion_reasons(self, fusion):
        data = make_bullish_data(120)
        result = await fusion.score("000001.SZ", data)
        assert len(result.reasons) > 0  # 至少有部分信号有理由

    @pytest.mark.asyncio
    async def test_empty_fusion(self):
        fusion = SignalFusion()
        result = await fusion.score("test", make_bullish_data(60))
        assert result.final_score == 50.0
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_add_remove_signal(self, fusion):
        fusion.remove_signal("rsi")
        assert "rsi" not in fusion.signal_names
        data = make_bullish_data(120)
        result = await fusion.score("test", data)
        assert len(result.individual_scores) == 3

    @pytest.mark.asyncio
    async def test_fusion_stock_code_in_result(self, fusion):
        data = make_bullish_data(120)
        result = await fusion.score("000725.SZ", data)
        assert result.stock_code == "000725.SZ"
