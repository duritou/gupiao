from src.infrastructure.storage.market_database import MarketDatabase
from config.settings import settings  # noqa: E402


def _decision(code: str, day: str, *, flow: str, price: float = 10.0) -> dict:
    positive = flow == "positive"
    return {
        "date": day,
        "stock_code": code,
        "stock_name": "integration probe",
        "ai_score": 76,
        "technical_score": 70,
        "strategy_confirmations": 3,
        "pre_gate_direction": "buy",
        "final_direction": "buy" if positive else "neutral",
        "direction": "buy" if positive else "neutral",
        "non_flow_gates_passed": True,
        "gate_reasons": [] if positive else [f"fund_flow_{flow}"],
        "flow_status": "ok" if positive else flow,
        "market_flow": (
            {"status": "ok", "main_net": 200}
            if positive else
            {
                "status": flow,
                "fallback_attempted": True,
                "fallback_status": "exhausted",
            }
        ),
        "market_price": price,
        "market_change_pct": 0.0,
        "market_price_date": day,
        "market_price_source": "tencent_live_quote",
        "universe_industry": "软件",
        "data_cutoff_at": f"{day}T09:34:58+08:00",
        "signal_at": f"{day}T09:35:00+08:00",
        "market_price_exchange_at": f"{day}T09:35:02+08:00",
        "market_price_fetched_at": f"{day}T09:35:02+08:00",
        **(
            {
                "deep_analysis_available": True,
                "deep_rating": "Overweight",
                "deep_provider": "codex_cli",
                "deep_model": settings.CODEX_MODEL,
                "final_buy_approved": True,
                "final_review_available": True,
                "final_review_verdict": "approve",
            }
            if positive else {}
        ),
    }


def _run(database, decision, day: str):
    return database.run_paper_strategy(
        [decision],
        day,
        100_000,
        execution_timestamp=f"{day}T09:35:03+08:00",
        trading_day_verified=True,
        is_trading_day=True,
    )


def test_missing_flow_to_positive_flow_promotes_probe(tmp_path):
    database = MarketDatabase(tmp_path / "probe-positive-cycle.db")
    code = "000001.SZ"

    first = _run(database, _decision(code, "2026-08-13", flow="missing"), "2026-08-13")
    second = _run(database, _decision(code, "2026-08-14", flow="positive", price=10.5), "2026-08-14")

    assert first["probe_opened"] == 1
    assert second["probe_promoted"] == 1
    assert database.get_paper_portfolio()["positions"][0]["execution_tier"] == "normal"


def test_missing_flow_to_negative_flow_exits_probe(tmp_path):
    database = MarketDatabase(tmp_path / "probe-negative-cycle.db")
    code = "000001.SZ"

    _run(database, _decision(code, "2026-08-13", flow="missing"), "2026-08-13")
    result = _run(
        database,
        _decision(code, "2026-08-14", flow="negative", price=9.7),
        "2026-08-14",
    )

    assert result["actions"]
    assert result["actions"][0]["action"] == "SELL"
    assert result["actions"][0]["reason"] == "probe_flow_negative"
    assert database.get_paper_portfolio()["positions"] == []


def test_confirmed_research_probe_uses_existing_small_position_limits(tmp_path):
    database = MarketDatabase(tmp_path / "confirmed-research.db")
    decision = _decision('000001.SZ', '2026-08-13', flow='positive')
    decision.update(direction='neutral', final_direction='neutral', ai_score=68,
                    action_score=68, execution_evidence_complete=True)
    result = _run(database, decision, '2026-08-13')
    assert result['probe_opened'] == 1
    position = database.get_paper_portfolio()['positions'][0]
    assert position['execution_tier'] == 'probe'
    assert position['shares'] * position['cost_price'] <= 3000
    repeated = _run(database, decision, '2026-08-13')
    assert not [a for a in repeated['actions'] if a['action'] == 'BUY']
