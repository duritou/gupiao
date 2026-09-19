"""Calibration must read one row per decision, not one per scan.

Several scans run each day and the journal historically kept a row per scan.
`get_pending_market_learning_decisions` guards against that with a
`ROW_NUMBER` partition, but `get_research_case_rows` -- the query that rebuilds
the in-memory case library on startup, and therefore the sole input to
`/calibration`, `/annual-report` and `/cases` -- did not.  Reading the
duplicates raw inflated the library ~2.4x and weighted the confidence
calibration curve by scan count instead of by decision.

The rows are inserted with raw SQL on purpose: `save_decisions_batch` now
upserts on `(decision_date, stock_code)`, so it can no longer produce the
duplicates this guard exists to collapse.  Those already in the database are
what it has to handle.
"""

import sqlite3

import pytest

from src.infrastructure.storage.market_database import MarketDatabase


def _raw(db_path, sql: str, params: tuple = ()):
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def _query(db_path, sql: str, params: tuple = ()):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _insert_scan(db_path, decision_date: str, code: str, direction: str = "buy",
                 confidence: float = 0.55, outcome_known: int = 0) -> int:
    """Insert one journal row the way the pre-upsert write path did."""
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            """INSERT INTO decision_journal
               (decision_date, stock_code, stock_name, ai_score, direction,
                confidence, recommendation, evidence, created_at, outcome_known)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (decision_date, code, code, 70.0, direction, confidence, "买入",
             "{}", f"{decision_date}T09:35:00+08:00", outcome_known),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


@pytest.fixture()
def database(tmp_path):
    return MarketDatabase(tmp_path / "case-rows-dedup.db")


def test_repeated_scans_of_one_day_collapse_to_one_case(database):
    # Three scans of the same day, same stock -- as the historical data has.
    for _ in range(3):
        _insert_scan(database.db_path, "2026-08-10", "000001.SZ")

    assert _query(database.db_path, "SELECT COUNT(*) FROM decision_journal")[0][0] == 3

    rows = database.get_research_case_rows()

    assert len(rows) == 1
    assert rows[0]["stock_code"] == "000001.SZ"


def test_distinct_days_and_codes_are_each_kept(database):
    _insert_scan(database.db_path, "2026-08-10", "000001.SZ")
    _insert_scan(database.db_path, "2026-08-10", "000001.SZ")   # duplicate scan
    _insert_scan(database.db_path, "2026-08-10", "600000.SH")
    _insert_scan(database.db_path, "2026-08-11", "000001.SZ")

    rows = database.get_research_case_rows()
    keys = sorted((row["decision_date"], row["stock_code"]) for row in rows)

    assert keys == [
        ("2026-08-10", "000001.SZ"),
        ("2026-08-10", "600000.SH"),
        ("2026-08-11", "000001.SZ"),
    ]


def test_the_latest_scan_of_the_day_is_the_case_kept(database):
    _insert_scan(database.db_path, "2026-08-10", "000001.SZ", confidence=0.51)
    latest = _insert_scan(database.db_path, "2026-08-10", "000001.SZ", confidence=0.77)

    rows = database.get_research_case_rows()

    assert len(rows) == 1
    assert rows[0]["id"] == latest
    assert rows[0]["confidence"] == 0.77


def test_directionless_rows_are_excluded(database):
    _insert_scan(database.db_path, "2026-08-10", "000001.SZ", direction="neutral")
    _insert_scan(database.db_path, "2026-08-10", "600000.SH", direction="buy")

    rows = database.get_research_case_rows()

    assert [row["stock_code"] for row in rows] == ["600000.SH"]


def test_calibration_population_shrinks_to_distinct_decisions(database):
    # The distortion this guard removes: duplicates must not reach calibration.
    for _ in range(4):
        _insert_scan(database.db_path, "2026-08-10", "000001.SZ", outcome_known=1)

    rows = database.get_research_case_rows()

    assert len([r for r in rows if r["outcome_known"]]) == 1
