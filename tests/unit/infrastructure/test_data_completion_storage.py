from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.infrastructure.market_data.data_completion_service import (
    _coverage_status,
    error_detail,
)
from src.infrastructure.market_data.flow_batch_backfill import (
    backfill_fund_flow_history,
)
from src.infrastructure.storage.market_database import MarketDatabase


def test_completion_status_does_not_call_partial_data_available():
    assert _coverage_status(complete=True, has_data=True) == "available"
    assert _coverage_status(complete=False, has_data=True) == "partial"
    assert _coverage_status(complete=False, has_data=False) == "empty"


def test_error_detail_redacts_credentials_and_keeps_exception_type():
    detail = error_detail(
        RuntimeError("token=secret-value https://example.test/a?token=secret")
    )
    assert detail["error_type"] == "RuntimeError"
    assert "secret-value" not in detail["error_message"]
    assert "[REDACTED]" in detail["error_message"]


def test_history_tables_are_idempotent_and_keep_raw_bars_separate(tmp_path):
    database = MarketDatabase(tmp_path / "market.db")
    code = "600519.SH"
    bars = [
        {
            "ts_code": code, "trade_date": "2026-08-21", "open": 10,
            "high": 11, "low": 9, "close": 10.5, "pre_close": 10,
            "change_pct": 5, "volume": 100, "amount": 200,
        },
        {
            "ts_code": code, "trade_date": "2026-08-22", "open": 10.5,
            "high": 11, "low": 10, "close": 10.8, "pre_close": 10.5,
            "change_pct": 2.85, "volume": 110, "amount": 220,
        },
    ]

    assert database.upsert_tushare_daily_history(bars)["stored_count"] == 2
    assert database.upsert_tushare_daily_history(bars)["stored_count"] == 0
    assert database.upsert_adjustment_factors([
        {"ts_code": code, "trade_date": "2026-08-21", "adj_factor": 1.2},
    ]) == 1
    assert database.upsert_adjustment_factors([
        {"ts_code": code, "trade_date": "2026-08-21", "adj_factor": 1.2},
    ]) == 1

    with database._get_conn() as conn:
        raw_close = conn.execute(
            "SELECT close FROM market_daily WHERE ts_code=? AND trade_date=?",
            (code, "2026-08-21"),
        ).fetchone()[0]
        adjusted = conn.execute(
            "SELECT adj_factor FROM market_adjustment_factor WHERE ts_code=?",
            (code,),
        ).fetchone()[0]
    assert raw_close == 10.5
    assert adjusted == 1.2
    assert database.get_bar_coverage([code], 2)["sufficient"] == 1
    assert database.get_adjustment_factor_coverage(code, 1)["status"] == "sufficient"


def test_financial_and_flow_history_preserve_period_and_direction(tmp_path):
    database = MarketDatabase(tmp_path / "market.db")
    code = "000001.SZ"
    statements = {
        "income": [
            {"ts_code": code, "end_date": "2026-06-30", "ann_date": "2026-08-20", "n_income": 10},
            {"ts_code": code, "end_date": "2026-03-31", "ann_date": "2026-04-25", "n_income": 8},
        ],
        "balancesheet": [{"ts_code": code, "end_date": "2026-06-30", "ann_date": "2026-08-20"}],
    }
    assert database.upsert_financial_history(code, statements)["stored_count"] == 3
    assert len(database.get_financial_history(code, 8)["income"]) == 2
    assert database.upsert_fund_flow_history([
        {
            "ts_code": code, "trade_date": "2026-08-22", "main_net": 0.0,
            "net_amount": -1.0, "status": "neutral",
        },
        {
            "ts_code": code, "trade_date": "2026-08-21", "main_net": -2.0,
            "net_amount": -3.0, "status": "negative",
        },
    ]) == 2
    rows = database.get_fund_flow_history(code, 20)
    assert rows[0]["status"] == "neutral"
    assert rows[0]["main_net"] == 0.0


def test_completion_checkpoint_lease_blocks_active_owner_and_releases_after_expiry(tmp_path):
    database = MarketDatabase(tmp_path / "lease.db")
    key = ("research_data_backfill", "candidate", "partition-1")
    database.save_completion_checkpoint(*key, {"codes": ["000001.SZ"]}, "pending")

    first = database.try_claim_completion_checkpoint(*key, "worker-a", lease_seconds=60)
    assert first["claimed"] is True
    second = database.try_claim_completion_checkpoint(*key, "worker-b", lease_seconds=60)
    assert second["claimed"] is False
    assert second["lease_owner"] == "worker-a"

    with database._get_conn() as conn:
        conn.execute(
            "UPDATE data_completion_checkpoint SET progress_json=? WHERE job_name=? "
            "AND target_name=? AND partition_key=?",
            ('{"lease_owner":"worker-a","lease_expires_at":"2000-01-01T00:00:00+00:00"}', *key),
        )
    third = database.try_claim_completion_checkpoint(*key, "worker-b", lease_seconds=60)
    assert third["claimed"] is True
    assert third["lease_owner"] == "worker-b"


@pytest.mark.asyncio
async def test_sync_code_refreshes_stale_flow_and_only_marks_complete_when_fresh(
    monkeypatch,
):
    from src.infrastructure.market_data import data_completion_service
    from src.infrastructure.market_data.tushare_provider import tushare_provider

    code = "300792.SZ"
    fresh_rows = [
        {"trade_date": f"2026-09-{4 - index:02d}", "main_net": 1.0}
        for index in range(20)
    ]
    state = {"rows": [
        {"trade_date": "2026-09-03", "main_net": 1.0}
        for _ in range(20)
    ]}

    class FakeDatabase:
        def get_bar_coverage(self, _codes, _required):
            return {"details": [{"status": "sufficient"}]}

        def get_adjustment_factor_coverage(self, _code, _required):
            return {"status": "sufficient"}

        def get_financial_history(self, _code, _periods):
            return {
                name: [{} for _ in range(8)]
                for name in ("income", "balancesheet", "cashflow", "fina_indicator")
            }

        def get_fund_flow_history(self, _code, _days):
            return list(state["rows"])

        def upsert_fund_flow_history(self, rows):
            state["rows"] = list(rows)
            return len(rows)

    async def fetch_moneyflow_history(_code, _days):
        return SimpleNamespace(
            data=fresh_rows, row_count=len(fresh_rows), data_date="2026-09-04"
        )

    monkeypatch.setattr(
        tushare_provider,
        "fetch_moneyflow_history",
        fetch_moneyflow_history,
    )
    result = await data_completion_service.sync_code(
        FakeDatabase(), code, 250, 8, 20, target_date="2026-09-04"
    )

    flow = result["components"]["fund_flow_history"]
    assert flow["status"] == "available"
    assert flow["fresh"] is True
    assert result["complete"] is True
    assert result["retryable"] is False


@pytest.mark.asyncio
async def test_sync_code_persists_empty_timeout_type_in_checkpoint_after_reopen(
    monkeypatch, tmp_path
):
    from src.infrastructure.market_data import data_completion_service
    from src.infrastructure.market_data.tushare_provider import tushare_provider

    async def timeout(*_args, **_kwargs):
        raise TimeoutError()

    for method in (
        "fetch_daily_history",
        "fetch_adjustment_factors",
        "fetch_financial_history",
        "fetch_moneyflow_history",
    ):
        monkeypatch.setattr(tushare_provider, method, timeout)

    path = tmp_path / "checkpoint.db"
    database = MarketDatabase(path)
    result = await data_completion_service.sync_code(
        database, "600681.SH", 250, 8, 20, target_date="2026-09-04"
    )

    assert result["complete"] is False
    assert result["retryable"] is True
    assert result["components"]["financial_history"]["status"] == "timeout"
    assert result["components"]["financial_history"]["error_type"] == "TimeoutError"
    assert result["components"]["financial_history"]["error_message"]
    database.save_completion_checkpoint(
        "research_data_backfill", "candidate", "run-1",
        {"results": {"600681.SH": result}}, "partial",
    )

    reopened = MarketDatabase(path)
    saved = reopened.get_completion_checkpoint(
        "research_data_backfill", "candidate", "run-1"
    )
    assert saved["status"] == "partial"
    saved_component = saved["progress"]["results"]["600681.SH"]["components"]["financial_history"]
    assert saved_component["error_type"] == "TimeoutError"
    assert saved_component["error_message"]


@pytest.mark.asyncio
async def test_batch_flow_backfill_fills_missing_cells_and_is_idempotent(
    monkeypatch, tmp_path
):
    from src.infrastructure.market_data.tushare_provider import tushare_provider

    database = MarketDatabase(tmp_path / "batch-flow.db")
    codes = ["000001.SZ", "600519.SH"]
    dates = ["2026-09-04", "2026-09-03"]
    for code in codes:
        database.upsert_tushare_daily_history([
            {
                "ts_code": code,
                "trade_date": day,
                "open": 10,
                "high": 10,
                "low": 10,
                "close": 10,
                "pre_close": 10,
                "change_pct": 0,
                "volume": 100,
                "amount": 100,
            }
            for day in dates
        ])
    calls = []

    async def fetch_batch(batch_codes, trade_date):
        calls.append((list(batch_codes), trade_date))
        return SimpleNamespace(
            data=[
                {
                    "ts_code": code,
                    "trade_date": trade_date,
                    "main_net": 100.0,
                    "net_amount": 120.0,
                    "status": "positive",
                    "source": "tushare",
                }
                for code in batch_codes
            ],
            row_count=len(batch_codes),
            data_date=trade_date,
        )

    monkeypatch.setattr(tushare_provider, "fetch_moneyflow_batch", fetch_batch)
    result = await backfill_fund_flow_history(
        database,
        codes,
        target_date="2026-09-04",
        flow_days=2,
        code_chunk_size=100,
        max_requests=10,
        deadline_seconds=10,
    )

    assert result["status"] == "complete"
    assert result["requests_attempted"] == 2
    assert result["stored_rows"] == 4
    assert len(calls) == 2
    assert all(len(batch_codes) == 2 for batch_codes, _ in calls)
    reopened = MarketDatabase(tmp_path / "batch-flow.db")
    coverage = reopened.get_fund_flow_coverage(codes, dates)
    assert all(coverage[code] == set(dates) for code in codes)

    second = await backfill_fund_flow_history(
        reopened,
        codes,
        target_date="2026-09-04",
        flow_days=2,
        code_chunk_size=100,
        max_requests=10,
        deadline_seconds=10,
    )
    assert second["status"] == "complete"
    assert second["requests_attempted"] == 0
    assert len(calls) == 2
