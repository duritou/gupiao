from __future__ import annotations

import sys
import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.market_data import research_flow
from src.infrastructure.market_data.source_manager import DataProvenance, SourceManager
from src.infrastructure.market_data.tushare_provider import (
    TushareProvider,
    tushare_provider,
)
from src.infrastructure.storage.market_database import MarketDatabase


class FakeFrame:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.empty = not rows

    def __len__(self) -> int:
        return len(self.rows)

    def to_dict(self, orient: str) -> list[dict]:
        assert orient == "records"
        return list(self.rows)


class FakePro:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def daily(self, **kwargs):
        self.calls.append(("daily", kwargs))
        return FakeFrame([
            {
                "ts_code": "600519.SH",
                "trade_date": "20260904",
                "open": 1320.0,
                "high": 1340.0,
                "low": 1310.0,
                "close": 1330.0,
                "pre_close": 1300.0,
                "pct_chg": 2.31,
                "vol": 1000.0,
                "amount": 2000.0,
            },
            {
                "ts_code": "600519.SH",
                "trade_date": "20260903",
                "open": 1290.0,
                "high": 1310.0,
                "low": 1280.0,
                "close": 1300.0,
                "pre_close": 1290.0,
                "pct_chg": 0.78,
                "vol": 900.0,
                "amount": 1800.0,
            },
        ])

    def rt_min(self, **kwargs):
        self.calls.append(("rt_min", kwargs))
        return FakeFrame([{
            "ts_code": kwargs["ts_code"],
            "time": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            "open": 10.0,
            "close": 10.1,
            "high": 10.2,
            "low": 9.9,
            "vol": 123400,
            "amount": 1240000,
        }])

    def daily_basic(self, **kwargs):
        self.calls.append(("daily_basic", kwargs))
        return FakeFrame([{
            "ts_code": "600519.SH",
            "trade_date": "20260904",
            "turnover_rate": 1.2,
            "pe_ttm": 25.0,
            "pb": 8.0,
            "total_mv": 1_000_000.0,
            "circ_mv": 900_000.0,
            "volume_ratio": 1.1,
        }])

    def fina_indicator(self, **kwargs):
        self.calls.append(("fina_indicator", kwargs))
        return FakeFrame([{
            "ann_date": "20260815",
            "end_date": "20260630",
            "eps": 4.0,
            "roe": 20.0,
            "roa": 10.0,
            "tr_yoy": 8.0,
            "netprofit_yoy": 9.0,
        }])

    def income(self, **kwargs):
        self.calls.append(("income", kwargs))
        return FakeFrame([{
            "ann_date": "20260815",
            "end_date": "20260630",
            "n_income_attr_p": 100.0,
            "total_revenue": 500.0,
        }])

    def moneyflow(self, **kwargs):
        self.calls.append(("moneyflow", kwargs))
        return FakeFrame([{
            "ts_code": "600519.SH",
            "trade_date": "20260904",
            "buy_lg_amount": 2.0,
            "sell_lg_amount": 1.0,
            "buy_elg_amount": 0.5,
            "sell_elg_amount": 0.2,
            "buy_md_amount": 0.4,
            "sell_md_amount": 0.3,
            "buy_sm_amount": 0.2,
            "sell_sm_amount": 0.1,
        }])

    def stock_basic(self, **kwargs):
        self.calls.append(("stock_basic", kwargs))
        return FakeFrame([{"ts_code": "600519.SH"}])


@pytest.fixture
def fake_tushare(monkeypatch):
    pro = FakePro()
    monkeypatch.setitem(
        sys.modules,
        "tushare",
        SimpleNamespace(pro_api=lambda token, timeout=30: pro),
    )
    return pro


@pytest.mark.asyncio
async def test_quote_normalizes_code_and_tushare_units(fake_tushare):
    provider = TushareProvider(token="test-token")

    payload = await provider.fetch_daily_quote("600519")

    assert payload.data["stock_code"] == "600519.SH"
    assert payload.data["data_date"] == "2026-09-04"
    assert payload.data["amount"] == 2_000_000.0
    assert payload.data["market_cap_yi"] == 100.0
    assert payload.data["is_realtime"] is False
    assert all(call[1]["ts_code"] == "600519.SH" for call in fake_tushare.calls)


@pytest.mark.asyncio
async def test_realtime_quote_preserves_exchange_timestamp(fake_tushare):
    provider = TushareProvider(token="test-token")

    payload = await provider.fetch_realtime_quote("600519")

    assert payload.endpoint == "rt_min"
    assert payload.data["price"] == 10.1
    assert payload.data["source"] == "tushare_rt_min"
    assert payload.data["is_realtime"] is True
    assert payload.data["exchange_at"]


@pytest.mark.asyncio
async def test_kline_is_chronological_and_preserves_eod_provenance(fake_tushare):
    provider = TushareProvider(token="test-token")

    payload = await provider.fetch_kline("600519", 2)

    assert [row["date"] for row in payload.data] == ["2026-09-03", "2026-09-04"]
    assert payload.data[0]["amount"] == 1_800_000.0
    assert payload.data[-1]["source"] == "tushare"


@pytest.mark.asyncio
async def test_moneyflow_keeps_direction_and_converts_wan_to_yuan(fake_tushare):
    provider = TushareProvider(token="test-token")

    payload = await provider.fetch_moneyflow("600519", 5)

    assert payload.data["status"] == "positive"
    assert payload.data["main_net"] == 13_000.0
    assert payload.data["net_amount"] == 15_000.0
    assert payload.data["data_date"] == "2026-09-04"


@pytest.mark.asyncio
async def test_moneyflow_batch_preserves_codes_and_requested_date(fake_tushare):
    provider = TushareProvider(token="test-token")

    payload = await provider.fetch_moneyflow_batch(["600519.SH"], "2026-09-04")

    assert payload.row_count == 1
    assert payload.data[0]["ts_code"] == "600519.SH"
    assert payload.data[0]["trade_date"] == "2026-09-04"
    call = next(item for item in fake_tushare.calls if item[0] == "moneyflow")
    assert call[1]["ts_code"] == "600519.SH"
    assert call[1]["trade_date"] == "20260904"


@pytest.mark.asyncio
async def test_daily_snapshot_reports_coverage(fake_tushare):
    provider = TushareProvider(token="test-token")

    payload = await provider.fetch_daily_snapshot("2026-09-04")

    assert payload.row_count == 1
    assert payload.coverage_ratio == 1.0
    assert all(row["source"] == "tushare" for row in payload.data)


def test_tushare_daily_persistence_rejects_partial_and_normalizes_dates(tmp_path):
    database = MarketDatabase(tmp_path / "market.db")
    row = {
        "ts_code": "600519.SH",
        "trade_date": "20260904",
        "close": 1330.0,
        "pre_close": 1300.0,
    }

    partial = database.upsert_tushare_daily_rows(
        [row], "2026-09-04", expected_count=2, complete=False
    )
    assert partial["status"] == "partial"
    assert database.get_latest_market_date_on_or_before("2026-09-04") == ""

    completed = database.upsert_tushare_daily_rows(
        [row], "20260904", expected_count=1, complete=True
    )
    assert completed["status"] == "completed"
    assert completed["target_date"] == "2026-09-04"
    assert database.get_latest_market_date_on_or_before("2026-09-04") == "2026-09-04"


@pytest.mark.asyncio
async def test_stock_evidence_keeps_successful_components_when_fundamental_times_out(
    monkeypatch,
):
    manager = SourceManager()
    quote = {"stock_code": "600519.SH", "price": 1330.0, "source": "tushare"}
    provenance = DataProvenance(provider="tushare", data_date="2026-09-04")
    monkeypatch.setattr(
        manager, "_try_tushare_quote", AsyncMock(return_value=(quote, provenance))
    )

    async def failed_fundamental(_code):
        raise TimeoutError("fina_indicator timeout")

    async def successful_flow(_code, _days):
        return {
            "status": "positive",
            "main_net": 100.0,
            "source": "tushare",
            "data_date": "2026-09-04",
            "row_count": 5,
            "endpoint": "moneyflow",
        }

    monkeypatch.setattr(tushare_provider, "fetch_fundamental", failed_fundamental)
    monkeypatch.setattr(research_flow, "get_research_flow", successful_flow)

    evidence = await manager.get_stock_evidence("600519.SH")

    assert evidence["quote"]["price"] == 1330.0
    assert evidence["fundamental"] == {}
    assert evidence["fund_flow"]["status"] == "positive"
    assert evidence["sources"] == ["tushare", "tushare.moneyflow"]


@pytest.mark.asyncio
async def test_timeout_does_not_start_overlapping_same_request(monkeypatch):
    provider = TushareProvider(token="test-token")
    provider.request_timeout_seconds = 0.1
    provider.retry_attempts = 2
    provider.total_timeout_seconds = 1.0
    active = 0
    maximum_active = 0
    calls = 0

    class SlowPro:
        def daily(self, **_kwargs):
            nonlocal active, maximum_active, calls
            calls += 1
            active += 1
            maximum_active = max(maximum_active, active)
            try:
                import time
                time.sleep(0.25)
                raise TimeoutError("simulated provider timeout")
            finally:
                active -= 1

    monkeypatch.setitem(
        sys.modules,
        "tushare",
        SimpleNamespace(pro_api=lambda _token, timeout=30: SlowPro()),
    )
    monkeypatch.setattr(provider.request_budget, "reserve", AsyncMock(return_value=0.0))

    with pytest.raises(asyncio.TimeoutError):
        await provider._call("daily", ts_code="600519.SH")

    await asyncio.sleep(0.35)
    assert calls == 2
    assert maximum_active == 1
