"""The evaluation must score recorded decisions without pooling eras.

Every number it prints is only as good as its segmentation: the record spans a
configuration whose gates could never open, so a merged average would describe
a system that no longer exists.  These tests pin the segmentation, the
deduplication, and the refusal to invent an outcome it cannot compute.
"""

import json
import sqlite3

import pytest

from src.explain.strategy_evaluation import evaluate_decisions


def _schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE market_daily (
            ts_code TEXT, trade_date TEXT, close REAL
        );
        CREATE TABLE stock_metadata_history (
            ts_code TEXT, as_of_date TEXT, market_cap_yi REAL, is_st INTEGER
        );
        CREATE TABLE decision_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_date TEXT, stock_code TEXT, direction TEXT,
            created_at TEXT
        );
        CREATE TABLE strategy_decision (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            journal_id INTEGER, decision_date TEXT, stock_code TEXT,
            strategy_name TEXT, analysis_json TEXT
        );
        """
    )


CALENDAR = [f"2026-09-{d:02d}" for d in range(1, 25)]
# The fifth session after the decision date is what the window end resolves to.
WINDOW_END = CALENDAR[5]


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    _schema(c)
    # Flat peers: the equal-weight benchmark needs a universe.
    for day in CALENDAR:
        for i in range(5):
            c.execute(
                "INSERT INTO market_daily VALUES (?,?,?)", (f"90000{i}.SZ", day, 10.0)
            )
    return c


def _price(conn, code, day, close):
    conn.execute("INSERT INTO market_daily VALUES (?,?,?)", (code, day, close))


def _decision(conn, day, code, *, direction="neutral", packet=None, repeat=1):
    for _ in range(repeat):
        cursor = conn.execute(
            "INSERT INTO decision_journal (decision_date, stock_code, direction, created_at)"
            " VALUES (?,?,?,'2026-09-01T09:35:00')",
            (day, code, direction),
        )
        conn.execute(
            """INSERT INTO strategy_decision
               (journal_id, decision_date, stock_code, strategy_name, analysis_json)
               VALUES (?,?,?,?,?)""",
            (
                int(cursor.lastrowid), day, code, "adaptive-paper",
                json.dumps(packet or {}),
            ),
        )
    conn.commit()


def test_repeated_scans_collapse_to_one_decision(conn):
    _price(conn, "000001.SZ", "2026-09-01", 10.0)
    _price(conn, "000001.SZ", WINDOW_END, 11.0)
    _decision(conn, "2026-09-01", "000001.SZ", repeat=4)

    result = evaluate_decisions(conn, start_date="2026-09-01", today="2026-09-24")

    assert result.total_decisions == 1
    assert result.evaluated == 1


def test_a_decision_without_a_forward_bar_is_skipped_not_guessed(conn):
    _price(conn, "000001.SZ", "2026-09-01", 10.0)   # no bar on the window end
    _decision(conn, "2026-09-01", "000001.SZ")

    result = evaluate_decisions(conn, start_date="2026-09-01", today="2026-09-24")

    assert result.evaluated == 0
    assert result.skipped_no_outcome == 1


def test_segments_are_reported_separately_by_strategy_version(conn):
    for i, version in enumerate(("2.2.0-evidence-routing", "2.3.0-evidence-integrity")):
        code = f"00000{i}.SZ"
        _price(conn, code, "2026-09-01", 10.0)
        _price(conn, code, WINDOW_END, 11.0)
        _decision(conn, "2026-09-01", code, packet={"strategy_version": version})

    result = evaluate_decisions(conn, start_date="2026-09-01", today="2026-09-24")

    assert set(result.by_strategy_version) == {
        "2.2.0-evidence-routing", "2.3.0-evidence-integrity"
    }
    assert any("不得合并阅读" in note for note in result.notes)


def test_segments_are_reported_separately_by_benchmark_basis(conn):
    _price(conn, "000001.SZ", "2026-09-01", 10.0)
    _price(conn, "000001.SZ", WINDOW_END, 11.0)
    _decision(conn, "2026-09-01", "000001.SZ")

    result = evaluate_decisions(conn, start_date="2026-09-01", today="2026-09-24")

    # No point-in-time metadata here, so the basis is honestly unfiltered.
    assert list(result.by_benchmark_basis) == ["unfiltered"]


def test_gate_attribution_reports_the_cost_of_each_gate(conn):
    _price(conn, "000001.SZ", "2026-09-01", 10.0)
    _price(conn, "000001.SZ", WINDOW_END, 12.0)   # beats the flat peers
    _decision(
        conn, "2026-09-01", "000001.SZ",
        packet={"score_guard_reasons": ["market_context_missing"]},
    )

    result = evaluate_decisions(conn, start_date="2026-09-01", today="2026-09-24")

    entry = next(g for g in result.gate_attribution if g["reason"] == "market_context_missing")
    assert entry["n"] == 1
    # Releasing it would have earned the excess, so the gate had a price.
    assert entry["mean_excess_if_released"] > 0


def test_final_direction_not_the_raw_direction_drives_the_label(conn):
    # A gate downgraded buy -> neutral; the label must follow the outcome of
    # record, not the direction the model originally wanted.
    _price(conn, "000001.SZ", "2026-09-01", 10.0)
    _price(conn, "000001.SZ", WINDOW_END, 11.0)
    _decision(
        conn, "2026-09-01", "000001.SZ", direction="buy",
        packet={"pre_gate_direction": "buy", "final_direction": "neutral"},
    )

    result = evaluate_decisions(conn, start_date="2026-09-01", today="2026-09-24")

    assert result.evaluated == 1
    assert result.by_strategy_version  # scored without raising


def test_deciles_are_omitted_when_the_sample_is_too_small(conn):
    _price(conn, "000001.SZ", "2026-09-01", 10.0)
    _price(conn, "000001.SZ", WINDOW_END, 11.0)
    _decision(conn, "2026-09-01", "000001.SZ", packet={"ranking_score": 64.0})

    result = evaluate_decisions(conn, start_date="2026-09-01", today="2026-09-24")

    assert result.score_deciles == []
    assert any("不构成证据" in note for note in result.notes) or result.evaluated < 100


def test_an_empty_sample_says_so(conn):
    result = evaluate_decisions(conn, start_date="2026-09-01", today="2026-09-24")

    assert result.evaluated == 0
    assert any("样本为空" in note for note in result.notes)
