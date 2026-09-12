from types import SimpleNamespace

import pytest

from src.explain.outcome_backfiller import _observation_skip_reason
from src.infrastructure.market_data.flow_batch_backfill import backfill_fund_flow_history
from src.infrastructure.market_data.tushare_provider import tushare_provider
from src.infrastructure.storage.market_database import MarketDatabase


def test_suspension_requires_same_day_evidence(tmp_path):
    db = MarketDatabase(tmp_path / "absence.db")
    db.upsert_stock_metadata_snapshot(
        [{"ts_code": "000001.SZ", "is_suspended": True}],
        "2026-09-03", source="fixture",
    )
    result = db.get_expected_market_absences(
        ["000001.SZ", "000002.SZ"], ["2026-09-02", "2026-09-03", "2026-09-04"]
    )
    assert result == {"000001.SZ": {"2026-09-03": "suspended"}}


def test_listing_boundaries_and_resume(tmp_path):
    db = MarketDatabase(tmp_path / "listing.db")
    db.upsert_stock_metadata_snapshot(
        [{"ts_code": "000001.SZ", "list_date": "20260903"},
         {"ts_code": "000002.SZ", "delist_date": "20260903"}],
        "2026-09-02", source="fixture",
    )
    result = db.get_expected_market_absences(
        ["000001.SZ", "000002.SZ"], ["2026-09-02", "2026-09-03"]
    )
    assert result["000001.SZ"] == {"2026-09-02": "not_yet_listed"}
    assert result["000002.SZ"] == {"2026-09-03": "delisted"}


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_error, expected_status", [
    ("tushare_empty:moneyflow", "partial"), ("connection refused", "failed"),
])
async def test_flow_distinguishes_suspended_unknown_and_failed(
    tmp_path, monkeypatch, provider_error, expected_status,
):
    db = MarketDatabase(tmp_path / "flow.db")
    day = "2026-09-03"
    db.upsert_stock_metadata_snapshot(
        [{"ts_code": "000001.SZ", "is_suspended": True}], day, source="fixture"
    )
    monkeypatch.setattr(db, "get_recent_market_dates", lambda *_: [day])
    calls = []

    async def fetch(codes, trade_date):
        calls.append((codes, trade_date))
        raise ValueError(provider_error)

    monkeypatch.setattr(tushare_provider, "fetch_moneyflow_batch", fetch)
    result = await backfill_fund_flow_history(
        db, ["000001.SZ", "000002.SZ"], target_date=day, flow_days=1
    )
    assert calls == [(["000002.SZ"], day)]
    assert result["status"] == expected_status
    assert result["missing_cells_after"] == 1
    assert result["expected_absent_count"] == 1
    assert bool(result["errors"]) == (expected_status == "failed")
    assert bool(result["empty_responses"]) == (expected_status == "partial")
    assert db.get_fund_flow_coverage(["000001.SZ"], [day]) == {"000001.SZ": set()}


@pytest.mark.asyncio
async def test_all_suspended_needs_no_provider_and_creates_no_flow(tmp_path, monkeypatch):
    db = MarketDatabase(tmp_path / "suspended.db")
    day = "2026-09-03"
    db.upsert_stock_metadata_snapshot(
        [{"ts_code": "000001.SZ", "is_suspended": True}], day, source="fixture"
    )
    monkeypatch.setattr(db, "get_recent_market_dates", lambda *_: [day])

    async def fetch(*_):
        pytest.fail("Suspended cells must not be requested")

    monkeypatch.setattr(tushare_provider, "fetch_moneyflow_batch", fetch)
    result = await backfill_fund_flow_history(db, ["000001.SZ"], target_date=day, flow_days=1)
    assert result["status"] == "complete"
    assert result["expected_absent_count"] == 1
    assert result["requests_attempted"] == 0


@pytest.mark.parametrize("stock,benchmark,absences,expected", [
    ({}, {}, {}, "benchmark_unavailable"),
    ({}, {"2026-09-03": 10}, {}, "horizon_not_ready_or_benchmark_pending"),
    ({"2026-09-03": 10}, {"2026-09-03": 10, "2026-09-04": 11},
     {"2026-09-04": "suspended"}, "suspended"),
    ({"2026-09-03": 10}, {"2026-09-03": 10, "2026-09-04": 11},
     {}, "stock_data_missing_unclassified"),
])
def test_learning_skip_reasons(monkeypatch, stock, benchmark, absences, expected):
    from src.explain import outcome_backfiller

    monkeypatch.setattr(outcome_backfiller, "dt_date", SimpleNamespace(
        today=lambda: SimpleNamespace(isoformat=lambda: "2026-09-09")
    ))
    assert _observation_skip_reason(stock, benchmark, "2026-09-03", 1, absences) == expected
