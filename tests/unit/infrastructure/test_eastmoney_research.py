from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from src.api.routes import unified_research_routes
from src.infrastructure.market_data import eastmoney_billboard, eastmoney_common, eastmoney_reports


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_parse_billboard_rows_and_institution_amounts():
    records = eastmoney_billboard.parse_dragon_tiger_records([
        {
            "TRADE_DATE": "2026-08-29 00:00:00",
            "EXPLANATION": "连续三个交易日内涨幅偏离值累计达20%",
            "BILLBOARD_NET_AMT": 1234567,
            "TURNOVERRATE": "2.5",
        }
    ])
    seats = eastmoney_billboard.parse_dragon_tiger_seats([
        {
            "OPERATEDEPT_NAME": "机构专用",
            "BUY": 100000,
            "SELL": 20000,
            "NET": 80000,
        }
    ])

    assert records[0]["date"] == "2026-08-29"
    assert records[0]["net_buy"] == 123.5
    assert records[0]["turnover"] == 2.5
    assert seats[0]["buy_amt"] == 10.0
    assert seats[0]["net"] == 8.0


@pytest.mark.asyncio
async def test_fetch_billboard_queries_records_and_latest_seats(monkeypatch):
    monkeypatch.setattr(eastmoney_common, "pace", AsyncMock())
    calls: list[str] = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params):
            assert url == eastmoney_common.DATACENTER_URL
            calls.append(params["reportName"])
            rows = {
                "RPT_DAILYBILLBOARD_DETAILSNEW": [{
                    "TRADE_DATE": "2026-08-29",
                    "EXPLANATION": "涨幅偏离值",
                    "BILLBOARD_NET_AMT": 500000,
                    "TURNOVERRATE": 4.2,
                }],
                "RPT_BILLBOARD_DAILYDETAILSBUY": [{
                    "OPERATEDEPT_NAME": "机构专用",
                    "OPERATEDEPT_CODE": "0",
                    "BUY": 200000,
                    "SELL": 50000,
                    "NET": 150000,
                }],
                "RPT_BILLBOARD_DAILYDETAILSSELL": [{
                    "OPERATEDEPT_NAME": "机构专用",
                    "OPERATEDEPT_CODE": "0",
                    "BUY": 10000,
                    "SELL": 80000,
                    "NET": -70000,
                }],
            }
            return _Response({"result": {"data": rows[params["reportName"]]}})

    monkeypatch.setattr(eastmoney_billboard.httpx, "AsyncClient", lambda **kwargs: Client())

    result = await eastmoney_billboard.fetch_eastmoney_dragon_tiger(
        "600519.SH", trade_date="2026-08-31"
    )

    assert calls == [
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        "RPT_BILLBOARD_DAILYDETAILSBUY",
        "RPT_BILLBOARD_DAILYDETAILSSELL",
    ]
    assert result["_meta"]["provider"] == "eastmoney"
    assert result["_meta"]["point_in_time"] is True
    assert result["data"]["records"][0]["net_buy"] == 50.0
    assert result["data"]["institution"] == {
        "buy_amt": 20.0,
        "sell_amt": 8.0,
        "net_amt": 12.0,
    }


def test_parse_reports_adds_compatibility_fields():
    reports = eastmoney_reports.parse_eastmoney_reports({
        "data": [{
            "infoCode": "A123",
            "title": "行业深度报告",
            "publishDate": "2026-08-28",
            "orgSName": "测试证券",
        }]
    })

    assert reports[0]["id"] == "A123"
    assert reports[0]["publish_date"] == "2026-08-28"
    assert reports[0]["institution"] == "测试证券"
    assert reports[0]["pdfUrl"].endswith("H3_A123_1.pdf")


@pytest.mark.asyncio
async def test_unified_research_prefers_native_billboard_and_reports(monkeypatch):
    monkeypatch.setattr(
        eastmoney_billboard,
        "fetch_eastmoney_dragon_tiger",
        AsyncMock(return_value={"data": {"records": [{"date": "2026-08-29"}]}}),
    )
    monkeypatch.setattr(
        eastmoney_reports,
        "fetch_eastmoney_reports",
        AsyncMock(return_value={"reports": [{"id": "A123"}], "count": 1}),
    )

    class Provider:
        async def get_dragon_tiger(self, code):
            raise AssertionError(code)

        async def get_reports(self, code):
            raise AssertionError(code)

    board, reports = await asyncio.gather(
        unified_research_routes._dragon_tiger_with_native_fallback("600519", Provider()),
        unified_research_routes._reports_with_native_fallback("600519", Provider()),
    )

    assert board["data"]["records"][0]["date"] == "2026-08-29"
    assert reports["reports"][0]["id"] == "A123"
