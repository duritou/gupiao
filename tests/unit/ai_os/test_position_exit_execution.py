from src.ai_os.trading_policy import position_exit_reason
from src.infrastructure.storage.market_database import MarketDatabase


def _position() -> dict:
    return {"avg_cost": 10.0, "entry_date": "2026-08-01"}


def test_hard_stop_loss_cannot_be_bypassed_by_deep_buy() -> None:
    reason = position_exit_reason(
        _position(),
        {"ai_score": 80, "direction": "buy", "deep_rating": "Buy"},
        current_price=9.2,
        holding_days=2,
    )

    assert reason == "hard_stop_loss=-8%;return=-8.0%"


def test_absolute_holding_limit_cannot_be_bypassed_by_deep_buy() -> None:
    reason = position_exit_reason(
        _position(),
        {"ai_score": 80, "direction": "buy", "deep_rating": "Overweight"},
        current_price=10.5,
        holding_days=20,
    )

    assert reason == "max_holding_days=20"


def test_missing_quote_never_uses_average_cost_as_sell_price(tmp_path) -> None:
    database = MarketDatabase(tmp_path / "missing-quote.db")
    database.ensure_paper_account(100_000)
    with database._get_conn() as connection:
        connection.execute("UPDATE paper_account SET cash=90000 WHERE id=1")
        connection.execute(
            """INSERT INTO paper_position(
                   stock_code, stock_name, shares, avg_cost, updated_at,
                   entry_date, eligible_sell_date
               ) VALUES ('000001.SZ', 'missing-quote', 1000, 10, '',
                         '2026-08-01', '2026-08-01')"""
        )

    result = database.run_paper_strategy(
        [],
        "2026-09-01",
        strict_real_data=False,
    )

    assert result["actions"] == []
    assert len(database.get_paper_portfolio("2026-09-01")["positions"]) == 1

