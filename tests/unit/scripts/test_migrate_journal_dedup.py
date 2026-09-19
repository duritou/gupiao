"""The migration must be provably safe before it is pointed at real data.

It runs one transaction and only commits when the UNIQUE index builds, which is
the acceptance test: a missed duplicate makes the index fail and rolls
everything back.  These tests run it on a synthetic journal and check the
outcome, the dry-run, and the refusal paths.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.migrate_journal_dedup import migrate  # noqa: E402


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(
        """
        CREATE TABLE decision_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_date TEXT NOT NULL, stock_code TEXT NOT NULL,
            stock_name TEXT, direction TEXT,
            outcome_known INTEGER DEFAULT 0, was_correct INTEGER,
            actual_return REAL, outcome_checked_at TEXT,
            created_at TEXT
        );
        CREATE TABLE strategy_decision (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            journal_id INTEGER, decision_date TEXT, stock_code TEXT,
            strategy_name TEXT, analysis_json TEXT,
            UNIQUE(decision_date, stock_code, strategy_name)
        );
        CREATE TABLE paper_trade (
            id INTEGER PRIMARY KEY AUTOINCREMENT, decision_id INTEGER, action TEXT
        );
        CREATE TABLE market_learning_observation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_id INTEGER NOT NULL, horizon_days INTEGER NOT NULL,
            UNIQUE(decision_id, horizon_days)
        );
        """
    )
    return c


def _journal(conn, day, code, outcome=None, direction="buy"):
    cursor = conn.execute(
        """INSERT INTO decision_journal
           (decision_date, stock_code, stock_name, direction, outcome_known,
            was_correct, actual_return, created_at)
           VALUES (?,?,?,?,?,?,?,'t')""",
        (day, code, code, direction, 1 if outcome is not None else 0,
         1 if outcome is not None else None, outcome),
    )
    return int(cursor.lastrowid)


def _sd(conn, journal_id, day, code, size=10):
    conn.execute(
        """INSERT INTO strategy_decision
           (journal_id, decision_date, stock_code, strategy_name, analysis_json)
           VALUES (?,?,?,?,?)""",
        (journal_id, day, code, f"adaptive-paper:journal:{journal_id}", "x" * size),
    )


def test_a_clean_journal_is_left_alone(conn):
    row = _journal(conn, "2026-09-01", "000001.SZ")
    _sd(conn, row, "2026-09-01", "000001.SZ")

    result = migrate(conn, confirm=True, backup=False)

    assert result["journal_rows_deleted"] == 0
    assert result["committed"] is True


def test_duplicates_collapse_and_the_index_gets_created(conn):
    for _ in range(4):
        row = _journal(conn, "2026-09-01", "000001.SZ")
        _sd(conn, row, "2026-09-01", "000001.SZ")

    result = migrate(conn, confirm=True, backup=False)

    assert result["journal_rows_after"] == 1
    assert result["committed"] is True
    assert conn.execute("SELECT COUNT(*) FROM decision_journal").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM strategy_decision").fetchone()[0] == 1
    indexes = [r[1] for r in conn.execute("PRAGMA index_list(decision_journal)")]
    assert "idx_decision_journal_unique" in indexes


def test_a_dry_run_changes_nothing(conn):
    for _ in range(3):
        row = _journal(conn, "2026-09-01", "000001.SZ")
        _sd(conn, row, "2026-09-01", "000001.SZ")

    result = migrate(conn, confirm=False, backup=False)

    assert result["committed"] is False
    assert conn.execute("SELECT COUNT(*) FROM decision_journal").fetchone()[0] == 3


def test_an_outcome_only_on_a_doomed_row_survives(conn):
    _journal(conn, "2026-09-01", "000001.SZ", outcome=0.042)
    survivor = _journal(conn, "2026-09-01", "000001.SZ")

    migrate(conn, confirm=True, backup=False)

    row = conn.execute(
        "SELECT outcome_known, actual_return FROM decision_journal WHERE id=?",
        (survivor,),
    ).fetchone()
    assert row["outcome_known"] == 1
    assert row["actual_return"] == 0.042


def test_trades_are_repointed_not_orphaned(conn):
    doomed = _journal(conn, "2026-09-01", "000001.SZ")
    survivor = _journal(conn, "2026-09-01", "000001.SZ")
    conn.execute(
        "INSERT INTO paper_trade (decision_id, action) VALUES (?,'BUY')", (doomed,)
    )

    migrate(conn, confirm=True, backup=False)

    assert conn.execute("SELECT COUNT(*) FROM paper_trade").fetchone()[0] == 1
    assert conn.execute("SELECT decision_id FROM paper_trade").fetchone()[0] == survivor


def test_colliding_observations_are_deduplicated(conn):
    doomed = _journal(conn, "2026-09-01", "000001.SZ")
    survivor = _journal(conn, "2026-09-01", "000001.SZ")
    for decision in (doomed, survivor):
        conn.execute(
            "INSERT INTO market_learning_observation (decision_id, horizon_days)"
            " VALUES (?,1)", (decision,),
        )

    migrate(conn, confirm=True, backup=False)

    rows = conn.execute(
        "SELECT decision_id, horizon_days FROM market_learning_observation"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["decision_id"] == survivor


def test_strategy_rows_are_renamed_onto_the_survivor(conn):
    doomed = _journal(conn, "2026-09-01", "000001.SZ")
    survivor = _journal(conn, "2026-09-01", "000001.SZ")
    _sd(conn, doomed, "2026-09-01", "000001.SZ", size=500)
    _sd(conn, survivor, "2026-09-01", "000001.SZ", size=10)

    migrate(conn, confirm=True, backup=False)

    row = conn.execute(
        "SELECT journal_id, strategy_name, analysis_json FROM strategy_decision"
    ).fetchone()
    assert row["journal_id"] == survivor
    assert row["strategy_name"] == f"adaptive-paper:journal:{survivor}"
    assert len(row["analysis_json"]) == 500   # the richer packet was kept


def test_distinct_days_and_codes_are_each_kept(conn):
    for day, code in (("2026-09-01", "000001.SZ"), ("2026-09-01", "600000.SH"),
                      ("2026-09-02", "000001.SZ")):
        row = _journal(conn, day, code)
        _sd(conn, row, day, code)

    migrate(conn, confirm=True, backup=False)

    assert conn.execute("SELECT COUNT(*) FROM decision_journal").fetchone()[0] == 3


def test_the_index_blocks_a_new_duplicate_afterwards(conn):
    row = _journal(conn, "2026-09-01", "000001.SZ")
    _sd(conn, row, "2026-09-01", "000001.SZ")
    migrate(conn, confirm=True, backup=False)

    # The constraint is what the migration was for: it must now reject the
    # very row shape that used to be inserted freely.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO decision_journal (decision_date, stock_code, created_at)"
            " VALUES ('2026-09-01','000001.SZ','t')"
        )
