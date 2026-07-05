"""Golden Dataset — 已知正确答案的信号测试用例

每个案例: 输入K线数据 → 预期信号方向和评分范围
用于 CI 验证信号引擎不被意外修改。
"""

from src.evaluation.engine import SignalGoldenCase

# MACD 金叉 K线: 先跌后涨
MACD_GOLDEN_CROSS_KLINES = [
    {"open": 20 - i * 0.05, "high": 20 - i * 0.03, "low": 20 - i * 0.08,
     "close": 20 - i * 0.05, "volume": 1000000}
    for i in range(30)
] + [
    {"open": 18.5 + i * 0.08, "high": 18.5 + i * 0.12, "low": 18.5 + i * 0.05,
     "close": 18.5 + i * 0.1, "volume": 1500000 + i * 10000}
    for i in range(40)
]

# 持续下跌 K线
BEARISH_KLINES = [
    {"open": 20 - i * 0.08, "high": 20 - i * 0.05, "low": 20 - i * 0.12,
     "close": 20 - i * 0.08, "volume": 800000}
    for i in range(60)
]

# 横盘震荡 K线
SIDEWAYS_KLINES = [
    {"open": 10 + (i % 10 - 5) * 0.05, "high": 10 + (i % 10 - 5) * 0.08,
     "low": 10 + (i % 10 - 5) * 0.02, "close": 10 + (i % 10 - 4) * 0.03,
     "volume": 500000}
    for i in range(60)
]

GOLDEN_CASES = [
    SignalGoldenCase(
        name="macd_bullish_trend",
        stock_code="GOLDEN001.SZ",
        kline_data=MACD_GOLDEN_CROSS_KLINES,
        expected_signal="buy",
        expected_score_min=45,
        expected_score_max=95,
        tolerance=15,  # 允许方向为 neutral（边界情况）
    ),
    SignalGoldenCase(
        name="rsi_bearish_trend",
        stock_code="GOLDEN002.SZ",
        kline_data=BEARISH_KLINES,
        expected_signal="buy",       # 持续下跌 → RSI超卖 → 看多信号
        expected_score_min=55,
        expected_score_max=95,
        tolerance=10,
    ),
    SignalGoldenCase(
        name="ma_bearish_trend",
        stock_code="GOLDEN003.SZ",
        kline_data=BEARISH_KLINES,
        expected_signal="sell",
        expected_score_min=20,
        expected_score_max=55,
        tolerance=10,
    ),
]
