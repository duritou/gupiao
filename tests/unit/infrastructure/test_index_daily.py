"""Reference indices live in their own table and never enter the scan pool.

The learning label scores against the equal-weight universe, so these bars are
for human comparison only.  They are stored rather than fetched per run because
the 沪深300 series used to exist nowhere but in one backfill's memory, making a
comparison depend on whether that run's network fetch happened to succeed.
"""

import pytest

from src.infrastructure.storage.market_database import MarketDatabase


def _bar(code: str, day: str, close: float) -> dict:
    return {
        "ts_code": code,
        "trade_date": day,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "pre_close": close,
        "change_pct": 0,
        "volume": 1000,
        "amount": 10000,
    }


@pytest.fixture()
def database(tmp_path):
    return MarketDatabase(tmp_path / "index.db")


def test_index_bars_round_trip(database):
    database.upsert_index_daily([_bar("000300.SH", "2026-09-01", 4000.0)])

    bars = database.get_index_bars("000300.SH")

    assert [b["trade_date"] for b in bars] == ["2026-09-01"]
    assert bars[0]["close"] == 4000.0


def test_existing_bars_are_never_overwritten(database):
    # A later fetch must not rewrite history that is already stored.
    database.upsert_index_daily([_bar("000300.SH", "2026-09-01", 4000.0)])

    result = database.upsert_index_daily([_bar("000300.SH", "2026-09-01", 9999.0)])

    assert result["stored_count"] == 0
    assert database.get_index_bars("000300.SH")[0]["close"] == 4000.0


def test_bars_are_returned_ascending(database):
    database.upsert_index_daily([
        _bar("000300.SH", "2026-09-03", 3.0),
        _bar("000300.SH", "2026-09-01", 1.0),
        _bar("000300.SH", "2026-09-02", 2.0),
    ])

    days = [b["trade_date"] for b in database.get_index_bars("000300.SH")]

    assert days == ["2026-09-01", "2026-09-02", "2026-09-03"]


def test_indices_do_not_leak_into_the_stock_bar_table(database):
    # An index in market_daily would be scanned as a tradeable candidate.
    database.upsert_index_daily([_bar("000300.SH", "2026-09-01", 4000.0)])

    assert database.get_daily_bars("000300.SH") == []


def test_coverage_reports_the_stored_window(database):
    assert database.get_index_coverage("000300.SH")["bars"] == 0

    database.upsert_index_daily([
        _bar("000300.SH", "2026-09-01", 1.0),
        _bar("000300.SH", "2026-09-08", 2.0),
    ])

    coverage = database.get_index_coverage("000300.SH")
    assert coverage["bars"] == 2
    assert coverage["first_date"] == "2026-09-01"
    assert coverage["last_date"] == "2026-09-08"


def test_a_row_without_a_close_is_skipped(database):
    rows = [_bar("000300.SH", "2026-09-01", 4000.0)]
    rows.append({**_bar("000300.SH", "2026-09-02", 4000.0), "close": None})

    result = database.upsert_index_daily(rows)

    assert result["stored_count"] == 1
    assert result["input_count"] == 2
