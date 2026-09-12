from datetime import datetime, timezone
from urllib.error import URLError

import pytest

from src.ai_os.causal_execution import validate_post_signal_quote
from src.infrastructure.market_data import tickflow_provider
from src.infrastructure.market_data.provider_metrics import ProviderReliabilityEngine
from src.infrastructure.market_data.source_manager import DataProvenance, SourceManager


def _timestamp(year: int, month: int, day: int, hour: int, minute: int) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp() * 1000)


def test_quote_parser_normalizes_documented_tickflow_shape():
    payload = [{
        "symbol": "600000.SH",
        "last_price": 12.34,
        "prev_close": 12.00,
        "open": 12.10,
        "high": 12.50,
        "low": 12.05,
        "volume": 120000,
        "amount": 1500000,
        "timestamp": _timestamp(2026, 8, 31, 2, 0),
        "ext": {
            "name": "浦发银行",
            "change_amount": 0.34,
            "change_pct": 0.0283,
            "turnover_rate": 0.005,
            "amplitude": 0.0375,
        },
    }]

    def fake_request(path, params, timeout):
        assert path == "/v1/quotes"
        assert params["symbols"] == "600000.SH"
        return payload

    original = tickflow_provider._request_json
    tickflow_provider._request_json = fake_request
    try:
        quote = tickflow_provider.fetch_quote("600000.SH")
    finally:
        tickflow_provider._request_json = original

    assert quote["stock_code"] == "600000.SH"
    assert quote["stock_name"] == "浦发银行"
    assert quote["price"] == 12.34
    assert quote["change_pct"] == 2.83
    assert quote["turnover"] == 0.5
    assert quote["amplitude"] == 3.75
    assert quote["data_date"] == "2026-08-31"
    assert quote["source"] == "tickflow_live_quote"


def test_kline_parser_expands_compact_columns_in_order():
    payload = {
        "timestamp": [
            _timestamp(2026, 8, 28, 0, 0),
            _timestamp(2026, 8, 31, 0, 0),
        ],
        "open": [10, 11],
        "high": [12, 13],
        "low": [9, 10],
        "close": [11, 12],
        "volume": [100, 120],
        "amount": [1000, 1200],
    }

    original = tickflow_provider._request_json
    tickflow_provider._request_json = lambda *args, **kwargs: payload
    try:
        rows = tickflow_provider.fetch_klines("600000.SH", count=2)
    finally:
        tickflow_provider._request_json = original

    assert [row["date"] for row in rows] == ["2026-08-28", "2026-08-31"]
    assert rows[-1]["close"] == 12.0
    assert rows[-1]["amount"] == 1200.0


def test_source_manager_skips_tickflow_without_key(monkeypatch):
    monkeypatch.delenv("TICKFLOW_API_KEY", raising=False)
    manager = SourceManager()
    assert "tickflow" not in manager._get_ranked_providers("600000.SH", "realtime_quote")


def test_data_status_reports_configured_tickflow_as_route_primary(monkeypatch):
    monkeypatch.setenv("TICKFLOW_API_KEY", "test-key")
    manager = SourceManager()
    manager._sources["tickflow"].total_calls = 1
    manager._sources["tickflow"].success_count = 1
    manager._sources["tickflow"].is_available = True
    manager._sources["tickflow"].latency_ms = 100.0
    monkeypatch.setattr(
        manager,
        "_get_ranked_providers",
        lambda code, capability: ["tickflow", "sina"]
        if capability == "realtime_quote" else [],
    )

    status = manager.get_data_status("600000.SH")

    assert status["primary_provider"] == "tickflow"


@pytest.mark.asyncio
async def test_configured_tickflow_does_not_return_old_tencent_cache(monkeypatch):
    monkeypatch.setenv("TICKFLOW_API_KEY", "test-key")
    manager = SourceManager()
    manager.cache.set("spot:quote:600000.SH", {
        "stock_code": "600000.SH", "price": 9.0, "source": "tencent",
    })
    expected = {
        "stock_code": "600000.SH", "price": 9.5,
        "source": "tickflow_live_quote",
    }
    provenance = DataProvenance(provider="tickflow", is_live=True)
    monkeypatch.setattr(
        manager, "_try_tickflow_quote",
        lambda code: _async_result(expected, provenance),
    )

    quote, result_provenance = await manager.get_realtime_quote("600000.SH")

    assert quote == expected
    assert result_provenance.provider == "tickflow"


@pytest.mark.asyncio
async def test_configured_tickflow_does_not_return_old_kline_cache(monkeypatch):
    monkeypatch.setenv("TICKFLOW_API_KEY", "test-key")
    manager = SourceManager()
    manager.cache.set("kline_daily:600000.SH:2:any", [
        {"date": "2026-08-28", "close": 9.0, "source": "sina_kline"},
    ])
    expected = [
        {"date": "2026-08-31", "close": 9.5, "source": "tickflow_kline"},
    ]
    provenance = DataProvenance(provider="tickflow", is_live=True)
    monkeypatch.setattr(
        manager, "_try_tickflow_kline",
        lambda code, count: _async_result(expected, provenance),
    )
    monkeypatch.setattr(
        manager,
        "_try_tushare_kline",
        lambda code, count: _async_result(
            None, DataProvenance(provider="tushare", error_message="test unavailable")
        ),
    )

    bars, result_provenance = await manager.get_kline("600000.SH", 2)

    assert bars == expected
    assert result_provenance.provider == "tickflow"


async def _async_result(value, provenance):
    return value, provenance


@pytest.mark.asyncio
async def test_source_manager_accepts_tickflow_quote(monkeypatch):
    monkeypatch.setenv("TICKFLOW_API_KEY", "test-key")
    manager = SourceManager()

    def fake_quote(code):
        return {
            "stock_code": code,
            "stock_name": "测试",
            "price": 10.0,
            "change_pct": 1.0,
            "amount": 2_000_000.0,
            "volume": 1000.0,
            "data_date": "2026-08-31",
            "exchange_timestamp": "2026-08-31T02:00:00+00:00",
            "fetched_at": "2026-08-31T02:00:01+00:00",
            "source": "tickflow_live_quote",
        }

    monkeypatch.setattr(tickflow_provider, "fetch_quote", fake_quote)

    quote, provenance = await manager._try_tickflow_quote("600000.SH")
    assert quote is not None
    assert quote["source"] == "tickflow_live_quote"
    assert provenance.provider == "tickflow"


def test_causal_execution_accepts_tickflow_as_verified_quote():
    decision = {
        "signal_at": "2026-08-31T10:00:00+08:00",
        "data_cutoff_at": "2026-08-31T09:59:00+08:00",
    }
    quote = {
        "price": 10.0,
        "data_date": "2026-08-31",
        "source": "tickflow_live_quote",
        "exchange_timestamp": "2026-08-31T02:00:02+00:00",
        "fetched_at": "2026-08-31T02:00:03+00:00",
    }
    verified, reason = validate_post_signal_quote(decision, quote)
    assert verified is not None
    assert reason == "verified_post_signal_quote"


def test_degraded_provider_allows_one_half_open_probe_and_recovers():
    engine = ProviderReliabilityEngine()
    metrics = engine.get_or_create_metrics("tickflow")
    metrics.is_degraded = True
    metrics.degraded_at = 1_000.0
    metrics.health_check_interval = 300.0

    assert engine.should_attempt("tickflow", now=1_299.0) is False
    assert engine.should_attempt("tickflow", now=1_300.0) is True
    assert engine.should_attempt("tickflow", now=1_301.0) is False

    engine.record_call("tickflow", "quote", True, 10.0)

    assert engine.is_degraded("tickflow") is False
    assert engine.should_attempt("tickflow", now=1_302.0) is True


@pytest.mark.asyncio
async def test_startup_probe_checks_tickflow_then_falls_back(monkeypatch):
    monkeypatch.setenv("TICKFLOW_API_KEY", "test-key")
    manager = SourceManager()
    calls = []

    async def failed_tickflow(code):
        calls.append("tickflow")
        return None, DataProvenance(provider="tickflow", error_message="blocked")

    async def failed_tushare(code):
        calls.append("tushare")
        return None, DataProvenance(provider="tushare", error_message="blocked")

    async def working_tencent(code):
        calls.append("tencent")
        return {"price": 10.0, "data_date": "2026-09-01"}, DataProvenance(
            provider="tencent", is_live=True,
        )

    async def failed_sina(code):
        calls.append("sina")
        return None, DataProvenance(provider="sina", error_message="unavailable")

    monkeypatch.setattr(manager, "_try_tickflow_quote", failed_tickflow)
    monkeypatch.setattr(manager, "_try_tushare_quote", failed_tushare)
    monkeypatch.setattr(manager, "_try_tencent_quote", working_tencent)
    monkeypatch.setattr(manager, "_try_sina_quote", failed_sina)

    result = await manager.probe_live_sources()

    assert calls == ["tickflow", "tushare", "tencent", "sina"]
    assert result["available"] is True
    assert result["provider"] == "tencent"
    assert [item["provider"] for item in result["providers"]] == calls


def test_winerror_10013_opens_long_circuit_without_leaking_raw_error(monkeypatch):
    monkeypatch.setenv("TICKFLOW_API_KEY", "test-key")
    denied = OSError("socket access forbidden")
    denied.winerror = 10013
    captured = {}

    def fail_urlopen(*args, **kwargs):
        raise URLError(denied)

    def capture_failure(host, reason, **kwargs):
        captured.update(host=host, reason=reason, **kwargs)

    monkeypatch.setattr(tickflow_provider, "urlopen", fail_urlopen)
    monkeypatch.setattr(tickflow_provider, "record_provider_failure", capture_failure)
    monkeypatch.setattr(tickflow_provider, "reserve_provider_request", lambda *args, **kwargs: 0.0)
    monkeypatch.setattr(tickflow_provider, "_MAX_RETRIES", 1)

    with pytest.raises(tickflow_provider.TickFlowError, match="windows_socket_denied"):
        tickflow_provider._request_json("/v1/quotes", {"symbols": "600000.SH"}, 1.0)

    assert captured["reason"] == "windows_socket_denied (WinError 10013)"
    assert captured["immediate"] is True
    assert captured["cooldown_seconds"] == 180.0
