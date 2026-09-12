"""Regression tests for point-in-time A-share backtest execution."""

import pytest

from src.backtest.engine import BacktestEngine


def _bar(date: str, price: float, **overrides) -> dict:
    bar = {
        "date": date,
        "open": price,
        "high": price + 0.1,
        "low": price - 0.1,
        "close": price,
        "volume": 100_000,
    }
    bar.update(overrides)
    return bar


@pytest.mark.asyncio
async def test_close_signal_fills_at_next_open_and_sell_obeys_t_plus_one():
    bars = [
        _bar("2026-08-20", 10.0),
        _bar("2026-08-21", 10.2),
        _bar("2026-08-24", 10.5),
    ]
    signals = [
        {"date": "2026-08-20", "score": 80, "direction": "buy"},
        {"date": "2026-08-21", "score": 80, "direction": "sell"},
    ]

    result = await BacktestEngine(slippage_rate=0).run("000001.SZ", bars, signals)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_signal_date == "2026-08-20"
    assert trade.entry_date == "2026-08-21"
    assert trade.exit_signal_date == "2026-08-21"
    assert trade.exit_date == "2026-08-24"
    assert trade.holding_days == 1
    assert trade.quantity % 100 == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("blocked_bar", "reason"),
    [
        (_bar("2026-08-21", 10.0, volume=0), "zero_volume"),
        (
            _bar("2026-08-21", 11.0, high=11.0, low=11.0, close=11.0),
            "one_price_limit_up",
        ),
        (_bar("2026-08-21", 10.0, is_suspended=True), "suspended"),
    ],
)
async def test_untradable_next_bar_records_rejection(blocked_bar: dict, reason: str):
    bars = [_bar("2026-08-20", 10.0), blocked_bar, _bar("2026-08-24", 10.2)]
    signals = [{"date": "2026-08-20", "score": 80, "direction": "buy"}]

    result = await BacktestEngine().run("000001.SZ", bars, signals)

    assert len(result.trades) == 1
    assert len(result.order_rejections) == 1
    assert result.order_rejections[0].reason == reason
    assert result.order_rejections[0].signal_date == "2026-08-20"
    assert result.order_rejections[0].intended_execution_date == "2026-08-21"


@pytest.mark.asyncio
async def test_adverse_slippage_applies_to_both_sides():
    bars = [
        _bar("2026-08-20", 10.0),
        _bar("2026-08-21", 10.0),
        _bar("2026-08-24", 11.0),
    ]
    signals = [
        {"date": "2026-08-20", "score": 80, "direction": "buy"},
        {"date": "2026-08-21", "score": 80, "direction": "sell"},
    ]

    result = await BacktestEngine(slippage_rate=0.001).run("000001.SZ", bars, signals)

    trade = result.trades[0]
    assert trade.entry_price == pytest.approx(10.01)
    assert trade.exit_price == pytest.approx(10.99)


@pytest.mark.asyncio
async def test_limit_down_sell_order_remains_pending_until_a_later_session():
    bars = [
        _bar("2026-08-20", 10.0),
        _bar("2026-08-21", 10.0),
        _bar("2026-08-24", 9.0, high=9.0, low=9.0, close=9.0),
        _bar("2026-08-25", 9.2),
    ]
    signals = [
        {"date": "2026-08-20", "score": 80, "direction": "buy"},
        {"date": "2026-08-21", "score": 80, "direction": "sell"},
    ]

    result = await BacktestEngine(slippage_rate=0).run("000001.SZ", bars, signals)

    assert len(result.trades) == 1
    assert result.trades[0].exit_date == "2026-08-25"
    assert any(
        rejection.reason == "one_price_limit_down"
        for rejection in result.order_rejections
    )


@pytest.mark.asyncio
async def test_buy_only_signal_remains_open_and_is_marked_to_market():
    bars = [
        _bar("2026-08-20", 10.0),
        _bar("2026-08-21", 10.2),
        _bar("2026-08-24", 10.5),
    ]
    signals = [{"date": "2026-08-20", "score": 80, "direction": "buy"}]

    result = await BacktestEngine(slippage_rate=0).run("000001.SZ", bars, signals)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_date == "2026-08-21"
    assert trade.exit_date == "2026-08-24"
    assert trade.exit_reason == "回测结束平仓"
    assert result.equity_curve[-1]["position_value"] == 0
    assert result.final_capital == result.equity_curve[-1]["total"]
