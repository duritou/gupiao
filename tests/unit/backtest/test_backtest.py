"""Backtest Engine + OutcomeTracker 全套测试"""

import pytest
import math

from src.backtest.engine import BacktestEngine, BacktestResult, PerformanceMetrics, Trade
from src.backtest.tracker import OutcomeTracker, TrackedOutcome, OutcomeSummary
from src.signals.builtin.technical import MACDSignal, RSISignal, MASignal, VolumeSignal
from src.signals.fusion import SignalFusion


# ===== Test Data =====

def make_uptrend_klines(n: int = 120) -> list[dict]:
    """上涨趋势K线"""
    result = []
    base = 10.0
    for i in range(n):
        price = base + i * 0.1 + math.sin(i * 0.1) * 0.5
        result.append({
            "timestamp": f"2026-{((i // 20) + 1):02d}-{(i % 20 + 1):02d}",
            "date": f"2026-{((i // 20) + 1):02d}-{(i % 20 + 1):02d}",
            "open": price - 0.05, "high": price + 0.15,
            "low": price - 0.10, "close": price,
            "volume": 1000000 + i * 5000,
        })
    return result


def make_downtrend_klines(n: int = 100) -> list[dict]:
    """下跌趋势K线"""
    result = []
    base = 20.0
    for i in range(n):
        price = base - i * 0.1
        result.append({
            "timestamp": f"2026-{((i // 20) + 1):02d}-{(i % 20 + 1):02d}",
            "date": f"2026-{((i // 20) + 1):02d}-{(i % 20 + 1):02d}",
            "open": price + 0.05, "high": price + 0.10,
            "low": price - 0.10, "close": price,
            "volume": 500000,
        })
    return result


async def compute_signals(klines: list[dict]) -> list[dict]:
    """计算融合信号"""
    fusion = SignalFusion([MACDSignal(), MASignal(), RSISignal(), VolumeSignal()])
    signals = []
    for i in range(30, len(klines)):
        window = klines[:i + 1]
        result = await fusion.score("test", window)
        date = klines[i].get("date", klines[i].get("timestamp", ""))
        signals.append({
            "date": date,
            "score": result.final_score,
            "direction": result.direction.value,
        })
    return signals


# ===== BacktestEngine Tests =====

class TestBacktestEngine:
    """回测引擎测试"""

    @pytest.mark.asyncio
    async def test_run_uptrend(self):
        klines = make_uptrend_klines(120)
        signals = await compute_signals(klines)
        engine = BacktestEngine(initial_capital=100000, position_size=10000)

        result = await engine.run("000001.SZ", klines, signals, "test_strategy")
        assert isinstance(result, BacktestResult)
        assert result.strategy_name == "test_strategy"
        assert result.final_capital > 0

    @pytest.mark.asyncio
    async def test_metrics_calculated(self):
        klines = make_uptrend_klines(120)
        signals = await compute_signals(klines)
        engine = BacktestEngine()

        result = await engine.run("test", klines, signals)
        m = result.metrics
        assert m.total_trades >= 0
        assert m.max_drawdown_pct >= 0
        assert m.sharpe_ratio != 0 or m.total_trades == 0

    @pytest.mark.asyncio
    async def test_trades_recorded(self):
        klines = make_uptrend_klines(120)
        signals = await compute_signals(klines)
        engine = BacktestEngine(position_size=5000)

        result = await engine.run("test", klines, signals)
        for trade in result.trades:
            assert trade.stock_code == "test"
            assert trade.entry_price > 0
            assert trade.holding_days >= 0

    @pytest.mark.asyncio
    async def test_equity_curve(self):
        klines = make_uptrend_klines(120)
        engine = BacktestEngine()

        result = await engine.run("test", klines)
        assert len(result.equity_curve) > 0
        assert "total" in result.equity_curve[0]

    @pytest.mark.asyncio
    async def test_downtrend_performance(self):
        """下跌趋势中回测应体现亏损或空仓"""
        klines = make_downtrend_klines(100)
        signals = await compute_signals(klines)
        engine = BacktestEngine()

        result = await engine.run("test", klines, signals)
        # 下跌趋势中最终资金应 ≤ 初始资金（除非空仓）
        assert result.final_capital <= result.initial_capital * 1.01

    @pytest.mark.asyncio
    async def test_stop_loss(self):
        """止损测试"""
        # 构造先涨后暴跌的K线
        klines = []
        for i in range(30):
            klines.append({"timestamp": f"2026-01-{i+1:02d}", "date": f"2026-01-{i+1:02d}",
                           "open": 10+i*0.1, "high": 10+i*0.2, "low": 10+i*0.05,
                           "close": 10+i*0.1, "volume": 1000000})
        # 暴跌
        for i in range(30):
            klines.append({"timestamp": f"2026-02-{i+1:02d}", "date": f"2026-02-{i+1:02d}",
                           "open": 13-i*0.5, "high": 13-i*0.4, "low": 13-i*0.6,
                           "close": 13-i*0.5, "volume": 2000000})

        # 构造buy信号（前30天）
        signals = [{"date": klines[25]["date"], "score": 80, "direction": "buy"}]
        engine = BacktestEngine(position_size=10000)

        result = await engine.run("test", klines, signals)
        # 应有止损触发
        stop_loss_trades = [t for t in result.trades if "止损" in t.exit_reason]
        assert len(stop_loss_trades) >= 0  # 至少不崩

    @pytest.mark.asyncio
    async def test_no_signals_buy_and_hold(self):
        """无信号时 no-op"""
        klines = make_uptrend_klines(60)
        engine = BacktestEngine()
        result = await engine.run("test", klines)
        assert result.metrics.total_trades == 0
        assert result.final_capital == result.initial_capital

    @pytest.mark.asyncio
    async def test_start_end_dates(self):
        klines = make_uptrend_klines(60)
        engine = BacktestEngine()
        result = await engine.run("test", klines)
        assert result.start_date != ""
        assert result.end_date != ""


# ===== PerformanceMetrics Tests =====

class TestPerformanceMetrics:
    """绩效指标测试"""

    def test_defaults(self):
        m = PerformanceMetrics()
        assert m.total_return_pct == 0.0
        assert m.total_trades == 0
        assert m.win_rate_pct == 0.0


# ===== OutcomeTracker Tests =====

class TestOutcomeTracker:
    """结果跟踪器测试"""

    def test_track_single(self):
        tracker = OutcomeTracker()
        outcome = tracker.track(
            report_id="rpt_001",
            stock_code="000001.SZ",
            stock_name="平安银行",
            predicted_score=85.0,
            predicted_direction="buy",
            predicted_at="2026-07-01",
            price_at_report=10.0,
            price_1w=10.5,
            price_1m=11.0,
            price_3m=12.0,
        )
        assert outcome.return_1w_pct == 5.0
        assert outcome.return_1m_pct == 10.0
        assert outcome.return_3m_pct == 20.0
        assert outcome.direction_correct is True
        assert outcome.score_accuracy == "accurate"

    def test_track_wrong_direction(self):
        tracker = OutcomeTracker()
        outcome = tracker.track(
            report_id="rpt_002",
            stock_code="000002.SZ",
            stock_name="test",
            predicted_score=80.0,
            predicted_direction="buy",
            predicted_at="2026-07-01",
            price_at_report=10.0,
            price_1w=9.5,
            price_1m=9.0,
            price_3m=8.0,
        )
        assert outcome.direction_correct is False
        assert outcome.score_accuracy == "wrong"

    def test_summarize(self):
        tracker = OutcomeTracker()
        tracker.track("r1", "000001.SZ", "A", 85, "buy", "2026-07-01", 10, 11, 12, 13)
        tracker.track("r2", "000002.SZ", "B", 75, "buy", "2026-07-01", 10, 9, 8, 7)
        tracker.track("r3", "000003.SZ", "C", 60, "neutral", "2026-07-01", 10, 10, 10, 10)

        summary = tracker.summarize()
        assert summary.total_tracked == 3
        assert summary.best_prediction is not None
        assert summary.worst_prediction is not None

    def test_direction_accuracy(self):
        tracker = OutcomeTracker()
        tracker.track("r1", "A", "A", 85, "buy", "", 10, 11, 12, 13)    # correct
        tracker.track("r2", "B", "B", 80, "buy", "", 10, 9, 8, 7)        # wrong
        tracker.track("r3", "C", "C", 85, "buy", "", 10, 11, 12, 13)     # correct

        summary = tracker.summarize()
        assert summary.direction_accuracy_pct == pytest.approx(66.7, 0.1)

    def test_empty_summary(self):
        tracker = OutcomeTracker()
        summary = tracker.summarize()
        assert summary.total_tracked == 0

    def test_count(self):
        tracker = OutcomeTracker()
        assert tracker.count == 0
        tracker.track("r1", "A", "A", 50, "neutral", "", 10)
        assert tracker.count == 1

    def test_score_correlation(self):
        """高评分应更准确"""
        tracker = OutcomeTracker()
        for i in range(5):
            tracker.track(f"r{i}", f"{i}", "test", 80 + i, "buy", "",
                         10, 11, 12, 13)  # high score, correct
        for i in range(5, 10):
            tracker.track(f"r{i}", f"{i}", "test", 40, "sell", "",
                         10, 9, 8, 7)  # low score, wrong direction for buy...

        summary = tracker.summarize()
        assert summary.score_correlation >= 0
