from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.api.routes import market_routes


def _payload():
    return SimpleNamespace(
        data=[
            {
                "thscode": "600519.SH",
                "ticker": "600519",
                "name": "贵州茅台",
                "exchange": "SH",
            }
        ],
        endpoint="/api/meta/tickers/search",
        request_id="req-symbol",
        data_date="2026-09-12",
        fetched_at="2026-09-12T10:00:00+00:00",
    )


@pytest.mark.asyncio
async def test_symbol_search_primary_uses_hithink(monkeypatch):
    calls = []

    class Fake:
        configured = True

        async def fetch_symbol_search(self, query, limit):
            calls.append((query, limit))
            return _payload()

    monkeypatch.setattr(market_routes, "hithink_provider", Fake())
    monkeypatch.setattr(market_routes.settings, "HITHINK_SYMBOL_MODE", "primary")

    result = await market_routes.symbol_search("贵州茅台", 5)

    assert result["results"][0]["thscode"] == "600519.SH"
    assert result["_meta"]["provider"] == "hithink"
    assert calls == [("贵州茅台", 5)]


@pytest.mark.asyncio
async def test_symbol_search_shadow_does_not_change_default_result(monkeypatch):
    class Fake:
        configured = True

        async def fetch_symbol_search(self, query, limit):
            return _payload()

    monkeypatch.setattr(market_routes, "hithink_provider", Fake())
    monkeypatch.setattr(market_routes.settings, "HITHINK_SYMBOL_MODE", "shadow")

    result = await market_routes.symbol_search("贵州茅台")

    assert result["results"] == []
    assert result["_meta"]["shadow_result_count"] == 1
    assert result["_meta"]["available"] is False


@pytest.mark.asyncio
async def test_symbol_search_skips_remote_for_normalized_code(monkeypatch):
    class Forbidden:
        configured = True

        async def fetch_symbol_search(self, query, limit):
            raise AssertionError("exact thscode must not trigger remote search")

    monkeypatch.setattr(market_routes, "hithink_provider", Forbidden())

    result = await market_routes.symbol_search("600519.SH")

    assert result["results"] == [{"thscode": "600519.SH", "ticker": "600519", "name": ""}]
    assert result["_meta"]["provider"] == "local_normalization"
