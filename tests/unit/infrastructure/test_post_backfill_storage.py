from __future__ import annotations

import json
from datetime import date, timedelta

from src.ai_os.post_backfill_rerun import (
    evaluate_post_backfill_gate,
    summarize_latest_backfill,
)
from src.infrastructure.storage.market_database import MarketDatabase


def _dates(count: int, end: date = date(2026, 9, 8)) -> list[str]:
    return [(end - timedelta(days=offset)).isoformat() for offset in range(count)]


def _populate_complete_code(database: MarketDatabase, code: str) -> list[str]:
    days = _dates(250)
    database.upsert_tushare_daily_history([
        {"ts_code": code, "trade_date": day, "open": 1, "high": 1,
         "low": 1, "close": 1, "pre_close": 1}
        for day in days
    ])
    database.upsert_adjustment_factors([
        {"ts_code": code, "trade_date": day, "adj_factor": 1}
        for day in days
    ])
    statements = {
        name: [{"ts_code": code, "end_date": f"202{6 - index}-12-31"}
               for index in range(8)]
        for name in ("income", "balancesheet", "cashflow", "fina_indicator")
    }
    database.upsert_financial_history(code, statements)
    flow_dates = days[:20]
    database.upsert_fund_flow_history([
        {"ts_code": code, "trade_date": day, "main_net": 1, "net_amount": 1}
        for day in flow_dates
    ])
    return days


def test_research_coverage_is_recomputed_from_database(tmp_path):
    database = MarketDatabase(tmp_path / "coverage.db")
    complete = "000001.SZ"
    incomplete = "000002.SZ"
    days = _populate_complete_code(database, complete)
    database.upsert_tushare_daily_history([
        {"ts_code": incomplete, "trade_date": day, "open": 1, "high": 1,
         "low": 1, "close": 1, "pre_close": 1}
        for day in days
    ])

    coverage = database.get_research_component_coverage(
        [complete, incomplete], "2026-09-08", 250, 8, 20
    )

    assert coverage["candidate_count"] == 2
    assert coverage["components"]["daily"]["complete_count"] == 2
    assert coverage["components"]["financial_history"]["complete_count"] == 1
    assert coverage["components"]["fund_flow_history"]["missing_codes"] == [incomplete]
    assert coverage["details"][complete]["fund_flow_history"]["complete"] is True


def test_rerun_claim_is_atomic_and_survives_reopen(tmp_path):
    path = tmp_path / "dispatch.db"
    database = MarketDatabase(path)
    key = "post_backfill_ai_rerun:2026-09-08:run-a:revision-a"

    first = database.claim_research_rerun(key, "2026-09-08", "run-a", "revision-a")
    second = database.claim_research_rerun(key, "2026-09-08", "run-a", "revision-a")
    database.finish_research_rerun(key, "succeeded", {"run_id": "run-b"})
    reopened = MarketDatabase(path)
    third = reopened.claim_research_rerun(key, "2026-09-08", "run-a", "revision-a")

    assert first["claimed"] is True
    assert second == {
        "claimed": False,
        "reason": "already_dispatched",
        "status": "claimed",
        "triggered_at": first["triggered_at"],
        "completed_at": "",
    }
    assert third["claimed"] is False
    assert third["status"] == "succeeded"


def test_latest_run_and_checkpoint_are_not_confused_by_date(tmp_path):
    path = tmp_path / "latest.db"
    database = MarketDatabase(path)
    with database._get_conn() as conn:
        conn.execute(
            """INSERT INTO decision_journal
               (decision_date, stock_code, stock_name, created_at)
               VALUES (?, ?, ?, ?)""",
            ("2026-09-08", "000001.SZ", "Test", "2026-09-08T13:00:00"),
        )
        journal_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO strategy_decision
               (journal_id, decision_date, stock_code, analysis_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (journal_id, "2026-09-08", "000001.SZ",
             json.dumps({"run_id": "run-latest", "run_created_at": "2026-09-08T13:00:00"}),
             "2026-09-08T13:00:00"),
        )

    latest = database.get_latest_strategy_run()

    assert latest["run_id"] == "run-latest"
    assert latest["codes"] == ["000001.SZ"]
    assert latest["run_created_at"] == "2026-09-08T13:00:00"


def test_latest_backfill_summary_reads_database_after_checkpoint_write(tmp_path):
    path = tmp_path / "summary.db"
    database = MarketDatabase(path)
    code = "000001.SZ"
    days = _populate_complete_code(database, code)
    with database._get_conn() as conn:
        conn.execute(
            """INSERT INTO decision_journal
               (decision_date, stock_code, stock_name, created_at)
               VALUES (?, ?, ?, ?)""",
            ("2026-09-08", code, "Test", "2026-09-08T13:00:00"),
        )
        journal_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO strategy_decision
               (journal_id, decision_date, stock_code, analysis_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (journal_id, "2026-09-08", code,
             json.dumps({"run_id": "run-latest", "run_created_at": "2026-09-08T13:00:00"}),
             "2026-09-08T13:00:00"),
        )
    database.save_completion_checkpoint(
        "research_data_backfill", "candidate",
        "20260906-v3:candidate:run-latest:1:2026-09-08:250:8:20",
        {"codes": [code], "completed": [code], "results": {}},
        "completed",
    )

    summary = summarize_latest_backfill(database)
    gate = evaluate_post_backfill_gate(
        summary, previous_ai_run_created_at="2026-09-08T13:00:00"
    )

    assert summary["candidate_count"] == 1
    assert summary["complete_candidate_count"] == 1
    assert all(
        item["coverage"] == 1.0
        for item in summary["component_coverage"].values()
    )
    assert gate["eligible"] is True


def test_force_reanalysis_reservation_bypasses_prior_budget_usage_but_stays_bounded(
    tmp_path,
):
    database = MarketDatabase(tmp_path / "force-rerun.db")
    prior = [{"stock_code": "000001.SZ"}]
    candidates = [
        {"stock_code": "000002.SZ"},
        {"stock_code": "000003.SZ"},
    ]
    fingerprints = {
        "000001.SZ": "revision-a",
        "000002.SZ": "revision-b",
        "000003.SZ": "revision-c",
    }

    database.reserve_deep_analysis_slots(
        "2026-09-08", "manual", prior, fingerprints,
        window_limit=1, daily_limit=1,
    )

    blocked = database.reserve_deep_analysis_slots(
        "2026-09-08", "manual", candidates, fingerprints,
        window_limit=1, daily_limit=1,
    )
    forced = database.reserve_deep_analysis_slots(
        "2026-09-08", "manual", candidates, fingerprints,
        window_limit=1, daily_limit=1,
        override_daily_limit=True,
        override_window_usage=True,
    )
    duplicate = database.reserve_deep_analysis_slots(
        "2026-09-08", "manual", [candidates[0]], fingerprints,
        window_limit=1, daily_limit=1,
        override_daily_limit=True,
        override_window_usage=True,
    )

    assert blocked["selected"] == []
    assert forced["selected"] == [candidates[0]]
    assert forced["skipped"] == 1
    assert duplicate["selected"] == []
