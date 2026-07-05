"""Backtest routes"""

import math
from fastapi import APIRouter, Query

router = APIRouter(tags=["backtest"], prefix="/backtest")


@router.post("/run")
async def run_backtest(
    trend: str = Query("up", description="up/down — 趋势方向"),
    days: int = Query(120),
):
    """运行回测"""
    from src.backtest.engine import BacktestEngine
    from src.signals.fusion import SignalFusion
    from src.signals.builtin.technical import MACDSignal, RSISignal, MASignal, VolumeSignal

    # 构造历史K线
    klines = []
    for i in range(days):
        if trend == "up":
            p = 10.0 + i * 0.08 + math.sin(i * 0.1) * 0.5
        else:
            p = 20.0 - i * 0.08 + math.sin(i * 0.1) * 0.5
        klines.append({
            "date": f"2026-{((i // 20) + 1):02d}-{(i % 20 + 1):02d}",
            "timestamp": f"2026-{((i // 20) + 1):02d}-{(i % 20 + 1):02d}",
            "close": p, "open": p - 0.03, "high": p + 0.06, "low": p - 0.04,
            "volume": 1000000 + i * 5000,
        })

    # 计算信号
    fusion = SignalFusion([MACDSignal(), RSISignal(), MASignal(), VolumeSignal()])
    signals = []
    for i in range(30, len(klines)):
        window = klines[:i + 1]
        result = await fusion.score("test", window)
        signals.append({
            "date": klines[i]["date"],
            "score": result.final_score,
            "direction": result.direction.value,
        })

    # 运行回测
    engine = BacktestEngine(initial_capital=100000, position_size=10000)
    result = await engine.run("backtest", klines, signals)

    m = result.metrics
    return {
        "strategy": result.strategy_name,
        "period": f"{result.start_date} ~ {result.end_date}",
        "initial_capital": result.initial_capital,
        "final_capital": result.final_capital,
        "metrics": {
            "total_return_pct": m.total_return_pct,
            "annual_return_pct": m.annual_return_pct,
            "max_drawdown_pct": m.max_drawdown_pct,
            "sharpe_ratio": m.sharpe_ratio,
            "win_rate_pct": m.win_rate_pct,
            "total_trades": m.total_trades,
            "winning": m.winning_trades,
            "losing": m.losing_trades,
        },
        "trades": [
            {"entry": t.entry_date, "exit": t.exit_date,
             "profit_pct": t.profit_pct, "holding_days": t.holding_days,
             "exit_reason": t.exit_reason}
            for t in result.trades[:10]
        ],
    }
