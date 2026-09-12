"""Regression tests for auditable Backtest API responses."""

import asyncio
from datetime import date, timedelta

from src.api.routes import backtest_routes


def _bars(count: int = 45) -> list[dict]:
    start = date.today() - timedelta(days=count - 1)
    return [
        {
            "date": (start + timedelta(days=index)).isoformat(),
            "open": 10 + index * 0.1,
            "high": 10.2 + index * 0.1,
            "low": 9.8 + index * 0.1,
            "close": 10.1 + index * 0.1,
            "volume": 1_000_000 + index,
            "amount": 10_000_000 + index,
        }
        for index in range(count)
    ]


def test_backtest_returns_complete_trade_and_lineage(monkeypatch):
    from src.infrastructure.storage import market_database
    from src.infrastructure.market_data.real_data_provider import real_data
    from src.signals import fusion as fusion_module

    monkeypatch.setattr(
        backtest_routes,
        "get_journal_decisions",
        lambda limit=1: [{
            "id": 42,
            "decision_date": date.today().isoformat(),
            "created_at": f"{date.today().isoformat()}T01:00:00+08:00",
            "stock_code": "000001.SZ",
            "stock_name": "平安银行",
        }],
    )
    monkeypatch.setattr(market_database.market_db, "get_daily_bars", lambda code, limit: _bars(limit))
    monkeypatch.setattr(market_database.market_db, "get_paper_trades", lambda **kwargs: [])

    async def _adjusted_bars(code, days, prefer_remote=False, adjustment_mode=None):
        assert prefer_remote is True
        assert adjustment_mode == "qfq"
        return [dict(bar, adjustment_mode="qfq") for bar in _bars(days)]

    monkeypatch.setattr(real_data, "get_daily_bars", _adjusted_bars)

    class _Signal:
        def __init__(self, direction: str):
            self.final_score = 70.0
            self.direction = type("Direction", (), {"value": direction})()

    class _Fusion:
        def __init__(self, signals):
            self.signals = signals

        async def score(self, code, bars):
            return _Signal("sell" if len(bars) == 44 else "buy")

    monkeypatch.setattr(fusion_module, "SignalFusion", _Fusion)

    result = asyncio.run(backtest_routes.run_backtest("", 45))

    assert result["status"] == "ok"
    assert result["stock_code"] == "000001.SZ"
    assert result["stock_name"] == "平安银行"
    assert result["selection_source"] == "latest_decision_journal"
    assert result["bar_count"] == 45
    assert result["data_quality"]["status"] == "verified"
    assert result["data_quality"]["is_synthetic"] is False
    assert result["data_quality"]["duplicate_dates"] == 0
    assert result["data_quality"]["invalid_ohlc_rows"] == 0
    assert result["data_quality"]["price_adjustment"] == "qfq-required"
    assert len(result["data_quality"]["input_checksum_sha256"]) == 64
    assert result["methodology"]["trust_level"] == "research_only"
    assert result["truth_audit"]["record_type"] == "historical_backtest_simulation"
    assert result["truth_audit"]["is_actual_paper_trading_record"] is False
    assert result["truth_audit"]["paper_ledger_trade_count_for_symbol_period"] == 0
    assert result["truth_audit"]["selection_decision_id"] == 42
    assert result["truth_audit"]["causality_status"] == "retrospective_selection_after_entry"
    assert result["trades"]
    trade = result["trades"][0]
    for key in (
        "record_type", "is_actual_paper_trade", "actual_paper_buy_match",
        "actual_paper_sell_match", "actual_paper_round_trip_match",
        "selection_decision_created_at", "signal_date", "simulated_at",
        "entry_signal_date", "exit_signal_date",
        "trade_provenance", "entry_date_type", "exit_date_type",
        "causality_status", "entry_execution_basis", "exit_execution_basis",
        "stock_code", "stock_name", "entry_date", "exit_date",
        "entry_price", "exit_price", "quantity", "entry_amount",
        "exit_amount", "buy_fee", "sell_commission", "stamp_tax",
        "total_fees", "profit_pct", "profit_amount", "entry_signal_score",
    ):
        assert key in trade
    assert trade["is_actual_paper_trade"] is False
    assert trade["trade_provenance"] == "historical_bars_replayed_now"
    assert trade["entry_date_type"] == "simulated_execution_date"
    assert trade["exit_date_type"] == "simulated_execution_date"
    assert trade["actual_paper_round_trip_match"] is False
    assert trade["causality_status"] == "retrospective_selection_after_entry"
    assert trade["entry_execution_basis"] == "next_session_open_plus_adverse_slippage"
    assert trade["exit_execution_basis"] == "next_session_open_minus_adverse_slippage"
    assert result["methodology"]["t_plus_one_sell"] is True
    assert result["methodology"]["slippage"] == 0.001
    assert "模拟执行日期" in result["truth_audit"]["plain_language"]
    assert result["truth_audit"]["trade_provenance"] == "historical_bars_replayed_now"


def test_bar_quality_flags_duplicates_and_invalid_ohlc():
    bars = _bars(40)
    bars.append(dict(bars[-1]))
    bars[0]["high"] = 1

    quality = backtest_routes._assess_bars(bars, 40, "local_market_database")

    assert quality["status"] == "warning"
    assert quality["integrity_passed"] is False
    assert quality["duplicate_dates"] == 1
    assert quality["invalid_ohlc_rows"] == 1
