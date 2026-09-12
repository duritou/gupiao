from types import SimpleNamespace

import pytest

from src.ai_os.portfolio_marking import refresh_paper_portfolio_quotes
from src.infrastructure.storage.market_database import MarketDatabase


def _codex_approval() -> dict:
    return {
        "deep_provider": "codex_cli",
        "deep_model": "gpt-5.6-terra",
        "final_buy_approved": True,
        "final_review_provider": "codex_cli",
        "final_review_model": "gpt-5.6-terra",
    }


def _seed_positions(database: MarketDatabase) -> None:
    database.ensure_paper_account(100_000)
    with database._get_conn() as connection:
        connection.execute("UPDATE paper_account SET cash=10000 WHERE id=1")
        connection.executemany(
            """INSERT INTO paper_position(
                   stock_code, stock_name, shares, avg_cost, updated_at,
                   entry_date, eligible_sell_date
               ) VALUES (?, ?, ?, ?, '', '2026-08-10', '2026-08-10')""",
            [
                ("000001.SZ", "first", 100, 9.0),
                ("000002.SZ", "second", 200, 19.0),
            ],
        )


def test_paper_portfolio_mark_calculates_daily_pl_and_persists_provenance(tmp_path):
    database = MarketDatabase(tmp_path / "portfolio.db")
    _seed_positions(database)

    result = database.mark_paper_portfolio(
        "2026-08-13",
        {
            "000001.SZ": {
                "price": 11.0,
                "pre_close": 10.0,
                "data_date": "2026-08-13",
                "source": "tencent",
            },
            "000002.SZ": {
                "price": 21.0,
                "pre_close": 20.0,
                "data_date": "2026-08-13",
                "source": "tencent",
            },
        },
    )

    assert result["daily_pl"] == pytest.approx(300.0)
    assert result["daily_pl_pct"] == pytest.approx(2.0)
    assert result["market_pnl"] == pytest.approx(300.0)
    assert result["reconciliation_delta"] == pytest.approx(0.0)
    assert result["reconciliation_status"] == "pass"
    assert result["price_coverage"] == 1.0

    portfolio = database.get_paper_portfolio(as_of_date="2026-08-13")
    assert portfolio["total_value"] == pytest.approx(15_300.0)
    assert portfolio["daily_pl"] == pytest.approx(300.0)
    assert portfolio["daily_pl_pct"] == pytest.approx(2.0)
    assert portfolio["market_pnl"] == pytest.approx(300.0)
    assert portfolio["reconciliation_status"] == "pass"
    assert portfolio["valuation_status"] == "fresh"
    assert portfolio["price_sources"] == ["tencent"]
    assert portfolio["positions"][0]["price_date"] == "2026-08-13"
    assert portfolio["positions"][0]["daily_pl"] == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_remote_refresh_marks_live_quotes_with_requested_date(tmp_path):
    database = MarketDatabase(tmp_path / "remote-mark.db")
    _seed_positions(database)

    class QuoteSource:
        async def get_realtime_quote(self, code):
            price = 11.0 if code == "000001.SZ" else 21.0
            pre_close = 10.0 if code == "000001.SZ" else 20.0
            return (
                {"price": price, "pre_close": pre_close},
                SimpleNamespace(
                    provider="tencent",
                    fetched_at="2026-08-13T15:01:00",
                    error_message="",
                    is_live=True,
                ),
            )

    result = await refresh_paper_portfolio_quotes(
        "2026-08-13",
        database=database,
        quote_source=QuoteSource(),
    )

    assert result["fresh_position_count"] == 2
    assert result["daily_pl"] == pytest.approx(300.0)


def test_paper_strategy_prefers_remote_decision_price_over_stale_local_quote(
    tmp_path, monkeypatch
):
    database = MarketDatabase(tmp_path / "execution-price.db")
    monkeypatch.setattr(
        database,
        "get_latest_quote",
        lambda code: {"price": 10.0, "change_pct": 1.0},
    )

    result = database.run_paper_strategy(
        [{
            "stock_code": "000001.SZ",
            "stock_name": "remote",
            "ai_score": 75,
            "direction": "buy",
            "universe_industry": "软件",
            "deep_analysis_available": True,
            "deep_rating": "Overweight",
            **_codex_approval(),
            "market_price": 20.0,
            "market_change_pct": 1.0,
            "market_price_date": "2026-08-13",
            "market_price_source": "tencent_live_quote",
            "data_cutoff_at": "2026-08-13T14:29:58+08:00",
            "signal_at": "2026-08-13T14:30:00+08:00",
            "market_price_exchange_at": "2026-08-13T14:30:02+08:00",
            "market_price_fetched_at": "2026-08-13T14:30:03+08:00",
        }],
        "2026-08-13",
        100_000,
        max_position_pct=0.20,
        execution_timestamp="2026-08-13T14:30:03+08:00",
        trading_day_verified=True,
        is_trading_day=True,
    )

    assert result["actions"][0]["price"] == pytest.approx(20.02)
    assert result["actions"][0]["shares"] == 900
    assert result["actions"][0]["reason"] == (
        "codex_terra=Overweight; max_position=20%"
    )
    assert result["actions"][0]["price_source"] == "tencent_live_quote"
    assert result["actions"][0]["execution_at"] == "2026-08-13T14:30:03+08:00"
    trade = database.get_paper_trades()[0]
    assert trade["quote_exchange_at"] == "2026-08-13T14:30:02+08:00"
    assert trade["quote_fetched_at"] == "2026-08-13T14:30:03+08:00"


def test_twenty_percent_cap_can_buy_multiple_lots_of_higher_price_stock(tmp_path):
    database = MarketDatabase(tmp_path / "round-lot-cap.db")
    result = database.run_paper_strategy(
        [{
            "stock_code": "000001.SZ",
            "stock_name": "high-price",
            "ai_score": 75,
            "direction": "buy",
            "deep_analysis_available": True,
            "deep_rating": "Overweight",
            **_codex_approval(),
            "market_price": 60.0,
        }],
        "2026-08-13",
        100_000,
        strict_real_data=False,
    )

    assert result["actions"][0]["shares"] == 300
    assert result["max_position_pct"] == 0.20


def test_twenty_percent_cap_still_rejects_when_one_lot_exceeds_cap(tmp_path):
    database = MarketDatabase(tmp_path / "round-lot-over-cap.db")
    result = database.run_paper_strategy(
        [{
            "stock_code": "000001.SZ",
            "stock_name": "very-high-price",
            "ai_score": 75,
            "direction": "buy",
            "deep_analysis_available": True,
            "deep_rating": "Overweight",
            **_codex_approval(),
            "market_price": 220.0,
        }],
        "2026-08-13",
        100_000,
        strict_real_data=False,
    )

    assert result["actions"] == []
    assert result["rejections"][0]["reason"] == (
        "position_cap_below_one_round_lot"
    )


def test_paper_strategy_rejects_stale_quote_and_closed_market(tmp_path):
    database = MarketDatabase(tmp_path / "strict-price.db")
    decision = {
        "stock_code": "000001.SZ",
        "stock_name": "strict",
        "ai_score": 75,
        "direction": "buy",
        "deep_analysis_available": True,
        "deep_rating": "Overweight",
        **_codex_approval(),
        "market_price": 20.0,
        "market_price_date": "2026-08-12",
        "market_price_source": "tencent_live_quote",
    }

    closed = database.run_paper_strategy(
        [decision],
        "2026-08-13",
        execution_timestamp="2026-08-13T20:00:00+08:00",
        trading_day_verified=True,
        is_trading_day=True,
    )
    assert closed["execution_status"] == "market_closed"
    assert closed["actions"] == []

    stale = database.run_paper_strategy(
        [decision],
        "2026-08-13",
        execution_timestamp="2026-08-13T14:30:00+08:00",
        trading_day_verified=True,
        is_trading_day=True,
    )
    assert stale["execution_status"] == "verified_no_action"
    assert stale["actions"] == []
    assert stale["rejections"][0]["reason"] == "stale_or_future_quote_date"
