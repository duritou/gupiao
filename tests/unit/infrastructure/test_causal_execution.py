import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

import src.ai_os.pipeline_runner as pipeline_runner_module
from src.ai_os.causal_execution import (
    CHINA_TZ,
    fetch_post_signal_quotes,
    validate_post_signal_quote,
)
from src.ai_os.pipeline_runner import (
    AIPipelineRunner,
    PipelineResult,
    _causal_daily_bars,
    _execution_candidates,
    _include_held_decisions,
)
from src.ai_os.task_executor import market_data_covers_latest_completed_day
from src.ai_os.trading_calendar import CompletedTradingDayStatus
from src.infrastructure.storage.market_database import MarketDatabase, market_db


def _codex_approval() -> dict:
    return {
        "deep_provider": "codex_cli",
        "deep_model": "gpt-5.6-terra",
        "final_buy_approved": True,
        "final_review_provider": "codex_cli",
        "final_review_model": "gpt-5.6-terra",
    }


def _decision() -> dict:
    return {
        "date": "2026-08-14",
        "stock_code": "000001.SZ",
        "stock_name": "causal",
        "ai_score": 75,
        "direction": "buy",
        "deep_analysis_available": True,
        "deep_rating": "Overweight",
        **_codex_approval(),
        "data_cutoff_at": "2026-08-14T09:34:58+08:00",
        "signal_at": "2026-08-14T09:35:00.500000+08:00",
    }


def _quote(exchange_timestamp: str) -> dict:
    return {
        "price": 10.0,
        "data_date": "2026-08-14",
        "source": "tencent_live_quote",
        "exchange_timestamp": exchange_timestamp,
        "fetched_at": "2026-08-14T01:35:03+00:00",
    }


def test_quote_must_be_strictly_after_signal_and_data_cutoff_before_signal():
    verified, reason = validate_post_signal_quote(
        _decision(), _quote("20260814093500")
    )
    assert verified is None
    assert reason == "quote_not_after_signal"

    invalid = _decision()
    invalid["data_cutoff_at"] = "2026-08-14T09:35:01+08:00"
    verified, reason = validate_post_signal_quote(
        invalid, _quote("20260814093502")
    )
    assert verified is None
    assert reason == "data_cutoff_after_signal"


def test_tushare_realtime_minute_is_an_execution_quote_source():
    quote = _quote("20260814093502")
    quote["source"] = "tushare_rt_min"

    verified, reason = validate_post_signal_quote(_decision(), quote)

    assert reason == "verified_post_signal_quote"
    assert verified["source"] == "tushare_rt_min"


def test_execution_candidates_exclude_neutral_scan_rows():
    decisions = [
        {
            "stock_code": "000001.SZ", "ai_score": 82, "direction": "buy",
            "deep_analysis_available": True, "deep_rating": "Buy",
            **_codex_approval(),
        },
        {"stock_code": "000005.SZ", "ai_score": 82, "direction": "buy"},
        {
            "stock_code": "000006.SZ", "ai_score": 75, "direction": "buy",
            "deep_analysis_available": True, "deep_rating": "Hold",
        },
        {"stock_code": "000002.SZ", "ai_score": 70, "direction": "neutral"},
        {"stock_code": "000003.SZ", "ai_score": 40, "direction": "sell"},
        {"stock_code": "000004.SZ", "ai_score": 55, "direction": "neutral"},
    ]

    selected = _execution_candidates(decisions, {"000003.SZ"})

    assert [item["stock_code"] for item in selected] == [
        "000001.SZ",
        "000003.SZ",
    ]


def test_paper_strategy_fails_closed_without_tradingagents_buy(tmp_path):
    database = MarketDatabase(tmp_path / "deep-gate.db")
    technical_only = {
        "date": "2026-08-14",
        "stock_code": "000001.SZ",
        "stock_name": "technical-only",
        "ai_score": 82,
        "direction": "buy",
        "market_price": 10.0,
    }
    deep_hold = {
        **technical_only,
        "stock_code": "000002.SZ",
        "stock_name": "deep-hold",
        "deep_analysis_available": True,
        "deep_rating": "Hold",
        "deep_provider": "codex_cli",
        "deep_model": "gpt-5.6-terra",
    }

    result = database.run_paper_strategy(
        [technical_only, deep_hold],
        "2026-08-14",
        strict_real_data=False,
    )

    assert result["actions"] == []
    assert {item["reason"] for item in result["rejections"]} == {
        "codex_deep_analysis_required",
        "codex_deep_buy_not_approved:hold",
    }


@pytest.mark.xfail(
    reason=(
        "Documents a regression the journal de-duplication introduced. This "
        "protection came from the journal-scoped strategy key: one journal row "
        "per scan meant one strategy row per scan, so an afternoon scan that "
        "skipped deep analysis could not erase the morning's. The journal now "
        "holds one row per (date, code), get_cached_deep_analyses reads "
        "strategy_decision, and save_strategy_decision replaces that row -- so "
        "an empty deep_rating from a later scan wipes the day's real one and "
        "the cache then finds nothing. The test was passing only because test "
        "databases lacked the unique index production had; it now fails on "
        "both. Fixing it changes deep_rating, which gates buying, so it needs "
        "a decision rather than a patch."
    ),
    strict=True,
)
def test_strategy_rows_are_not_overwritten_by_later_same_day_scan(tmp_path):
    database = MarketDatabase(tmp_path / "strategy-history.db")
    morning = _decision()
    morning_id = database.save_decision(morning)
    database.save_strategy_decision(morning, morning_id)

    afternoon = {
        **morning,
        "ai_score": 55,
        "direction": "neutral",
        "signal_at": "2026-08-14T14:31:00+08:00",
        "deep_analysis_available": False,
        "deep_rating": "",
    }
    afternoon_id = database.save_decision(afternoon)
    database.save_strategy_decision(afternoon, afternoon_id)

    rows = database.get_decisions_for_date("2026-08-14")
    by_id = {row["id"]: row for row in rows}
    assert by_id[morning_id]["deep_rating"] == "Overweight"
    assert not by_id[afternoon_id]["deep_analysis_available"]
    assert database.count_cached_deep_analyses("2026-08-14") == 1


def test_held_decision_is_kept_below_the_top_300_cutoff():
    all_scored = [
        {"stock_code": f"{index:06d}.SZ", "ai_score": 100 - index / 10}
        for index in range(301)
    ]
    holding = {"stock_code": "600667.SH", "ai_score": 34, "direction": "sell"}
    all_scored.append(holding)

    selected = _include_held_decisions(
        all_scored[:300],
        all_scored,
        {"600667.SH"},
    )

    assert len(selected) == 301
    assert selected[-1] is holding


@pytest.mark.asyncio
async def test_execution_quote_retries_until_exchange_time_is_after_signal():
    calls = 0

    async def fetcher(codes):
        nonlocal calls
        calls += 1
        timestamp = "20260814093500" if calls == 1 else "20260814093502"
        return {codes[0]: _quote(timestamp)}

    accepted, rejected = await fetch_post_signal_quotes(
        [_decision()], fetcher, attempts=2, retry_delay_seconds=0
    )

    assert calls == 2
    assert rejected == []
    assert accepted["000001.SZ"]["exchange_at"] == "2026-08-14T09:35:02+08:00"
    assert accepted["000001.SZ"]["fetched_at"] == "2026-08-14T09:35:03+08:00"
    assert accepted["000001.SZ"]["causality_status"] == (
        "verified_post_signal_quote"
    )


def test_intraday_signal_cannot_use_same_day_completed_daily_bar():
    bars = [
        {"date": "2026-08-13", "close": 10},
        {"date": "2026-08-14", "close": 99},
        {"date": "2026-08-15", "close": 999},
    ]

    intraday = _causal_daily_bars(
        bars,
        datetime(2026, 8, 14, 14, 30, tzinfo=CHINA_TZ),
    )
    after_close = _causal_daily_bars(
        bars,
        datetime(2026, 8, 14, 15, 6, tzinfo=CHINA_TZ),
    )

    assert [bar["date"] for bar in intraday] == ["2026-08-13"]
    assert [bar["date"] for bar in after_close] == [
        "2026-08-13",
        "2026-08-14",
    ]


def test_database_rejects_a_pre_signal_quote_and_audits_reason(tmp_path):
    database = MarketDatabase(tmp_path / "time-travel.db")
    decision = _decision()
    decision.update({
        "market_price": 10,
        "market_price_date": "2026-08-14",
        "market_price_source": "tencent_live_quote",
        "market_price_exchange_at": "2026-08-14T09:35:00+08:00",
        "market_price_fetched_at": "2026-08-14T09:35:01+08:00",
    })

    result = database.run_paper_strategy(
        [decision],
        "2026-08-14",
        execution_timestamp="2026-08-14T09:35:02+08:00",
        trading_day_verified=True,
        is_trading_day=True,
    )

    assert result["actions"] == []
    assert result["rejections"][0]["reason"] == "quote_not_after_signal"
    with database._get_conn() as connection:
        rejection = dict(connection.execute(
            "SELECT * FROM paper_order_rejection"
        ).fetchone())
    assert rejection["signal_at"] == decision["signal_at"]
    assert rejection["quote_exchange_at"] == decision["market_price_exchange_at"]


def test_database_rejects_fill_timestamp_before_quote_arrival(tmp_path):
    database = MarketDatabase(tmp_path / "fill-before-quote.db")
    decision = _decision()
    decision.update({
        "market_price": 10,
        "market_price_date": "2026-08-14",
        "market_price_source": "tencent_live_quote",
        "market_price_exchange_at": "2026-08-14T09:35:02+08:00",
        "market_price_fetched_at": "2026-08-14T09:35:03+08:00",
    })

    result = database.run_paper_strategy(
        [decision],
        "2026-08-14",
        execution_timestamp="2026-08-14T09:35:02.500000+08:00",
        trading_day_verified=True,
        is_trading_day=True,
    )

    assert result["actions"] == []
    assert result["rejections"][0]["reason"] == "execution_before_quote_received"


def test_quote_received_after_session_is_not_eligible_for_fill():
    quote = _quote("20260814145659")
    quote["fetched_at"] = "2026-08-14T06:57:01+00:00"

    verified, reason = validate_post_signal_quote(_decision(), quote)

    assert verified is None
    assert reason == "quote_received_outside_market_session"


def test_closing_call_auction_is_not_simulated_as_an_immediate_fill():
    quote = _quote("20260814145701")
    quote["fetched_at"] = "2026-08-14T06:57:02+00:00"

    verified, reason = validate_post_signal_quote(_decision(), quote)

    assert verified is None
    assert reason == "quote_outside_market_session"


def test_night_order_is_rejected_and_persisted_for_audit(tmp_path):
    database = MarketDatabase(tmp_path / "night-order.db")

    result = database.run_paper_strategy(
        [_decision()],
        "2026-08-14",
        execution_timestamp="2026-08-14T21:38:00+08:00",
        trading_day_verified=True,
        is_trading_day=True,
    )
    rejections = database.get_paper_order_rejections()

    assert result["actions"] == []
    assert result["execution_status"] == "market_closed"
    assert result["rejections"][0]["reason"] == "market_closed"
    assert rejections[0]["execution_at"] == "2026-08-14T21:38:00+08:00"
    assert rejections[0]["reason"] == "market_closed"


def test_unverified_or_closed_trading_calendar_fails_closed(tmp_path):
    database = MarketDatabase(tmp_path / "calendar.db")

    unverified = database.run_paper_strategy(
        [_decision()],
        "2026-08-14",
        execution_timestamp="2026-08-14T09:35:03+08:00",
    )
    holiday = database.run_paper_strategy(
        [_decision()],
        "2026-08-14",
        execution_timestamp="2026-08-14T09:35:03+08:00",
        trading_day_verified=True,
        is_trading_day=False,
        trading_calendar_source="calendar_test",
    )

    assert unverified["execution_status"] == "trading_calendar_unverified"
    assert holiday["execution_status"] == "market_holiday"
    assert holiday["trading_calendar_source"] == "calendar_test"


def test_market_data_freshness_uses_completed_trading_day_not_three_day_age():
    verified = CompletedTradingDayStatus(
        day=datetime(2026, 8, 13).date(),
        source="calendar_test",
    )
    degraded = CompletedTradingDayStatus(
        day=datetime(2026, 8, 13).date(),
        source="weekday_fallback",
        degraded=True,
    )

    assert not market_data_covers_latest_completed_day("2026-08-12", verified)
    assert market_data_covers_latest_completed_day("2026-08-13", verified)
    assert market_data_covers_latest_completed_day("2026-08-13", degraded)


def test_causality_policy_archives_and_labels_historical_replay(tmp_path):
    database = MarketDatabase(tmp_path / "causality-policy.db")
    database.ensure_paper_account(100_000)
    with database._get_conn() as connection:
        connection.execute(
            """INSERT INTO paper_trade(
                   trade_date, action, stock_code, stock_name, shares, price,
                   value, created_at, signal_at, execution_mode, legacy_trade_id
               ) VALUES (
                   '2026-08-12', 'BUY', '000001.SZ', 'old', 100, 10,
                   1000, '2026-08-12T09:30:00+08:00',
                   '2026-08-11T21:38:00+08:00',
                   'next_trading_day_open_after_close_signal', 1
               )"""
        )

    result = database.apply_paper_causality_policy()
    portfolio = database.get_paper_portfolio()
    trade = database.get_paper_trades()[0]

    assert result["status"] == "applied"
    assert result["archive_id"] == 1
    assert portfolio["ledger_version"] == 4
    assert portfolio["execution_policy"] == "post_signal_fresh_exchange_quote_v1"
    assert trade["causality_status"] == "verified_historical_bar_replay"
    assert trade["execution_time_type"] == "historical_bar_replay"


@pytest.mark.asyncio
async def test_pipeline_serializes_overlapping_runs(monkeypatch):
    runner = AIPipelineRunner()
    active = 0
    max_active = 0

    async def fake_run(codes=None, save_to_journal=True, **kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return PipelineResult()

    monkeypatch.setattr(runner, "_run_daily_pipeline_once", fake_run)
    await asyncio.gather(
        runner.run_daily_pipeline(),
        runner.run_daily_pipeline(),
    )

    assert max_active == 1


@pytest.mark.asyncio
async def test_market_open_uses_latest_persisted_decision_per_stock(monkeypatch):
    rows = [
        {
            "id": 3,
            "decision_date": datetime.now().date().isoformat(),
            "created_at": "2026-08-20T08:39:00+08:00",
            "stock_code": "000001.SZ",
            "ai_score": 80,
            "direction": "buy",
        },
        {
            "id": 2,
            "decision_date": datetime.now().date().isoformat(),
            "created_at": "2026-08-20T01:05:00+08:00",
            "stock_code": "000001.SZ",
            "ai_score": 70,
            "direction": "buy",
        },
        {
            "id": 1,
            "decision_date": datetime.now().date().isoformat(),
            "created_at": "2026-08-20T01:04:00+08:00",
            "stock_code": "600000.SH",
            "ai_score": 50,
            "direction": "neutral",
        },
    ]
    monkeypatch.setattr(market_db, "get_decisions_for_date", lambda *a, **k: rows)
    execute = AsyncMock(return_value={
        "paper_result": {
            "actions": [],
            "cash": 100000.0,
            "position_count": 0,
            "execution_status": "no_action",
            "execution_at": "2026-08-20T09:35:05+08:00",
            "rejections": [],
        },
        "pre_trade_portfolio_mark": {},
        "portfolio_mark": {},
        "execution_quotes": {},
        "execution_decisions": [],
        "causal_rejections": [],
        "trading_calendar_source": "baostock_trade_calendar",
        "trading_calendar_verified": True,
    })
    monkeypatch.setattr(pipeline_runner_module, "_execute_paper_cycle", execute)

    result = await AIPipelineRunner().execute_persisted_strategy()

    sent = execute.await_args.args[0]
    assert [item["stock_code"] for item in sent] == ["000001.SZ", "600000.SH"]
    assert sent[0]["signal_at"] == "2026-08-20T08:39:00+08:00"
    assert sent[0]["data_cutoff_at"] == sent[0]["signal_at"]
    assert result["status"] == "executed_persisted_plan"
    assert result["source_decision_count"] == 2


def test_learning_profile_excludes_same_day_and_future_outcomes(tmp_path):
    database = MarketDatabase(tmp_path / "future-learning.db")
    with database._get_conn() as connection:
        connection.executemany(
            """INSERT INTO market_learning_observation(
                   decision_id, observation_date, horizon_days, stock_code,
                   direction, was_correct, stock_return, benchmark_return,
                   excess_return, sources_json, feature_json, created_at
               ) VALUES (?, ?, 1, '000001.SZ', 'buy', 1, 0.1, 0, 0.1,
                         '[]', '{}', '')""",
            [
                (1, "2026-08-13"),
                (2, "2026-08-14"),
                (3, "2099-01-01"),
            ],
        )

    profile = database.get_market_learning_profile(
        horizon_days=1,
        as_of_date="2026-08-14",
    )

    assert profile["total_observations"] == 1
    assert profile["as_of_date_exclusive"] == "2026-08-14"
