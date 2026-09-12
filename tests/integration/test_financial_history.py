from __future__ import annotations

import pytest

from src.infrastructure.market_data.source_manager import DataProvenance, source_manager


@pytest.mark.asyncio
async def test_source_manager_exposes_multi_period_counts(monkeypatch, tmp_path):
    from src.infrastructure.storage import market_database as database_module
    from src.infrastructure.market_data import source_manager as source_module

    database = database_module.MarketDatabase(tmp_path / "market.db")
    code = "600519.SH"
    database.upsert_financial_history(code, {
        "income": [
            {"ts_code": code, "end_date": "2026-06-30", "ann_date": "2026-08-20"},
            {"ts_code": code, "end_date": "2026-03-31", "ann_date": "2026-04-25"},
        ],
        "balancesheet": [
            {"ts_code": code, "end_date": "2026-06-30", "ann_date": "2026-08-20"},
            {"ts_code": code, "end_date": "2026-03-31", "ann_date": "2026-04-25"},
        ],
        "cashflow": [
            {"ts_code": code, "end_date": "2026-06-30", "ann_date": "2026-08-20"},
            {"ts_code": code, "end_date": "2026-03-31", "ann_date": "2026-04-25"},
        ],
        "fina_indicator": [
            {"ts_code": code, "end_date": "2026-06-30", "ann_date": "2026-08-20"},
            {"ts_code": code, "end_date": "2026-03-31", "ann_date": "2026-04-25"},
        ],
    })
    original = database_module.market_db
    database_module.market_db = database
    try:
        async def forbidden_provider(*args, **kwargs):
            raise AssertionError("complete local history should not call the provider")

        monkeypatch.setattr(
            source_module.tushare_provider, "fetch_financial_history", forbidden_provider
        )
        result, provenance = await source_manager.get_financial_history(code, periods=2)
        assert result["period_counts"]["income"] == 2
        assert result["history_complete"] is True
        assert provenance.is_cached is True
    finally:
        database_module.market_db = original
