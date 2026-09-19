import json
from datetime import date, timedelta

from src.ai_os.market_learning import multi_horizon_learning_adjustment
from src.ai_os.paper_execution_service import PaperExecutionService
from src.explain import outcome_backfiller
from src.infrastructure.storage.market_database import MarketDatabase


def _decision(code: str, day: str, price: float, direction: str = "buy") -> dict:
    return {
        "date": day,
        "stock_code": code,
        "stock_name": "isolated cycle",
        "ai_score": 78,
        "action_score": 78,
        "technical_score": 72,
        "confidence": 0.8,
        "direction": direction,
        "recommendation": "Buy" if direction == "buy" else "Sell",
        "market_price": price,
        "market_price_date": day,
        "market_price_source": "isolated_fixture",
        "market_price_fetched_at": f"{day}T09:35:00+08:00",
        "universe_industry": "软件",
        "signal_at": f"{day}T09:34:00+08:00",
        "data_cutoff_at": f"{day}T09:34:00+08:00",
        "deep_analysis_available": True,
        "deep_rating": "Buy",
        "deep_provider": "codex_cli",
        "deep_model": "gpt-5.6-terra",
        "final_review_available": True,
        "final_review_verdict": "approve",
        "final_buy_approved": True,
        "market_flow": {"status": "positive", "main_net": 100},
        "flow_status": "positive",
        "flow_sources": ["tushare"],
        "fallback_attempted": True,
        "fallback_status": "confirmed",
        "gate_reasons": [],
        "non_flow_gates_passed": True,
        "execution_evidence_complete": True,
        "evidence": json.dumps(
            {"market_discovery": {"sources": ["tushare"]}},
            ensure_ascii=False,
        ),
    }


def test_buy_sell_then_learning_profile_consumes_observation(tmp_path, monkeypatch):
    database = MarketDatabase(tmp_path / "cycle.db")
    code = "000001.SZ"
    rows = []
    start = date.fromisoformat("2026-08-13")
    for offset in range(25):
        day = start + timedelta(days=offset)
        if offset == 0:
            close = 10.0
        elif offset == 1:
            close = 10.8
        elif offset == 2:
            close = 10.7
        else:
            close = 10.7 + offset * 0.01
        rows.append({
            "ts_code": code,
            "trade_date": day.isoformat(),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "pre_close": close,
            "change_pct": 0,
            "volume": 1000,
            "amount": 10000,
            "turnover": 1,
        })
    # The benchmark is the equal-weight universe, so a single-stock fixture
    # would make it identical to the stock under test and force excess to zero.
    # Flat peers give the pick something to beat.
    for peer in ("600000.SH", "600001.SH", "600002.SH"):
        for offset in range(25):
            day = (start + timedelta(days=offset)).isoformat()
            rows.append({
                "ts_code": peer,
                "trade_date": day,
                "open": 20.0,
                "high": 20.0,
                "low": 20.0,
                "close": 20.0,
                "pre_close": 20.0,
                "change_pct": 0,
                "volume": 1000,
                "amount": 20000,
                "turnover": 1,
            })
    database.upsert_tushare_daily_history(rows)

    buy = _decision(code, "2026-08-13", 10.0)
    buy["journal_id"] = database.save_decision(buy)
    bought = PaperExecutionService(database).execute(
        [buy], "2026-08-13", strict_real_data=False,
        trading_day_verified=True, is_trading_day=True,
    )
    assert [action["action"] for action in bought["actions"]] == ["BUY"]
    reopened = MarketDatabase(database.db_path)
    assert reopened.get_paper_portfolio()["positions"][0]["entry_deep_rating"] == "Buy"

    sell = _decision(code, "2026-08-14", 10.8, direction="sell")
    sell["journal_id"] = reopened.save_decision(sell)
    sold = PaperExecutionService(reopened).execute(
        [sell], "2026-08-14", strict_real_data=False,
        trading_day_verified=True, is_trading_day=True,
    )
    assert [action["action"] for action in sold["actions"]] == ["SELL"]

    monkeypatch.setattr(outcome_backfiller, "market_db", reopened)
    # The benchmark is now derived per window from the local bar table rather
    # than handed in as a prefetched series, so this passes the session
    # calendar and lets `reopened` supply the equal-weight universe.
    stats = outcome_backfiller._backfill_market_observations(
        1,
        ["2026-08-13", "2026-08-14", "2026-08-15"],
    )
    assert stats["verified"] == 2

    profile = reopened.get_market_learning_profile(
        horizon_days=1, as_of_date="2026-09-08"
    )
    learned = multi_horizon_learning_adjustment(
        {1: profile}, code, ["tushare"]
    )
    assert profile["decisive_observations"] == 2
    assert learned["score_adjustment"] > 0

    reopened_again = MarketDatabase(database.db_path)
    duplicate = outcome_backfiller._backfill_market_observations(
        1,
        {
            "2026-08-13": 100.0,
            "2026-08-14": 102.0,
            "2026-08-15": 102.5,
        },
    )
    assert duplicate["pending"] == 0
    assert reopened_again.get_market_learning_profile(
        horizon_days=1, as_of_date="2026-09-08"
    )["decisive_observations"] == 2
