import json

import pytest

from src.ai_os.trading_costs import (
    FEE_POLICY,
    calculate_trade_costs,
    quantize_price,
)
from src.ai_os.trading_policy import position_exit_reason
from src.infrastructure.storage.market_database import MarketDatabase


def test_trade_cost_policy_charges_both_side_commission_and_sell_stamp_tax():
    assert calculate_trade_costs(20_000, "BUY") == {
        "commission": 10.0,
        "stamp_tax": 0.0,
        "total_fees": 10.0,
    }
    assert calculate_trade_costs(20_000, "SELL") == {
        "commission": 10.0,
        "stamp_tax": 10.0,
        "total_fees": 20.0,
    }


def test_price_and_cost_policy_is_tick_rounded_and_supports_shared_rates():
    assert quantize_price(10.004) == 10.0
    assert quantize_price(10.005) == 10.01
    assert calculate_trade_costs(
        10_000,
        "SELL",
        commission_rate=0.001,
        stamp_tax_rate=0.002,
    ) == {
        "commission": 10.0,
        "stamp_tax": 20.0,
        "total_fees": 30.0,
    }


def test_fee_migration_archives_old_policy_and_backfills_signal_time(tmp_path):
    database = MarketDatabase(tmp_path / "fees.db")
    database.ensure_paper_account(100_000)
    with database._get_conn() as connection:
        connection.execute(
            "UPDATE paper_account SET cash=79994, fee_policy='legacy' WHERE id=1"
        )
        connection.execute(
            """INSERT INTO paper_trade(
                   trade_date, action, stock_code, stock_name, shares, price,
                   value, reason, created_at, fee, legacy_trade_id
               ) VALUES (
                   '2026-08-12', 'BUY', '000001.SZ', 'test', 2000, 10,
                   20000, 'legacy', '2026-08-12T09:30:00+08:00', 6, 7
               )"""
        )
        connection.execute(
            """INSERT INTO paper_portfolio_snapshot(
                   snapshot_date, cash, market_value, total_value, created_at,
                   updated_at
               ) VALUES (
                   '2026-08-13', 79994, 20000, 99994, '', ''
               )"""
        )
        connection.execute(
            """INSERT INTO paper_ledger_archive(
                   archived_at, reason, payload_json, rebuilt_summary_json
               ) VALUES (?, 'legacy seed', ?, '{}')""",
            (
                "2026-08-13T00:00:00",
                json.dumps({
                    "paper_trade": [{
                        "id": 7,
                        "created_at": "2026-08-11T20:30:00+08:00",
                    }],
                }),
            ),
        )

    result = database.apply_paper_fee_policy()
    portfolio = database.get_paper_portfolio("2026-08-13")
    trade = database.get_paper_trades()[0]
    with database._get_conn() as connection:
        snapshot = dict(connection.execute(
            "SELECT * FROM paper_portfolio_snapshot WHERE snapshot_date='2026-08-13'"
        ).fetchone())

    assert result["status"] == "applied"
    assert result["archive_id"] == 2
    assert result["cash_adjustment"] == -4.0
    assert portfolio["cash"] == pytest.approx(79_990)
    assert snapshot["cash"] == pytest.approx(79_990)
    assert snapshot["total_value"] == pytest.approx(99_990)
    assert portfolio["fee_policy"] == FEE_POLICY
    assert trade["commission"] == 10.0
    assert trade["stamp_tax"] == 0.0
    assert trade["total_fees"] == 10.0
    assert trade["net_cash_flow"] == -20_010.0
    assert trade["signal_at"] == "2026-08-11T20:30:00+08:00"
    assert trade["signal_time_type"] == "strategy_signal_only_not_an_order_or_fill"
    assert trade["execution_at"] == "2026-08-12T09:30:00+08:00"


def test_paper_sell_records_commission_stamp_tax_and_execution_time(tmp_path):
    database = MarketDatabase(tmp_path / "sell.db")
    database.ensure_paper_account(100_000)
    with database._get_conn() as connection:
        connection.execute("UPDATE paper_account SET cash=50000 WHERE id=1")
        connection.execute(
            """INSERT INTO paper_position(
                   stock_code, stock_name, shares, avg_cost, updated_at,
                   entry_date, eligible_sell_date
               ) VALUES (
                   '000001.SZ', 'sell-test', 1000, 8, '',
                   '2026-08-01', '2026-08-01'
               )"""
        )

    result = database.run_paper_strategy(
        [{
            "date": "2026-08-13",
            "data_cutoff_at": "2026-08-13T14:28:59+08:00",
            "signal_at": "2026-08-13T14:29:00+08:00",
            "stock_code": "000001.SZ",
            "stock_name": "sell-test",
            "ai_score": 30,
            "direction": "sell",
            "market_price": 10.0,
            "market_price_date": "2026-08-13",
            "market_price_source": "tencent_live_quote",
            "market_price_exchange_at": "2026-08-13T14:29:02+08:00",
            "market_price_fetched_at": "2026-08-13T14:29:03+08:00",
        }],
        "2026-08-13",
        execution_timestamp="2026-08-13T14:29:03+08:00",
        trading_day_verified=True,
        is_trading_day=True,
    )
    trade = database.get_paper_trades()[0]

    assert result["actions"][0]["commission"] == 5.0
    assert result["actions"][0]["stamp_tax"] == 5.0
    assert trade["total_fees"] == 10.0
    assert trade["signal_at"] == "2026-08-13T14:29:00+08:00"
    assert trade["execution_at"] == "2026-08-13T14:29:03+08:00"
    assert trade["quote_exchange_at"] == "2026-08-13T14:29:02+08:00"
    assert trade["quote_fetched_at"] == "2026-08-13T14:29:03+08:00"
    assert trade["causality_status"] == "verified_post_signal_quote"


def _held_position() -> dict:
    return {"avg_cost": 10.0, "entry_date": "2026-08-01"}


def test_neutral_position_exits_after_five_days_when_score_is_weak():
    reason = position_exit_reason(
        _held_position(),
        {"ai_score": 54, "direction": "neutral"},
        current_price=10.5,
        holding_days=5,
    )

    assert reason == "neutral_timeout=5d;score=54.0<55"


def test_neutral_position_locks_profit_without_deep_buy_support():
    reason = position_exit_reason(
        _held_position(),
        {"ai_score": 50, "direction": "neutral"},
        current_price=11.2,
        holding_days=1,
    )

    assert reason == "neutral_profit_lock=12%;return=12.0%"


def test_profit_retrace_protection_exits_profitable_neutral_position():
    reason = position_exit_reason(
        _held_position(),
        {"ai_score": 52, "direction": "neutral"},
        current_price=13.0,
        holding_days=3,
        high_price=15.0,
    )

    assert reason == "profit_retrace_protection=8%;return=30.0%"


def test_deep_buy_support_is_not_forced_out_by_neutral_exit_rules():
    reason = position_exit_reason(
        _held_position(),
        {
            "ai_score": 75,
            "direction": "buy",
            "deep_rating": "Buy",
        },
        current_price=20.0,
        holding_days=19,
        high_price=25.0,
    )

    assert reason == ""


def test_exit_rules_fail_closed_when_price_or_cost_is_missing():
    assert position_exit_reason(
        {"avg_cost": 0},
        {"ai_score": 20, "direction": "sell"},
        current_price=10,
        holding_days=20,
    ) == ""


def test_paper_strategy_executes_neutral_timeout_exit(tmp_path):
    database = MarketDatabase(tmp_path / "neutral-timeout.db")
    database.ensure_paper_account(100_000)
    with database._get_conn() as connection:
        connection.execute("UPDATE paper_account SET cash=90000 WHERE id=1")
        connection.execute(
            """INSERT INTO paper_position(
                   stock_code, stock_name, shares, avg_cost, updated_at,
                   entry_date, eligible_sell_date
               ) VALUES (
                   '000001.SZ', 'neutral-timeout', 1000, 10, '',
                   '2026-08-01', '2026-08-01'
               )"""
        )
        for day in (
            "2026-08-04", "2026-08-05", "2026-08-06",
            "2026-08-07", "2026-08-08",
        ):
            connection.execute(
                "INSERT INTO market_daily(ts_code, trade_date) VALUES (?, ?)",
                ("000001.SZ", day),
            )

    result = database.run_paper_strategy(
        [{
            "date": "2026-08-08",
            "stock_code": "000001.SZ",
            "stock_name": "neutral-timeout",
            "ai_score": 54,
            "direction": "neutral",
            "market_price": 10.5,
            "market_change_pct": 0,
        }],
        "2026-08-08",
        strict_real_data=False,
    )

    assert result["actions"][0]["action"] == "SELL"
    assert result["actions"][0]["reason"] == "neutral_timeout=5d;score=54.0<55"
    assert database.get_paper_portfolio("2026-08-08")["positions"] == []
    assert position_exit_reason(
        _held_position(),
        {"ai_score": 20, "direction": "sell"},
        current_price=0,
        holding_days=20,
    ) == ""
