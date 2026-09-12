from __future__ import annotations

import pytest

from src.infrastructure.market_data import sina_financials


def _payload(period: str, *, revenue: str = "100") -> dict:
    return {
        "result": {
            "data": {
                "report_list": {
                    period: {
                        "data": [
                            {
                                "item_title": "\u8425\u4e1a\u6536\u5165",
                                "item_value": revenue,
                                "item_tongbi": "12.5",
                            },
                            {"item_title": "\u51c0\u5229\u6da6", "item_value": "20"},
                            {
                                "item_title": "\u57fa\u672c\u6bcf\u80a1\u6536\u76ca",
                                "item_value": "0.20",
                            },
                        ]
                    }
                }
            }
        }
    }


def test_parse_sina_financial_payload_keeps_report_period_and_yoy():
    old_period = _payload("20250331")["result"]["data"]["report_list"]["20250331"]
    new_period = _payload("20260331", revenue="130")["result"]["data"]["report_list"]["20260331"]
    payload = {
        "result": {
            "data": {
                "report_list": {
                    "20250331": old_period,
                    "20260331": new_period,
                }
            }
        }
    }

    rows = sina_financials.parse_sina_financial_payload(payload, limit=8)

    assert [row["report_date"] for row in rows] == ["2026-03-31", "2025-03-31"]
    assert rows[0]["\u8425\u4e1a\u6536\u5165"] == "130"
    assert rows[0]["\u8425\u4e1a\u6536\u5165_\u540c\u6bd4"] == "12.5"


@pytest.mark.asyncio
async def test_fetch_sina_financials_returns_native_point_in_time_metadata(monkeypatch):
    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params):
            del url
            source = params["source"]
            if source == "lrb":
                return FakeResponse(_payload("20260331", revenue="130"))
            return FakeResponse(_payload("20251231"))

    monkeypatch.setattr(sina_financials.httpx, "AsyncClient", lambda **kwargs: FakeClient())

    result = await sina_financials.fetch_sina_financials("600519.SH")

    assert result["_meta"]["source_layer"] == "adaptive_native"
    assert result["_meta"]["point_in_time"] is True
    assert result["_meta"]["latest_report_date"] == "2026-03-31"
    assert result["data"]["period"] == "2026-03-31"
    assert result["data"]["revenue"] == "130"
    assert set(result["data"]["statements"]) == {
        "income_statement",
        "balance_sheet",
        "cash_flow_statement",
    }
