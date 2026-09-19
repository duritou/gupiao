import asyncio
import time

import pytest

from src.api.routes import market_routes, signals_routes
from src.infrastructure.market_data.source_manager import DataProvenance


@pytest.mark.asyncio
async def test_market_overview_does_not_block_api_loop(monkeypatch):
    provenance = DataProvenance(provider="test", source_name="test")

    async def blocking_indices():
        time.sleep(0.1)
        return [], provenance

    async def blocking_breadth():
        time.sleep(0.1)
        return None, provenance

    monkeypatch.setattr(market_routes.source_manager, "get_index_quotes", blocking_indices)
    monkeypatch.setattr(
        market_routes.source_manager, "get_market_breadth", blocking_breadth
    )
    market_routes._overview_cache = None
    overview = asyncio.create_task(market_routes.market_overview())
    await asyncio.sleep(0.01)

    assert overview.done() is False
    await asyncio.wait_for(asyncio.sleep(0.01), timeout=0.05)
    result = await overview
    assert result["_data"]["indices"]["provider"] == "test"


@pytest.mark.asyncio
async def test_market_quotes_degrades_each_slow_provider(monkeypatch):
    async def slow_quote(_code: str):
        time.sleep(0.1)

    monkeypatch.setattr(market_routes.source_manager, "get_realtime_quote", slow_quote)
    monkeypatch.setattr(market_routes, "_DASHBOARD_QUOTE_TIMEOUT_SECONDS", 0.01)

    result = await asyncio.wait_for(
        market_routes.market_quotes(market_routes.QuoteBatchRequest(codes=["600000.SH"])),
        timeout=0.2,
    )

    assert result["quotes"][0]["available"] is False
    assert result["quotes"][0]["provenance"]["provider"] == "none"
    assert result["quotes"][0]["provenance"]["error"]


@pytest.mark.asyncio
async def test_signal_batch_degrades_slow_daily_bars(monkeypatch):
    from src.api.routes import journal_utils
    from src.infrastructure.market_data.real_data_provider import real_data

    async def slow_bars(*_args, **_kwargs):
        time.sleep(0.1)

    monkeypatch.setattr(journal_utils, "stock_name_from_journal", lambda code: code)
    monkeypatch.setattr(real_data, "get_daily_bars", slow_bars)
    monkeypatch.setattr(signals_routes, "_SIGNAL_ITEM_TIMEOUT_SECONDS", 0.01)
    signals_routes._signal_cache.clear()

    result = await asyncio.wait_for(
        signals_routes.compute_batch(signals_routes.BatchRequest(codes=["600000.SH"])),
        timeout=0.2,
    )

    assert "超过" in result["signals"][0]["error"]
