from __future__ import annotations

import json
import sqlite3

from scripts.backfill_research_data import _codes_from_source


def test_candidate_selection_is_exactly_scoped_to_run_id(tmp_path):
    path = tmp_path / "decisions.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE strategy_decision (
                id INTEGER PRIMARY KEY,
                decision_date TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                analysis_json TEXT NOT NULL
            );
            CREATE TABLE paper_position (stock_code TEXT, shares INTEGER);
            CREATE TABLE market_daily (ts_code TEXT, trade_date TEXT);
            """
        )
        for index, (code, run_id) in enumerate(
            (("000001.SZ", "run-a"), ("000002.SZ", "run-a"), ("600000.SH", "run-b")),
            start=1,
        ):
            conn.execute(
                "INSERT INTO strategy_decision VALUES (?, ?, ?, ?)",
                (index, "2026-09-04", code, json.dumps({"run_id": run_id})),
            )
        conn.commit()

    codes, selection = _codes_from_source(path, "candidate", 300, "run-a")

    assert codes == ["000001.SZ", "000002.SZ"]
    assert selection["run_id"] == "run-a"
    assert selection["candidate_selection_exact"] is True


def test_default_selection_uses_latest_run_across_decision_dates(tmp_path):
    path = tmp_path / "decisions.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE strategy_decision (
                id INTEGER PRIMARY KEY,
                decision_date TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                analysis_json TEXT NOT NULL
            );
            CREATE TABLE paper_position (stock_code TEXT, shares INTEGER);
            CREATE TABLE market_daily (ts_code TEXT, trade_date TEXT);
            """
        )
        rows = [
            (1, "2026-09-05", "000001.SZ", "run-old"),
            (2, "2026-09-06", "000002.SZ", "run-new"),
        ]
        conn.executemany(
            "INSERT INTO strategy_decision VALUES (?, ?, ?, ?)",
            [(i, day, code, json.dumps({"run_id": run})) for i, day, code, run in rows],
        )
        conn.commit()

    codes, selection = _codes_from_source(path, "candidate", 300)

    assert codes == ["000002.SZ"]
    assert selection["run_id"] == "run-new"


def test_position_is_appended_without_evicting_candidate_batch(tmp_path):
    path = tmp_path / "decisions.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE strategy_decision (
                id INTEGER PRIMARY KEY,
                decision_date TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                analysis_json TEXT NOT NULL
            );
            CREATE TABLE paper_position (stock_code TEXT, shares INTEGER);
            CREATE TABLE market_daily (ts_code TEXT, trade_date TEXT);
            """
        )
        conn.execute(
            "INSERT INTO strategy_decision VALUES "
            "(1, '2026-09-06', '000001.SZ', '{\"run_id\":\"run-a\"}')"
        )
        conn.execute("INSERT INTO paper_position VALUES ('600000.SH', 100)")
        conn.commit()

    codes, selection = _codes_from_source(path, "candidate", 1, "run-a")

    assert codes == ["000001.SZ", "600000.SH"]
    assert selection["candidate_count"] == 1
    assert selection["position_count"] == 1


def test_checkpoint_args_carry_a_bounded_recovery_budget():
    from scripts.backfill_research_data import _args_from_checkpoint

    args = _args_from_checkpoint(
        "source.db", "out", "20260906-v3:candidate:run-a:300:2026-09-04:250:8:20",
        write_production=False, confirm_production=False, batch_deadline_seconds=60,
    )
    assert args is not None
    assert args.batch_deadline_seconds == 60
    assert args.lease_seconds >= 300
