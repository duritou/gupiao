"""Test the data pipeline with baostock fallback."""
import pytest
import asyncio


@pytest.mark.asyncio
async def test_source_manager_baostock_quote():
    """SourceManager should return quote data via baostock fallback."""
    from src.infrastructure.market_data.source_manager import source_manager

    quote, prov = await source_manager.get_realtime_quote("000725.SZ")

    assert quote is not None, f"Quote failed: {prov.error_message}"
    assert quote["price"] > 0, f"Price should be > 0, got {quote['price']}"
    assert quote["stock_name"], "Stock name should not be empty"
    assert prov.is_available, "Provenance should show data available"
    VALID_PROVIDERS = ("ifind", "mootdx", "tushare", "akshare", "finnhub", "fmp", "twelvedata", "polygon", "alphavantage", "baostock")
    assert prov.provider in VALID_PROVIDERS, \
        f"Unexpected provider: {prov.provider}"
    assert prov.trust_score > 0, f"Trust score should be > 0, got {prov.trust_score}"


@pytest.mark.asyncio
async def test_source_manager_baostock_kline():
    """SourceManager should return K-line data via baostock fallback."""
    from src.infrastructure.market_data.source_manager import source_manager

    klines, prov = await source_manager.get_kline("000725.SZ", count=10)

    assert klines is not None, f"K-line failed: {prov.error_message}"
    assert len(klines) >= 5, f"Should have >= 5 candles, got {len(klines)}"
    assert "date" in klines[0]
    assert "close" in klines[0]
    assert klines[0]["close"] > 0
    assert prov.is_available


@pytest.mark.asyncio
async def test_health_check_shows_live_data():
    """Health check should report data available."""
    from src.infrastructure.market_data.source_manager import source_manager

    health = source_manager.check_health()
    assert health["live_data_available"] is True, \
        f"Live data should be available, sources: {health['sources']}"


@pytest.mark.asyncio
async def test_detail_endpoint_returns_data():
    """The detail API endpoint should return stock data."""
    from src.api.app import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    r = client.get("/api/v1/detail/000725.SZ")

    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:500]}"
    data = r.json()

    # Should have data, not error
    assert "data_error" not in data or not data.get("data_error"), \
        f"Should not have data_error: {data.get('data_error', '')[:200]}"

    assert data.get("latest_price", 0) > 0, \
        f"latest_price should be > 0: {data}"

    # Should have provenance
    assert "_data" in data
    assert data["_data"]["data_available"] is True

    # K-line should be available
    assert "klines" in data
    assert len(data["klines"]) > 0
