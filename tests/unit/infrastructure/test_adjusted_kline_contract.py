"""Tests for explicit point-in-time K-line adjustment contracts."""

import pytest

from src.infrastructure.market_data import source_manager as source_manager_module
from src.infrastructure.market_data.source_manager import source_manager


@pytest.mark.asyncio
async def test_qfq_request_filters_raw_providers_and_labels_bars(monkeypatch):
    attempted = []
    code = "000001.SZ-QFQ-CONTRACT"

    monkeypatch.setattr(
        source_manager,
        "_get_ranked_providers",
        lambda stock_code, capability: ["mootdx", "sina", "tencent"],
    )

    async def _dispatch(provider, stock_code, count):
        attempted.append(provider)
        return ([{"date": "2026-08-28", "close": 10.0}], object())

    monkeypatch.setattr(source_manager, "_dispatch_kline", _dispatch)
    monkeypatch.setattr(source_manager, "_is_a_share", lambda stock_code: True)

    bars, _ = await source_manager.get_kline(code, 20, adjustment_mode="qfq")

    assert attempted == ["tencent"]
    assert bars[0]["adjustment_mode"] == "qfq"


@pytest.mark.asyncio
async def test_qfq_cache_is_separate_from_unconstrained_cache(monkeypatch):
    code = "000002.SZ-QFQ-CACHE"
    attempts = []
    monkeypatch.setattr(source_manager_module.tushare_provider, "token", "")
    monkeypatch.setattr(
        source_manager, "_get_ranked_providers", lambda stock_code, capability: ["tencent"],
    )
    monkeypatch.setattr(source_manager, "_is_a_share", lambda stock_code: True)

    async def _dispatch(provider, stock_code, count):
        attempts.append(provider)
        return ([{"date": "2026-08-28", "close": 10.0}], object())

    monkeypatch.setattr(source_manager, "_dispatch_kline", _dispatch)

    await source_manager.get_kline(code, 20)
    await source_manager.get_kline(code, 20, adjustment_mode="qfq")

    assert attempts == ["tencent", "tencent"]
