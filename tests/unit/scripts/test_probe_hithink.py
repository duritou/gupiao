from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts import probe_hithink


class _FakeProvider:
    configured = True

    def __init__(self, fail: str = ""):
        self.fail = fail

    def runtime_stats(self):
        return {"calls": 7, "successes": 7, "failures": 0}

    def _payload(self, capability):
        if capability == self.fail:
            raise RuntimeError("request header must never be returned")
        if capability == "financial_indicators":
            data = {"abilities": [{"indicators": [{"index_id": "eps", "value": 1}]}]}
        elif capability == "dragon_tiger":
            data = {"stock_items": [], "hot_money_items": []}
        else:
            data = {"item": []}
        return SimpleNamespace(
            data=data,
            row_count=0,
            data_date="2026-09-11",
            is_live=False,
            request_id="req-probe",
        )

    async def fetch_snapshot(self, code):
        return self._payload("snapshot")

    async def fetch_valuation_snapshot(self, code):
        return self._payload("valuation")

    async def fetch_daily_history(self, code, start, end, adjust):
        return self._payload("daily_kline")

    async def fetch_financial_indicators(self, code, report):
        return self._payload("financial_indicators")

    async def fetch_limit_pool(self, kind, date, page, size):
        return self._payload("limit_up_pool" if kind == "up" else "limit_break_pool")

    async def fetch_dragon_tiger(self, date):
        return self._payload("dragon_tiger")


@pytest.mark.asyncio
async def test_probe_is_bounded_and_redacted():
    result = await probe_hithink.run_probe(
        "600519.SH",
        ["snapshot", "financial_indicators", "dragon_tiger"],
        provider=_FakeProvider(),
    )

    assert result["status"] == "completed"
    assert result["supported_count"] == 3
    assert all(item["is_live"] is False for item in result["results"])
    assert "request header" not in str(result)


@pytest.mark.asyncio
async def test_probe_reports_error_type_and_keeps_other_capabilities():
    result = await probe_hithink.run_probe(
        "600519.SH",
        ["snapshot", "valuation"],
        provider=_FakeProvider(fail="valuation"),
    )

    assert result["status"] == "completed"
    assert result["results"][0]["status"] == "supported"
    assert result["results"][1] == {
        "capability": "valuation",
        "status": "failed",
        "error_type": "runtimeerror",
        "elapsed_ms": result["results"][1]["elapsed_ms"],
    }


@pytest.mark.asyncio
async def test_probe_skips_without_credentials():
    class _Unconfigured:
        configured = False

    result = await probe_hithink.run_probe(provider=_Unconfigured())

    assert result == {"status": "not_configured", "code": "600519.SH", "results": []}
