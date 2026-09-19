import pytest

from src.infrastructure.storage.market_database import MarketDatabase
from config.settings import settings  # noqa: E402


def _missing_probe(code: str, day: str, *, price: float = 10.0) -> dict:
    return {
        "date": day,
        "stock_code": code,
        "stock_name": "flow probe",
        "universe_industry": "软件",
        "ai_score": 76,
        "technical_score": 70,
        "strategy_confirmations": 3,
        "pre_gate_direction": "buy",
        "final_direction": "neutral",
        "direction": "neutral",
        "non_flow_gates_passed": True,
        "gate_reasons": ["fund_flow_missing"],
        "flow_status": "missing",
        "market_flow": {
            "status": "missing",
            "fallback_attempted": True,
            "fallback_status": "exhausted",
        },
        "market_price": price,
        "market_change_pct": 1.0,
        "market_price_date": day,
        "market_price_source": "tencent_live_quote",
        "data_cutoff_at": f"{day}T09:34:58+08:00",
        "signal_at": f"{day}T09:35:00+08:00",
        "market_price_exchange_at": f"{day}T09:35:02+08:00",
        "market_price_fetched_at": f"{day}T09:35:02+08:00",
    }


def _approved_buy(code: str, day: str, *, price: float = 10.5) -> dict:
    decision = _missing_probe(code, day, price=price)
    decision.update({
        "direction": "buy",
        "final_direction": "buy",
        "flow_status": "ok",
        "market_flow": {"status": "ok", "main_net": 200},
        "gate_reasons": [],
        "deep_analysis_available": True,
        "deep_rating": "Overweight",
        "deep_provider": "codex_cli",
        "deep_model": settings.CODEX_MODEL,
        "final_buy_approved": True,
        "final_review_available": True,
        "final_review_verdict": "approve",
    })
    return decision


def _run(database, decision, day: str):
    return database.run_paper_strategy(
        [decision],
        day,
        100_000,
        execution_timestamp=f"{day}T09:35:03+08:00",
        trading_day_verified=True,
        is_trading_day=True,
    )


def test_missing_flow_opens_a_strict_paper_probe_and_persists_identity(tmp_path):
    database = MarketDatabase(tmp_path / "flow-probe.db")

    result = _run(database, _missing_probe("000001.SZ", "2026-08-13"), "2026-08-13")
    portfolio = database.get_paper_portfolio()
    trade = database.get_paper_trades()[0]

    assert result["actions"][0]["execution_tier"] == "probe"
    assert result["actions"][0]["shares"] == 100
    assert result["probe_opened"] == 1
    assert portfolio["positions"][0]["execution_tier"] == "probe"
    assert portfolio["positions"][0]["entry_flow_state"] == "missing"
    assert portfolio["positions"][0]["entry_fallback_status"] == "exhausted"
    assert trade["execution_tier"] == "probe"
    assert trade["flow_state"] == "missing"


def test_negative_flow_is_recorded_as_blocked_and_never_bought(tmp_path):
    database = MarketDatabase(tmp_path / "negative-flow.db")
    decision = _missing_probe("000001.SZ", "2026-08-13")
    decision.update({
        "flow_status": "negative",
        "market_flow": {"status": "negative", "main_net": -200},
        "gate_reasons": ["fund_flow_negative"],
    })

    result = _run(database, decision, "2026-08-13")
    rejection = database.get_paper_order_rejections()[0]

    assert result["actions"] == []
    assert result["rejections"][0]["reason"] == "fund_flow_negative"
    assert rejection["execution_tier"] == "blocked"
    assert rejection["flow_state"] == "negative"


def test_probe_daily_limit_is_one_and_does_not_open_a_second_position(tmp_path):
    database = MarketDatabase(tmp_path / "probe-daily-limit.db")
    first = _missing_probe("000001.SZ", "2026-08-13")
    second = _missing_probe("000002.SZ", "2026-08-13", price=11.0)

    result = database.run_paper_strategy(
        [first, second],
        "2026-08-13",
        100_000,
        execution_timestamp="2026-08-13T09:35:03+08:00",
        trading_day_verified=True,
        is_trading_day=True,
    )

    assert len([a for a in result["actions"] if a["execution_tier"] == "probe"]) == 1
    assert result["probe_opened"] == 1
    assert any(
        rejection["reason"] == "flow_probe_entry_limit_reached"
        for rejection in result["rejections"]
    )


def test_probe_promotion_tops_up_without_averaging_down(tmp_path):
    database = MarketDatabase(tmp_path / "probe-promotion.db")
    code = "000001.SZ"
    opened = _run(database, _missing_probe(code, "2026-08-13"), "2026-08-13")
    old_cost = database.get_paper_portfolio()["positions"][0]["cost_price"]

    promoted = _run(database, _approved_buy(code, "2026-08-14"), "2026-08-14")
    position = database.get_paper_portfolio()["positions"][0]
    trades = database.get_paper_trades(limit=10)

    assert opened["probe_opened"] == 1
    assert promoted["probe_promoted"] == 1
    assert any(action.get("promotion_status") == "promoted" for action in promoted["actions"])
    assert position["execution_tier"] == "normal"
    assert position["promotion_status"] == "promoted"
    assert position["shares"] > 200
    assert position["cost_price"] >= old_cost
    assert any(trade.get("promotion_status") == "promoted" for trade in trades)


def test_probe_stop_loss_does_not_require_a_new_buy_decision(tmp_path):
    database = MarketDatabase(tmp_path / "probe-stop-loss.db")
    code = "000001.SZ"
    _run(database, _missing_probe(code, "2026-08-13"), "2026-08-13")
    decision = _missing_probe(code, "2026-08-14", price=9.5)
    decision["market_change_pct"] = -1.0

    result = _run(database, decision, "2026-08-14")

    assert result["actions"]
    assert result["actions"][0]["action"] == "SELL"
    assert result["actions"][0]["reason"].startswith("probe_stop_loss")
