from __future__ import annotations

import pytest

from src.infrastructure.market_data.source_manager import source_manager


@pytest.mark.asyncio
async def test_flow_history_consumer_keeps_zero_and_negative_values(monkeypatch, tmp_path):
    from src.infrastructure.storage import market_database as database_module

    database = database_module.MarketDatabase(tmp_path / "market.db")
    code = "000001.SZ"
    database.upsert_fund_flow_history([
        {
            "ts_code": code, "trade_date": "2026-08-22", "main_net": 0.0,
            "net_amount": -1.0, "status": "neutral", "source": "tushare",
        },
    ])
    original = database_module.market_db
    database_module.market_db = database
    try:
        from src.infrastructure.market_data import source_manager as source_module

        async def forbidden_provider(*args, **kwargs):
            raise AssertionError("provider must not be called for a complete window")

        monkeypatch.setattr(
            source_module.tushare_provider,
            "fetch_moneyflow_history", forbidden_provider,
        )
        result, _ = await source_manager.get_fund_flow_history(code, days=1)
        assert result["rows"][0]["main_net"] == 0.0
        assert result["rows"][0]["status"] == "neutral"
    finally:
        database_module.market_db = original
