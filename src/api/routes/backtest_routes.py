"""Backtest routes using real daily bars."""

from fastapi import APIRouter, Query

from src.api.routes.journal_utils import get_journal_decisions

router = APIRouter(tags=["backtest"], prefix="/backtest")


def _empty_metrics() -> dict:
    return {
        "total_return_pct": 0,
        "annual_return_pct": 0,
        "max_drawdown_pct": 0,
        "sharpe_ratio": 0,
        "win_rate_pct": 0,
        "total_trades": 0,
        "winning": 0,
        "losing": 0,
    }


@router.post("/run")
async def run_backtest(
    code: str = Query("", description="Stock code; defaults to top journal decision"),
    days: int = Query(120, ge=40, le=500),
):
    """Run a backtest on real historical daily bars."""
    from src.backtest.engine import BacktestEngine
    from src.infrastructure.market_data.real_data_provider import real_data
    from src.signals.builtin.technical import MACDSignal, MASignal, RSISignal, VolumeSignal
    from src.signals.fusion import SignalFusion

    if not code:
        decisions = get_journal_decisions(limit=1)
        code = str(decisions[0].get("stock_code") or "") if decisions else ""
    if not code:
        return {
            "status": "no_data",
            "data_source": "decision_journal + real_data_provider",
            "message": "No journal decision is available to choose a backtest stock.",
            "period": "",
            "metrics": _empty_metrics(),
            "trades": [],
        }

    bars = await real_data.get_daily_bars(code, days=days)
    if not bars or len(bars) < 40:
        return {
            "status": "insufficient_data",
            "stock_code": code,
            "data_days": len(bars) if bars else 0,
            "data_source": "real_data_provider",
            "period": "",
            "metrics": _empty_metrics(),
            "trades": [],
        }

    fusion = SignalFusion([MACDSignal(), RSISignal(), MASignal(), VolumeSignal()])
    signals = []
    for i in range(30, len(bars)):
        window = bars[: i + 1]
        result = await fusion.score(code, window)
        signals.append(
            {
                "date": bars[i].get("date") or bars[i].get("timestamp"),
                "score": result.final_score,
                "direction": result.direction.value,
            }
        )

    engine = BacktestEngine(initial_capital=100000, position_size=10000)
    result = await engine.run(code, bars, signals)
    metrics = result.metrics
    return {
        "status": "ok",
        "strategy": result.strategy_name,
        "stock_code": code,
        "period": f"{result.start_date} ~ {result.end_date}",
        "initial_capital": result.initial_capital,
        "final_capital": result.final_capital,
        "metrics": {
            "total_return_pct": metrics.total_return_pct,
            "annual_return_pct": metrics.annual_return_pct,
            "max_drawdown_pct": metrics.max_drawdown_pct,
            "sharpe_ratio": metrics.sharpe_ratio,
            "win_rate_pct": metrics.win_rate_pct,
            "total_trades": metrics.total_trades,
            "winning": metrics.winning_trades,
            "losing": metrics.losing_trades,
        },
        "trades": [
            {
                "entry": t.entry_date,
                "exit": t.exit_date,
                "profit_pct": t.profit_pct,
                "holding_days": t.holding_days,
                "exit_reason": t.exit_reason,
            }
            for t in result.trades[:10]
        ],
        "data_source": "real_data_provider + signal_fusion",
    }
