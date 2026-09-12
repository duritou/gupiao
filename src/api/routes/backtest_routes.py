"""Auditable single-stock backtests backed by real daily bars."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

from fastapi import APIRouter, Query

from src.ai_os.trading_costs import FEE_POLICY
from src.api.routes.journal_utils import (
    get_journal_decisions,
    latest_decision_for_code,
    stock_name_from_journal,
)

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
        "avg_win_pct": 0,
        "avg_loss_pct": 0,
        "profit_factor": 0,
    }


def _assess_bars(bars: list[dict], requested_days: int, source_mode: str) -> dict:
    """Return inspectable integrity, freshness, and lineage evidence."""
    dates: list[str] = []
    invalid_rows = 0
    canonical_rows = []
    for bar in bars:
        bar_date = str(bar.get("date") or bar.get("timestamp") or "")[:10]
        try:
            open_price = float(bar.get("open") or 0)
            high = float(bar.get("high") or 0)
            low = float(bar.get("low") or 0)
            close = float(bar.get("close") or 0)
            volume = float(bar.get("volume") or 0)
            amount = float(bar.get("amount") or 0)
        except (TypeError, ValueError):
            invalid_rows += 1
            continue
        valid_ohlc = (
            bool(bar_date)
            and min(open_price, high, low, close) > 0
            and high >= max(open_price, close, low)
            and low <= min(open_price, close, high)
            and volume >= 0
        )
        if not valid_ohlc:
            invalid_rows += 1
        dates.append(bar_date)
        canonical_rows.append([bar_date, open_price, high, low, close, volume, amount])

    unique_dates = set(dates)
    duplicate_dates = len(dates) - len(unique_dates)
    first_date = min(unique_dates) if unique_dates else ""
    last_date = max(unique_dates) if unique_dates else ""
    freshness_days = None
    if last_date:
        try:
            freshness_days = (date.today() - date.fromisoformat(last_date)).days
        except ValueError:
            invalid_rows += 1
    integrity_passed = bool(bars) and invalid_rows == 0 and duplicate_dates == 0
    freshness_state = (
        "current" if freshness_days is not None and 0 <= freshness_days <= 5
        else "future" if freshness_days is not None and freshness_days < 0
        else "stale"
    )
    checksum = hashlib.sha256(
        json.dumps(canonical_rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    local_source = source_mode == "local_market_database"
    return {
        "status": "verified" if integrity_passed and freshness_state == "current" else "warning",
        "is_synthetic": False,
        "integrity_passed": integrity_passed,
        "source_mode": source_mode,
        "source_table": "market_daily" if local_source else "real_data_provider",
        "upstream_source": "baostock daily synchronization" if local_source else "provider manager",
        "requested_days": requested_days,
        "bar_count": len(bars),
        "first_date": first_date,
        "last_date": last_date,
        "freshness_days": freshness_days,
        "freshness_state": freshness_state,
        "duplicate_dates": duplicate_dates,
        "invalid_ohlc_rows": invalid_rows,
        "price_adjustment": "none (baostock adjustflag=3)" if local_source else "qfq-required",
        "input_checksum_sha256": checksum,
        "verified_at": datetime.now().astimezone().isoformat(),
    }


@router.post("/run")
async def run_backtest(
    code: str = Query("", description="Stock code; defaults to top journal decision"),
    days: int = Query(120, ge=40, le=500),
):
    """Run a reproducible technical backtest on real historical daily bars."""
    from src.backtest.engine import BacktestEngine
    from src.infrastructure.market_data.real_data_provider import real_data
    from src.infrastructure.storage.market_database import market_db
    from src.signals.builtin.technical import MACDSignal, MASignal, RSISignal, VolumeSignal
    from src.signals.fusion import SignalFusion

    selection_source = "explicit_code"
    selection_decision: dict = {}
    selected_name = ""
    if not code:
        decisions = get_journal_decisions(limit=1)
        selection_decision = decisions[0] if decisions else {}
        code = str(selection_decision.get("stock_code") or "")
        selected_name = str(selection_decision.get("stock_name") or "")
        selection_source = "latest_decision_journal"
    code = code.strip().upper()
    if not code:
        return {
            "status": "no_data",
            "data_source": "decision_journal + local_market_database",
            "message": "No journal decision is available to choose a backtest stock.",
            "period": "",
            "metrics": _empty_metrics(),
            "trades": [],
        }

    if not selection_decision:
        selection_decision = latest_decision_for_code(code) or {}
    selected_name = selected_name or stock_name_from_journal(code)
    bars = await real_data.get_daily_bars(
        code, days=days, prefer_remote=True, adjustment_mode="qfq",
    ) or []
    source_mode = "real_data_provider_qfq"
    data_quality = _assess_bars(bars, days, source_mode)
    if len(bars) < 40:
        return {
            "status": "insufficient_data",
            "stock_code": code,
            "stock_name": selected_name,
            "data_days": len(bars),
            "data_source": source_mode,
            "data_quality": data_quality,
            "period": "",
            "metrics": _empty_metrics(),
            "trades": [],
        }

    fusion = SignalFusion([MACDSignal(), RSISignal(), MASignal(), VolumeSignal()])
    signals = []
    for i in range(30, len(bars)):
        result = await fusion.score(code, bars[: i + 1])
        signals.append({
            "date": bars[i].get("date") or bars[i].get("timestamp"),
            "score": result.final_score,
            "direction": result.direction.value,
        })

    engine = BacktestEngine(initial_capital=100000, position_size=10000)
    result = await engine.run(code, bars, signals)
    metrics = result.metrics
    generated_at = datetime.now().astimezone().isoformat()
    selection_decision_date = str(selection_decision.get("decision_date") or "")
    selection_decision_created_at = str(selection_decision.get("created_at") or "")
    paper_ledger_trades = market_db.get_paper_trades(
        limit=500,
        stock_code=code,
        date_from=result.start_date,
        date_to=result.end_date,
    )

    def _paper_match(action: str, trade_date: str) -> dict:
        return next(
            (
                item for item in paper_ledger_trades
                if str(item.get("action") or "").upper() == action
                and str(item.get("trade_date") or "") == trade_date
            ),
            {},
        )

    trade_rows = []
    matched_ledger_legs = 0
    retrospective_entries = 0
    for trade in result.trades:
        paper_buy = _paper_match("BUY", trade.entry_date)
        paper_sell = _paper_match("SELL", trade.exit_date)
        matched_ledger_legs += int(bool(paper_buy)) + int(bool(paper_sell))
        selection_after_entry = bool(
            selection_decision_date
            and trade.entry_date
            and selection_decision_date > trade.entry_date
        )
        retrospective_entries += int(selection_after_entry)
        trade_rows.append({
            "record_type": "historical_backtest_simulation",
            "is_actual_paper_trade": False,
            "actual_paper_buy_match": bool(paper_buy),
            "actual_paper_sell_match": bool(paper_sell),
            "actual_paper_round_trip_match": bool(paper_buy and paper_sell),
            "paper_buy_trade_id": paper_buy.get("id"),
            "paper_sell_trade_id": paper_sell.get("id"),
            "selection_decision_date": selection_decision_date,
            "selection_decision_created_at": selection_decision_created_at,
            "signal_date": trade.entry_signal_date,
            "entry_signal_date": trade.entry_signal_date,
            "exit_signal_date": trade.exit_signal_date,
            "signal_time_granularity": "daily_close_date_only",
            "simulated_at": generated_at,
            "trade_provenance": "historical_bars_replayed_now",
            "entry_date_type": "simulated_execution_date",
            "exit_date_type": "simulated_execution_date",
            "causality_status": (
                "retrospective_selection_after_entry"
                if selection_after_entry
                else "historical_backtest_not_live_fill"
            ),
            "entry_execution_basis": "next_session_open_plus_adverse_slippage",
            "exit_execution_basis": "next_session_open_minus_adverse_slippage",
            "final_bar_exit_execution_basis": "final_bar_close_minus_adverse_slippage",
            "stock_code": trade.stock_code,
            "stock_name": selected_name,
            "entry_date": trade.entry_date,
            "exit_date": trade.exit_date,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "quantity": trade.quantity,
            "entry_amount": trade.entry_amount,
            "exit_amount": trade.exit_amount,
            "buy_fee": trade.buy_fee,
            "sell_commission": trade.sell_commission,
            "stamp_tax": trade.stamp_tax,
            "total_fees": trade.total_fees,
            "gross_profit_pct": trade.gross_profit_pct,
            "profit_pct": trade.profit_pct,
            "profit_amount": trade.profit_amount,
            "holding_days": trade.holding_days,
            "entry_signal_score": trade.signal_score,
            "exit_reason": trade.exit_reason,
        })

    truth_audit = {
        "record_type": "historical_backtest_simulation",
        "is_actual_paper_trading_record": False,
        "paper_ledger_trade_count_for_symbol_period": len(paper_ledger_trades),
        "matched_paper_ledger_legs": matched_ledger_legs,
        "selection_source": selection_source,
        "selection_decision_id": selection_decision.get("id"),
        "selection_decision_date": selection_decision_date,
        "selection_decision_created_at": selection_decision_created_at,
        "backtest_generated_at": generated_at,
        "retrospective_entry_count": retrospective_entries,
        "causality_status": (
            "retrospective_selection_after_entry"
            if retrospective_entries
            else "historical_backtest_not_live_fill"
        ),
        "plain_language": (
            "本页成交由回测运行时使用历史K线事后模拟；买入/卖出日期是模拟执行日期，"
            "不是当时写入纸面交易账本的真实成交日期。"
        ),
        "trade_provenance": "historical_bars_replayed_now",
    }
    return {
        "status": "ok",
        "strategy": result.strategy_name,
        "stock_code": code,
        "stock_name": selected_name,
        "selection_source": selection_source,
        "period": f"{result.start_date} ~ {result.end_date}",
        "bar_count": len(bars),
        "signal_count": len(signals),
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
            "avg_win_pct": metrics.avg_win_pct,
            "avg_loss_pct": metrics.avg_loss_pct,
            "profit_factor": metrics.profit_factor,
        },
        "trades": trade_rows,
        "order_rejections": [
            {
                "stock_code": item.stock_code,
                "action": item.action,
                "signal_date": item.signal_date,
                "intended_execution_date": item.intended_execution_date,
                "reason": item.reason,
            }
            for item in result.order_rejections
        ],
        "equity_curve": result.equity_curve,
        "data_source": f"{source_mode} + signal_fusion",
        "data_quality": data_quality,
        "truth_audit": truth_audit,
        "methodology": {
            "scope": "single_stock",
            "selection": selection_source,
            "signals": ["MACD", "RSI", "MA", "Volume"],
            "buy_rule": "direction=buy and score>=60",
            "sell_rule": "direction=sell and score>=60, close stop-loss -8%, or final-day close",
            "execution_price": "next-session open with 10bp adverse slippage",
            "position_size": 10000,
            "fee_policy": FEE_POLICY,
            "slippage": 0.001,
            "board_lot": 100,
            "t_plus_one_sell": True,
            "blocked_fills": ["suspension", "zero volume", "one-price limit up/down"],
            "limitations": [
                "single-symbol backtest, not the full AI portfolio",
                "daily bars cannot model intraday queue priority or partial fills",
                "slippage is a fixed research assumption rather than an order-book estimate",
                "unadjusted prices may be distorted by corporate actions",
            ],
            "trust_level": "research_only",
        },
        "generated_at": generated_at,
    }
