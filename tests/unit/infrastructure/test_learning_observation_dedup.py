"""One real call must produce one learning observation, not one per scan.

Several scans run each day and `save_decisions_batch` used to append a row per
scan, so the same `(decision_date, stock_code)` accumulated many rows.  The
pending queue joined on `decision_id`, which differs per row, so every
duplicate became its own sample for `market_learning`.

The write side now upserts on `(decision_date, stock_code)` and reuses the
existing row id, so a repeated scan collapses before the queue is consulted and
the read-side guard below is the second line of defence rather than the first.
"""

import sqlite3

import pytest

from src.infrastructure.storage.market_database import MarketDatabase


def _journal_row(decision_date: str, code: str, direction: str = "buy") -> dict:
    # The journal stores `decision.get("date")` as decision_date, and
    # `signal_at` as created_at -- both are set by the pipeline.
    return {
        "date": decision_date,
        "signal_at": f"{decision_date}T09:35:00+08:00",
        "stock_code": code,
        "stock_name": code,
        "ai_score": 70.0,
        "direction": direction,
        "confidence": 0.7,
        "recommendation": "买入",
        "fusion_score": 70.0,
        "macd_score": 70.0,
        "rsi_score": 70.0,
        "kdj_score": 70.0,
        "ma_score": 70.0,
        "volume_score": 70.0,
        "buy_signals": 2,
        "sell_signals": 0,
        "evidence": "{}",
        "created_at": f"{decision_date}T09:35:00+08:00",
    }


def _raw(db_path, sql: str, params: tuple = ()):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


@pytest.fixture()
def database(tmp_path):
    return MarketDatabase(tmp_path / "learning-dedup.db")


def test_repeated_scans_of_one_day_yield_a_single_observation(database):
    # Same trading day, same stock, three scans -- as the scheduler produces.
    database.save_decisions_batch([
        _journal_row("2026-08-10", "000001.SZ"),
        _journal_row("2026-08-10", "000001.SZ"),
        _journal_row("2026-08-10", "000001.SZ"),
    ])
    # The write side upserts on (decision_date, stock_code), so the three scans
    # collapse to one row before the pending queue is even consulted.
    assert _raw(database.db_path, "SELECT COUNT(*) FROM decision_journal")[0][0] == 1

    pending = database.get_pending_market_learning_decisions(horizon_days=1)

    assert [row["stock_code"] for row in pending] == ["000001.SZ"]


def test_distinct_days_and_codes_are_each_kept(database):
    database.save_decisions_batch([
        _journal_row("2026-08-10", "000001.SZ"),
        _journal_row("2026-08-10", "000001.SZ"),   # duplicate scan
        _journal_row("2026-08-10", "600000.SH"),
        _journal_row("2026-08-11", "000001.SZ"),
    ])

    pending = database.get_pending_market_learning_decisions(horizon_days=1)
    keys = sorted((row["decision_date"], row["stock_code"]) for row in pending)

    assert keys == [
        ("2026-08-10", "000001.SZ"),
        ("2026-08-10", "600000.SH"),
        ("2026-08-11", "000001.SZ"),
    ]


def test_the_latest_scan_of_the_day_is_the_one_observed(database):
    database.save_decisions_batch([_journal_row("2026-08-10", "000001.SZ")])
    database.save_decisions_batch(
        [_journal_row("2026-08-10", "000001.SZ", direction="sell")]
    )

    pending = database.get_pending_market_learning_decisions(horizon_days=1)

    assert len(pending) == 1
    assert pending[0]["direction"] == "sell"


def test_neutral_calls_are_still_excluded(database):
    database.save_decisions_batch([
        _journal_row("2026-08-10", "000001.SZ", direction="neutral"),
        _journal_row("2026-08-10", "600000.SH", direction="buy"),
    ])

    pending = database.get_pending_market_learning_decisions(horizon_days=1)

    assert [row["stock_code"] for row in pending] == ["600000.SH"]
