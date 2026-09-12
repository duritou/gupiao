from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.api.routes import dragon_tiger_routes, valuation_routes
from src.infrastructure.market_data.source_manager import DataProvenance


class FakeHiThink:
    configured = True

    def __init__(self, valuation=None, dragon=None, error: Exception | None = None):
        self.valuation = valuation
        self.dragon = dragon
        self.error = error
        self.valuation_calls = 0
        self.dragon_calls = 0

    async def fetch_valuation_snapshot(self, code):
        self.valuation_calls += 1
        if self.error:
            raise self.error
        return self.valuation

    async def fetch_dragon_tiger(self, **kwargs):
        self.dragon_calls += 1
        if self.error:
            raise self.error
        return self.dragon


def valuation_payload():
    return SimpleNamespace(
        data=[{"thscode": "600519.SH", "name": "贵州茅台", "pe_ttm": -1.2, "pb_mrq": None, "ps_ttm": 7.2, "pcf_ttm": None}],
        endpoint="/api/a-share/valuations/snapshot",
        request_id="req-v",
        data_date="2026-09-11",
        fetched_at="2026-09-11T15:00:00+00:00",
    )


def dragon_payload():
    return SimpleNamespace(
        data={"board_type": "all", "trade_date": "2026-09-11", "stock_items": [{"thscode": "600519.SH", "name": "贵州茅台", "net_value": None, "limit_reason": "机构净买"}], "hot_money_items": []},
        endpoint="/api/a-share/special-data/dragon-tiger-list",
        request_id="req-d",
        fetched_at="2026-09-11T15:00:00+00:00",
    )


@pytest.mark.asyncio
async def test_valuation_primary_returns_hithink_without_calling_existing_source(monkeypatch):
    fake = FakeHiThink(valuation_payload())
    monkeypatch.setattr(valuation_routes, "hithink_provider", fake)
    monkeypatch.setattr(valuation_routes.settings, "HITHINK_VALUATION_MODE", "primary")

    async def forbidden(code):
        raise AssertionError("existing source must not run for a successful primary")

    monkeypatch.setattr(valuation_routes.source_manager, "get_eod_quote", forbidden)
    result = await valuation_routes.get_valuation("600519")

    assert result["_meta"]["provider"] == "hithink"
    assert result["data"]["pe"] == -1.2
    assert result["data"]["pb"] is None
    assert fake.valuation_calls == 1


@pytest.mark.asyncio
async def test_valuation_shadow_keeps_existing_return(monkeypatch):
    fake = FakeHiThink(valuation_payload())
    monkeypatch.setattr(valuation_routes, "hithink_provider", fake)
    monkeypatch.setattr(valuation_routes.settings, "HITHINK_VALUATION_MODE", "shadow")

    async def quote(code):
        return {"stock_code": code, "price": 10, "pe": 18, "pb": 1.5}, DataProvenance(provider="tencent")

    monkeypatch.setattr(valuation_routes.source_manager, "get_eod_quote", quote)
    result = await valuation_routes.get_valuation("600519")

    assert result["_meta"]["provider"] == "tencent"
    assert result["data"]["pe"] == 18
    assert fake.valuation_calls == 1


@pytest.mark.asyncio
async def test_valuation_fallback_uses_hithink_after_existing_failure(monkeypatch):
    fake = FakeHiThink(valuation_payload())
    monkeypatch.setattr(valuation_routes, "hithink_provider", fake)
    monkeypatch.setattr(valuation_routes.settings, "HITHINK_VALUATION_MODE", "fallback")

    async def unavailable(code):
        raise RuntimeError("source unavailable")

    monkeypatch.setattr(valuation_routes.source_manager, "get_eod_quote", unavailable)
    monkeypatch.setattr(valuation_routes, "get_vibe_provider", lambda: SimpleNamespace(get_valuation=unavailable))
    result = await valuation_routes.get_valuation("600519")

    assert result["_meta"]["provider"] == "hithink"
    assert fake.valuation_calls == 1


@pytest.mark.asyncio
async def test_valuation_hithink_error_is_recorded_on_existing_result(monkeypatch):
    fake = FakeHiThink(error=RuntimeError("temporary"))
    monkeypatch.setattr(valuation_routes, "hithink_provider", fake)
    monkeypatch.setattr(valuation_routes.settings, "HITHINK_VALUATION_MODE", "primary")

    async def quote(code):
        return {"stock_code": code, "price": 10, "pe": 18, "pb": 1.5}, DataProvenance(provider="tencent")

    monkeypatch.setattr(valuation_routes.source_manager, "get_eod_quote", quote)
    result = await valuation_routes.get_valuation("600519")

    assert result["_meta"]["provider"] == "tencent"
    assert result["_meta"]["hithink_fallback_reason"] == "RuntimeError"


@pytest.mark.asyncio
async def test_dragon_primary_normalizes_plain_code_and_projects_board(monkeypatch):
    fake = FakeHiThink(dragon=dragon_payload())
    monkeypatch.setattr(dragon_tiger_routes, "hithink_provider", fake)
    monkeypatch.setattr(dragon_tiger_routes.settings, "HITHINK_SPECIAL_MODE", "primary")

    async def forbidden(code):
        raise AssertionError("existing source must not run for a successful primary")

    monkeypatch.setattr(dragon_tiger_routes.source_manager, "get_dragon_tiger", forbidden)
    result = await dragon_tiger_routes.get_dragon_tiger("600519")

    assert result["_meta"]["provider"] == "hithink"
    assert result["data"]["records"][0]["reason"] == "机构净买"
    assert result["data"]["records"][0]["net_value"] is None
    assert fake.dragon_calls == 1


@pytest.mark.asyncio
async def test_dragon_shadow_keeps_tushare_result(monkeypatch):
    fake = FakeHiThink(dragon=dragon_payload())
    monkeypatch.setattr(dragon_tiger_routes, "hithink_provider", fake)
    monkeypatch.setattr(dragon_tiger_routes.settings, "HITHINK_SPECIAL_MODE", "shadow")

    async def board(code):
        return {"records": [{"date": "2026-09-11", "reason": "test"}], "seats": {}, "institution": {}}, DataProvenance(provider="tushare")

    monkeypatch.setattr(dragon_tiger_routes.source_manager, "get_dragon_tiger", board)
    result = await dragon_tiger_routes.get_dragon_tiger("600519")

    assert result["_meta"]["provider"] == "tushare"
    assert result["data"]["records"][0]["reason"] == "test"
    assert fake.dragon_calls == 1


@pytest.mark.asyncio
async def test_dragon_fallback_uses_hithink_when_tushare_has_no_records(monkeypatch):
    fake = FakeHiThink(dragon=dragon_payload())
    monkeypatch.setattr(dragon_tiger_routes, "hithink_provider", fake)
    monkeypatch.setattr(dragon_tiger_routes.settings, "HITHINK_SPECIAL_MODE", "fallback")

    async def empty_board(code):
        return {}, DataProvenance(provider="tushare")

    monkeypatch.setattr(dragon_tiger_routes.source_manager, "get_dragon_tiger", empty_board)
    monkeypatch.setattr(dragon_tiger_routes, "fetch_eastmoney_dragon_tiger", empty_board)
    result = await dragon_tiger_routes.get_dragon_tiger("600519")

    assert result["_meta"]["provider"] == "hithink"
    assert fake.dragon_calls == 1
