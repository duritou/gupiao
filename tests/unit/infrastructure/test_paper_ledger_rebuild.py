import pytest

from src.ai_os.paper_ledger_rebuild import replay_legacy_trade_intents
from src.infrastructure.storage.market_database import MarketDatabase


def _bars(rows):
    return [
        {"date": day, "open": open_price, "close": close_price}
        for day, open_price, close_price in rows
    ]


def test_verified_replay_uses_executable_open_and_recomputes_cash_reserve():
    trades = [
        {
            "id": 1,
            "trade_date": "2026-08-07",
            "action": "BUY",
            "stock_code": "000001.SZ",
            "stock_name": "first",
            "reason": "ai_score=67.0",
            "created_at": "2026-08-07T08:30:00+08:00",
        },
        {
            "id": 2,
            "trade_date": "2026-08-11",
            "action": "BUY",
            "stock_code": "000002.SZ",
            "stock_name": "second",
            "reason": "ai_score=70.0",
            "created_at": "2026-08-11T21:30:00+08:00",
        },
        {
            "id": 3,
            "trade_date": "2026-08-12",
            "action": "SELL",
            "stock_code": "000001.SZ",
            "stock_name": "first",
            "reason": "restore_min_cash_reserve=10%",
            "created_at": "2026-08-12T08:30:00+08:00",
        },
    ]
    histories = {
        "000001.SZ": _bars([
            ("2026-08-07", 10.0, 10.2),
            ("2026-08-11", 10.3, 10.4),
            ("2026-08-12", 10.5, 10.6),
        ]),
        "000002.SZ": _bars([
            ("2026-08-11", 19.0, 20.0),
            ("2026-08-12", 21.0, 22.0),
        ]),
    }

    rebuilt = replay_legacy_trade_intents(
        trades,
        histories,
        {"000001.SZ": "tencent", "000002.SZ": "tencent"},
    )

    assert rebuilt["trades"][0]["trade_date"] == "2026-08-07"
    assert rebuilt["trades"][0]["price"] == pytest.approx(10.01)
    assert rebuilt["trades"][1]["trade_date"] == "2026-08-12"
    assert rebuilt["trades"][1]["price"] == pytest.approx(21.02)
    assert len(rebuilt["trades"]) == 2
    assert rebuilt["cash"] >= 10_000
    assert rebuilt["summary"]["skipped_legacy_trades"][0]["legacy_trade_id"] == 3


def test_archive_and_replace_preserves_legacy_payload(tmp_path):
    database = MarketDatabase(tmp_path / "archive.db")
    database.ensure_paper_account(100_000)
    with database._get_conn() as connection:
        connection.execute(
            """INSERT INTO paper_position(
                   stock_code, stock_name, shares, avg_cost, updated_at
               ) VALUES ('000001.SZ', 'legacy', 100, 5, '')"""
        )
    rebuilt = {
        "cash": 80_000,
        "positions": [{
            "stock_code": "000002.SZ",
            "stock_name": "verified",
            "shares": 1000,
            "avg_cost": 20,
            "entry_date": "2026-08-13",
            "entry_price_source": "tencent",
        }],
        "trades": [],
        "summary": {"test": True},
    }

    result = database.archive_and_replace_paper_ledger(rebuilt, "test rebuild")
    state = database.get_paper_ledger_state()

    assert result["archive_id"] == 1
    assert state["account"]["ledger_quality"] == "verified_real_prices"
    assert state["paper_position"][0]["stock_code"] == "000002.SZ"
    with database._get_conn() as connection:
        archive = connection.execute(
            "SELECT payload_json FROM paper_ledger_archive WHERE id=1"
        ).fetchone()
    assert "000001.SZ" in archive["payload_json"]


def test_market_open_phase_runs_verified_strategy_after_open():
    from src.ai_os.scheduler import SchedulePhase, get_schedule_for_phase

    tasks = get_schedule_for_phase(SchedulePhase.MARKET_OPEN)

    assert [task.name for task in tasks] == [
        "market_open_check",
        "execute_open_strategy",
    ]
    assert tasks[1].depends_on == ["market_open_check"]
