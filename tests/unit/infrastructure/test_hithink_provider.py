from __future__ import annotations

import asyncio
from collections.abc import Iterable

import httpx
import pytest

from src.infrastructure.market_data import hithink_client as client_module
from src.infrastructure.market_data.hithink_client import HiThinkError
from src.infrastructure.market_data.hithink_provider import HiThinkProvider
from src.infrastructure.market_data.provider_resilience import reset_provider_resilience_state
from src.infrastructure.market_data.provider_metrics import reliability_engine
from tests.fixtures.hithink.responses import (
    DAILY_HISTORY,
    DRAGON_TIGER,
    EMPTY_LIMIT_POOL,
    FINANCIAL,
    INDICATORS,
    SNAPSHOT,
    SYMBOL_SEARCH,
    VALUATION,
)


class FakeClient:
    def __init__(self, responses: Iterable[object]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def get(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def response(body: dict, status: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers or {})


@pytest.fixture(autouse=True)
def reset_state() -> None:
    reset_provider_resilience_state()
    reliability_engine.reset_runtime_state()


def provider(fake: FakeClient, **kwargs) -> HiThinkProvider:
    return HiThinkProvider(api_key="test-key", client=fake, min_interval_seconds=0, **kwargs)


@pytest.mark.asyncio
async def test_snapshot_uses_header_maps_null_and_not_live() -> None:
    fake = FakeClient([response(SNAPSHOT, headers={"X-Request-ID": "header-id"})])
    result = await provider(fake).fetch_snapshot(["600519.SH", "600519.SH"])

    assert result.data[0]["thscode"] == "600519.SH"
    assert result.data[0]["turnover"] is None
    assert result.is_live is False
    assert result.request_id == "req-snapshot-001"
    assert fake.calls[0]["headers"] == {"X-api-key": "test-key", "Accept": "application/json"}
    assert fake.calls[0]["params"] == {"thscodes": "600519.SH"}


@pytest.mark.asyncio
async def test_symbol_search_and_valuation_preserve_provider_fields() -> None:
    fake = FakeClient([response(SYMBOL_SEARCH), response(VALUATION)])
    p = provider(fake)
    symbols = await p.fetch_symbol_search("贵州茅台", 1)
    valuation = await p.fetch_valuation_snapshot("300750.SZ")

    assert symbols.data[0]["asset_type"] == "a-share"
    assert symbols.data[0]["end_date"] is None
    assert valuation.data[0]["pe_ttm"] == -1.2
    assert valuation.data[0]["pe_mrq"] is None


@pytest.mark.asyncio
async def test_nontrading_empty_pool_is_valid_empty_result() -> None:
    fake = FakeClient([response(EMPTY_LIMIT_POOL)])
    result = await provider(fake).fetch_limit_pool("up", "2026-09-12")

    assert result.data["item"] == []
    assert result.row_count == 0
    assert fake.calls[0]["params"]["date_ms"] == 1789142400000


@pytest.mark.asyncio
async def test_daily_history_maps_dates_and_uses_millisecond_window() -> None:
    fake = FakeClient([response(DAILY_HISTORY)])
    result = await provider(fake).fetch_daily_history("600519.SH", "2026-09-01", "2026-09-12", "forward")

    assert result.data[0]["date"] == "2026-09-11"
    assert result.data[0]["close"] == 10.5
    assert fake.calls[0]["params"] == {
        "thscode": "600519.SH", "interval": "1d", "start": 1788192000000,
        "end": 1789142400000, "adjust": "forward",
    }


@pytest.mark.asyncio
async def test_financial_history_keeps_period_null_and_calls_three_statements() -> None:
    fake = FakeClient([response(FINANCIAL), response(FINANCIAL), response(FINANCIAL)])
    result = await provider(fake).fetch_financial_history("600519", period="annual", limit=1)

    assert set(result.data["statements"]) == {"income", "balance", "cashflow"}
    assert result.data["statements"]["income"][0]["net_profit"] is None
    assert len(fake.calls) == 3
    assert all(call["params"] == {"thscode": "600519.SH", "period": "annual", "limit": 1} for call in fake.calls)


@pytest.mark.asyncio
async def test_dragon_tiger_preserves_empty_hot_money_rows() -> None:
    fake = FakeClient([response(DRAGON_TIGER)])
    result = await provider(fake).fetch_dragon_tiger("2026-09-11", "all")

    assert result.data["trade_date"] == "2026-09-11"
    assert result.data["hot_money_items"] == []
    assert result.data["stock_items"][0]["net_value"] is None
    assert fake.calls[0]["params"] == {"board_type": "all", "date": "2026-09-11"}


@pytest.mark.asyncio
async def test_business_error_http_200_is_validation_and_not_retried() -> None:
    fake = FakeClient([response({"code": 1003, "message": "bad parameter", "request_id": "req-bad", "data": None})])
    with pytest.raises(HiThinkError) as exc_info:
        await provider(fake, retry_attempts=3).fetch_snapshot("600519")

    assert exc_info.value.category == "validation"
    assert exc_info.value.provider_code == 1003
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_auth_failure_is_not_retried_and_error_is_redacted() -> None:
    fake = FakeClient([response({"code": 0, "data": {"secret": "do-not-log"}}, status=401)])
    with pytest.raises(HiThinkError) as exc_info:
        await provider(fake, retry_attempts=3).fetch_snapshot("600519")

    assert exc_info.value.category == "authentication"
    assert "test-key" not in str(exc_info.value)
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_rate_limit_honors_retry_after_and_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient([
        response({"code": 0, "data": None}, status=429, headers={"Retry-After": "2"}),
        response(SNAPSHOT),
    ])
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(client_module.asyncio, "sleep", fake_sleep)
    result = await provider(fake, retry_attempts=2).fetch_snapshot("600519")

    assert result.row_count == 1
    assert len(fake.calls) == 2
    assert any(seconds >= 2 for seconds in sleeps)


@pytest.mark.asyncio
async def test_server_failure_has_bounded_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient([response({}, status=503), response(SNAPSHOT)])
    async def fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(client_module.asyncio, "sleep", fake_sleep)
    result = await provider(fake, retry_attempts=2).fetch_snapshot("600519")

    assert result.row_count == 1
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_timeout_is_classified_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient([httpx.TimeoutException("timeout"), httpx.TimeoutException("timeout")])
    async def fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(client_module.asyncio, "sleep", fake_sleep)
    with pytest.raises(HiThinkError) as exc_info:
        await provider(fake, retry_attempts=2).fetch_snapshot("600519")

    assert exc_info.value.category == "timeout"
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_invalid_codes_and_dates_fail_before_network() -> None:
    fake = FakeClient([])
    p = provider(fake)
    with pytest.raises(ValueError, match="invalid_thscode"):
        await p.fetch_snapshot("000001.US")
    with pytest.raises(ValueError, match="invalid_date_range"):
        await p.fetch_daily_history("600519.SH", "2026-09-13", "2026-09-12")
    assert fake.calls == []


@pytest.mark.asyncio
async def test_financial_indicator_contract_requires_abilities_array() -> None:
    fake = FakeClient([response({"code": 0, "request_id": "req-ind", "data": {"abilities": {}}})])
    with pytest.raises(HiThinkError, match="abilities_not_array"):
        await provider(fake).fetch_financial_indicators("600519.SH", "2025-4")


@pytest.mark.asyncio
async def test_financial_indicator_maps_array_and_null_value() -> None:
    fake = FakeClient([response(INDICATORS)])
    result = await provider(fake).fetch_financial_indicators("600519.SH", "2025-4")

    assert result.data["abilities"][0]["ability"] == "growth"
    assert result.data["abilities"][0]["indicators"][0]["value"] is None


@pytest.mark.asyncio
async def test_unconfigured_provider_never_calls_network() -> None:
    fake = FakeClient([])
    with pytest.raises(HiThinkError) as exc_info:
        await HiThinkProvider(api_key="", client=fake).fetch_snapshot("600519")

    assert exc_info.value.category == "not_configured"
    assert fake.calls == []


def test_runtime_stats_are_aggregated_without_credentials() -> None:
    p = HiThinkProvider(api_key="test-key")
    stats = p.runtime_stats()

    assert stats["calls"] == 0
    assert "api_key" not in stats
    assert "test-key" not in repr(stats)
