"""The de-duplication plan must account for every row before anyone runs it.

There are no declared foreign keys in this schema, so a mis-aimed reference is
silent corruption rather than an error.  The plan's conservation buckets are the
guard: each table's rows must be partitioned into disjoint, exhaustive buckets.
These tests check the plan against hand-computed numbers on a synthetic journal.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.plan_journal_dedup import build_plan  # noqa: E402


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(
        """
        CREATE TABLE decision_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_date TEXT, stock_code TEXT,
            outcome_known INTEGER DEFAULT 0, actual_return REAL
        );
        CREATE TABLE strategy_decision (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            journal_id INTEGER, analysis_json TEXT
        );
        CREATE TABLE paper_trade (
            id INTEGER PRIMARY KEY AUTOINCREMENT, decision_id INTEGER
        );
        CREATE TABLE market_learning_observation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_id INTEGER, horizon_days INTEGER
        );
        """
    )
    return c


def _journal(conn, day, code, outcome=None):
    cursor = conn.execute(
        "INSERT INTO decision_journal (decision_date, stock_code, outcome_known, actual_return)"
        " VALUES (?,?,?,?)",
        (day, code, 1 if outcome is not None else 0, outcome),
    )
    return int(cursor.lastrowid)


def _sd(conn, journal_id, size=10):
    cursor = conn.execute(
        "INSERT INTO strategy_decision (journal_id, analysis_json) VALUES (?,?)",
        (journal_id, "x" * size),
    )
    return int(cursor.lastrowid)


def test_no_duplicates_is_a_no_op(conn):
    first = _journal(conn, "2026-09-01", "000001.SZ")
    _sd(conn, first)

    plan = build_plan(conn)

    assert plan["duplicate_groups"] == 0
    assert plan["journal_rows_deleted"] == 0
    assert plan["strategy_rows_deleted"] == 0
    assert plan["conservation_ok"] is True


def test_the_latest_write_survives(conn):
    _journal(conn, "2026-09-01", "000001.SZ")
    keeper = _journal(conn, "2026-09-01", "000001.SZ")

    plan = build_plan(conn)

    assert plan["journal_rows_deleted"] == 1
    assert plan["unique_groups"] == 1
    # The surviving row is the one every count is expressed against.
    assert keeper  # the second insert


def test_an_outcome_only_on_a_doomed_row_is_merged_forward(conn):
    _journal(conn, "2026-09-01", "000001.SZ", outcome=0.05)
    _journal(conn, "2026-09-01", "000001.SZ")   # survives, carries no outcome

    plan = build_plan(conn)

    assert plan["outcomes_merged_forward"] == 1
    assert plan["outcome_conflicts"] == 0


def test_disagreeing_outcomes_are_reported_as_conflicts(conn):
    _journal(conn, "2026-09-01", "000001.SZ", outcome=0.05)
    _journal(conn, "2026-09-01", "000001.SZ", outcome=-0.05)

    plan = build_plan(conn)

    assert plan["outcome_conflicts"] == 1
    assert plan["conservation_ok"] is True  # a conflict is reported, not hidden


def test_the_richest_packet_wins_over_the_survivors_own(conn):
    doomed = _journal(conn, "2026-09-01", "000001.SZ")
    survivor = _journal(conn, "2026-09-01", "000001.SZ")
    _sd(conn, doomed, size=500)      # richer, but on the row being deleted
    _sd(conn, survivor, size=10)

    plan = build_plan(conn)

    # Keeping the survivor's own row would drop the richer packet.
    assert plan["strategy_rows_repointed"] == 1
    assert plan["strategy_rows_deleted"] == 1


def test_a_survivor_without_its_own_packet_is_reported(conn):
    doomed = _journal(conn, "2026-09-01", "000001.SZ")
    _journal(conn, "2026-09-01", "000001.SZ")   # survivor, owns no packet
    _sd(conn, doomed)

    plan = build_plan(conn)

    assert plan["groups_survivor_had_no_strategy_row"] == 1
    # It must be re-pointed, not merely deleted, or the group loses its packet.
    assert plan["strategy_rows_repointed"] == 1
    assert plan["strategy_rows_deleted"] == 0


def test_trades_are_repointed_and_never_deleted(conn):
    doomed = _journal(conn, "2026-09-01", "000001.SZ")
    _journal(conn, "2026-09-01", "000001.SZ")
    conn.execute("INSERT INTO paper_trade (decision_id) VALUES (?)", (doomed,))

    plan = build_plan(conn)

    assert plan["trades_repointed"] == 1
    assert plan["conservation"]["paper_trade"]["deleted"] == 0
    assert plan["conservation"]["paper_trade"]["sums"] is True


def test_colliding_observations_are_deduplicated_not_orphaned(conn):
    doomed = _journal(conn, "2026-09-01", "000001.SZ")
    survivor = _journal(conn, "2026-09-01", "000001.SZ")
    for decision in (doomed, survivor):
        conn.execute(
            "INSERT INTO market_learning_observation (decision_id, horizon_days) VALUES (?,1)",
            (decision,),
        )

    plan = build_plan(conn)

    assert plan["observation_unique_collisions"] == 1
    assert plan["observations_deleted"] == 1
    assert plan["conservation"]["market_learning_observation"]["sums"] is True


def test_conservation_holds_on_a_mixed_journal(conn):
    # Two groups: one clean, one with three scans, a trade, and two horizons.
    clean = _journal(conn, "2026-09-01", "000001.SZ")
    _sd(conn, clean)
    for outcome in (None, 0.02, None):
        row = _journal(conn, "2026-09-02", "600000.SH", outcome=outcome)
        _sd(conn, row, size=20)
    doomed = conn.execute(
        "SELECT id FROM decision_journal WHERE decision_date='2026-09-02' ORDER BY id LIMIT 1"
    ).fetchone()[0]
    conn.execute("INSERT INTO paper_trade (decision_id) VALUES (?)", (doomed,))
    for horizon in (1, 20):
        conn.execute(
            "INSERT INTO market_learning_observation (decision_id, horizon_days) VALUES (?,?)",
            (doomed, horizon),
        )

    plan = build_plan(conn)

    assert plan["conservation_ok"] is True
    for table, buckets in plan["conservation"].items():
        assert buckets["sums"], table
        assert buckets["no_negatives"], table
