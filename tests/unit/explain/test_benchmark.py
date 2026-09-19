"""The equal-weight benchmark must never leak future information.

`stock_basic` holds essentially one current snapshot, so filtering a historical
universe with it would use market caps and ST flags that were not knowable on
the decision date.  These tests pin the point-in-time behaviour and the basis
tagging that makes uneven metadata coverage visible instead of silent.
"""

import sqlite3

import pytest

from src.explain.benchmark import (
    BASIS_FILTERED,
    BASIS_UNFILTERED,
    BASIS_UNRELIABLE_ST,
    equal_weight_return,
)


def _schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE market_daily (
            ts_code TEXT, trade_date TEXT, close REAL
        );
        CREATE TABLE stock_metadata_history (
            ts_code TEXT, as_of_date TEXT, market_cap_yi REAL, is_st INTEGER
        );
        """
    )


def _bar(conn, code, day, close):
    conn.execute("INSERT INTO market_daily VALUES (?,?,?)", (code, day, close))


def _meta(conn, code, day, cap, is_st=0):
    conn.execute(
        "INSERT INTO stock_metadata_history VALUES (?,?,?,?)", (code, day, cap, is_st)
    )


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    _schema(c)
    # 1200 metadata rows so the day clears the completeness threshold.
    for i in range(1200):
        _meta(c, f"{i:06d}.SZ", "2026-09-10", 100.0, is_st=1 if i < 200 else 0)
    return c


def _prices(conn, day, codes, close):
    for code in codes:
        _bar(conn, code, day, close)


def test_cap_and_st_filters_both_apply_when_metadata_is_complete(conn):
    codes = [f"{i:06d}.SZ" for i in range(1200)]
    _prices(conn, "2026-09-10", codes, 10.0)
    _prices(conn, "2026-09-17", codes, 11.0)

    _, basis = equal_weight_return(conn, "2026-09-10", "2026-09-17")

    assert basis.status == BASIS_FILTERED
    # 200 ST names dropped; the remaining 1000 all clear the 20亿 floor.
    assert basis.constituent_count == 1000


def test_sub_floor_market_caps_are_excluded(conn):
    codes = [f"{i:06d}.SZ" for i in range(1200)]
    _prices(conn, "2026-09-10", codes, 10.0)
    _prices(conn, "2026-09-17", codes, 11.0)
    conn.execute(
        "UPDATE stock_metadata_history SET market_cap_yi=5.0 WHERE ts_code='000500.SZ'"
    )

    _, basis = equal_weight_return(conn, "2026-09-10", "2026-09-17")

    assert basis.constituent_count == 999


def test_an_all_zero_st_flag_falls_back_to_cap_only(conn):
    # 2026-09-07 .. 09-09 look exactly like this: ~5200 rows, is_st written as 0.
    conn.execute("UPDATE stock_metadata_history SET is_st=0")
    codes = [f"{i:06d}.SZ" for i in range(1200)]
    _prices(conn, "2026-09-10", codes, 10.0)
    _prices(conn, "2026-09-17", codes, 11.0)

    _, basis = equal_weight_return(conn, "2026-09-10", "2026-09-17")

    assert basis.status == BASIS_UNRELIABLE_ST
    assert "st_flag_unpopulated" in basis.reasons
    # The cap filter survives; dropping it too would widen the pool past the
    # unfiltered case rather than narrowing it.
    assert basis.constituent_count == 1200


def test_a_sparse_metadata_day_is_unfiltered(conn):
    conn.execute("DELETE FROM stock_metadata_history WHERE ts_code > '000300.SZ'")
    codes = [f"{i:06d}.SZ" for i in range(1200)]
    _prices(conn, "2026-09-10", codes, 10.0)
    _prices(conn, "2026-09-17", codes, 11.0)

    _, basis = equal_weight_return(conn, "2026-09-10", "2026-09-17")

    assert basis.status == BASIS_UNFILTERED
    assert "metadata_capture_incomplete" in basis.reasons
    assert basis.constituent_count == 1200


def test_no_metadata_at_all_is_unfiltered(conn):
    conn.execute("DELETE FROM stock_metadata_history")
    codes = [f"{i:06d}.SZ" for i in range(50)]
    _prices(conn, "2026-09-10", codes, 10.0)
    _prices(conn, "2026-09-17", codes, 11.0)

    _, basis = equal_weight_return(conn, "2026-09-10", "2026-09-17")

    assert basis.status == BASIS_UNFILTERED
    assert basis.metadata_date is None
    assert "no_point_in_time_metadata" in basis.reasons


def test_metadata_after_the_window_is_never_used(conn):
    # A later snapshot must not back-fill a decision made before it.
    conn.execute("DELETE FROM stock_metadata_history")
    for i in range(1200):
        _meta(conn, f"{i:06d}.SZ", "2026-09-20", 100.0)
    codes = [f"{i:06d}.SZ" for i in range(1200)]
    _prices(conn, "2026-09-10", codes, 10.0)
    _prices(conn, "2026-09-17", codes, 11.0)

    _, basis = equal_weight_return(conn, "2026-09-10", "2026-09-17")

    assert basis.status == BASIS_UNFILTERED
    assert basis.metadata_date is None
    assert basis.constituent_count == 1200


def test_return_is_the_equal_weight_mean(conn):
    conn.execute("DELETE FROM stock_metadata_history")
    for i in range(1200):
        _meta(conn, f"{i:06d}.SZ", "2026-09-10", 100.0)
    _prices(conn, "2026-09-10", ["000001.SZ", "000002.SZ"], 10.0)
    _prices(conn, "2026-09-17", ["000001.SZ"], 11.0)   # +10%
    _prices(conn, "2026-09-17", ["000002.SZ"], 12.0)   # +20%

    value, basis = equal_weight_return(conn, "2026-09-10", "2026-09-17")

    assert value == pytest.approx(0.15)
    assert basis.constituent_count == 2


def test_a_stock_missing_an_endpoint_is_excluded(conn):
    conn.execute("DELETE FROM stock_metadata_history")
    for i in range(1200):
        _meta(conn, f"{i:06d}.SZ", "2026-09-10", 100.0)
    _prices(conn, "2026-09-10", ["000001.SZ", "000002.SZ"], 10.0)
    _prices(conn, "2026-09-17", ["000001.SZ"], 11.0)   # 000002 suspended at the end

    _, basis = equal_weight_return(conn, "2026-09-10", "2026-09-17")

    assert basis.constituent_count == 1


def test_no_constituents_reports_no_value(conn):
    conn.execute("DELETE FROM stock_metadata_history")
    _prices(conn, "2026-09-10", ["000001.SZ"], 10.0)

    value, basis = equal_weight_return(conn, "2026-09-10", "2026-09-17")

    assert value is None
    assert basis.constituent_count == 0
