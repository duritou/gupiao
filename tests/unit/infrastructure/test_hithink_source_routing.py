from __future__ import annotations

from dataclasses import dataclass

import pytest

from config.settings import settings
from src.infrastructure.market_data import source_manager as source_manager_module
from src.infrastructure.market_data.source_manager import source_manager


@dataclass
class _Payload:
    data: list[dict]
    data_date: str = "2026-09-11"
    endpoint: str = "/api/a-share/prices/historical"
    fetched_at: str = "2026-09-12T01:00:00+00:00"


class _FakeHiThink:
    configured = True

    async def fetch_daily_history(self, code, start, end, adjust):
        assert code == "600519.SH"
        assert start < end
        assert adjust == "none"
        return _Payload(
            [
                {
                    "date": "2026-09-10",
                    "open": 1200,
                    "high": 1210,
                    "low": 1190,
                    "close": 1205,
                    "volume": 100,
                    "amount": 120500,
                },
                {
                    "date": "2026-09-11",
                    "open": 1205,
                    "high": 1220,
                    "low": 1200,
                    "close": 1215,
                    "volume": 110,
                    "amount": 133650,
                },
            ]
        )


class _FakeFinancialHiThink:
    configured = True

    async def fetch_financial_history(self, code, period, limit):
        return _Payload(
            {
                "statements": {
                    "income": [
                        {
                            "thscode": code,
                            "period_end_ms": 1767139200000,
                            "report_date_ms": 1774915200000,
                            "net_profit": None,
                        }
                    ]
                }
            }
        )


@pytest.mark.asyncio
async def test_hithink_kline_dispatch_returns_dated_non_live_bars(monkeypatch):
    monkeypatch.setattr(source_manager_module, "hithink_provider", _FakeHiThink())
    monkeypatch.setattr(settings, "HITHINK_DAILY_MODE", "validator")

    bars, provenance = await source_manager._dispatch_kline("hithink", "600519.SH", 2)

    assert bars is not None
    assert [bar["date"] for bar in bars] == ["2026-09-10", "2026-09-11"]
    assert provenance.provider == "hithink"
    assert provenance.is_live is False
    assert provenance.data_date == "2026-09-11"
    assert provenance.coverage_ratio == 1.0


def test_hithink_is_not_ranked_when_daily_mode_is_shadow_or_disabled(monkeypatch):
    monkeypatch.setattr(source_manager_module, "hithink_provider", _FakeHiThink())
    for mode in ("shadow", "disabled"):
        monkeypatch.setattr(settings, "HITHINK_DAILY_MODE", mode)
        assert "hithink" not in source_manager._get_ranked_providers("600519.SH", "daily_kline")


@pytest.mark.asyncio
async def test_financial_fallback_only_adds_missing_periods(monkeypatch):
    class _Database:
        def __init__(self):
            self.rows = {"income": [{"end_date": "2024-12-31", "net_profit": 10}]}

        def upsert_financial_history(self, code, statements, **kwargs):
            self.rows.setdefault("income", []).extend(statements.get("income") or [])

        def get_financial_history(self, code, limit):
            return {name: list(rows) for name, rows in self.rows.items()}

    class _DatabaseModule:
        market_db = _Database()

    monkeypatch.setattr(source_manager_module, "hithink_provider", _FakeFinancialHiThink())
    monkeypatch.setattr(settings, "HITHINK_FINANCIAL_MODE", "fallback")

    merged, used, error = await source_manager._augment_financial_history_with_hithink(
        "600519.SH",
        2,
        _DatabaseModule.market_db.get_financial_history("600519.SH", 2),
        _DatabaseModule,
    )

    assert used is True
    assert error == ""
    assert len(merged["income"]) == 2
    assert merged["income"][0]["net_profit"] == 10
    assert merged["income"][1]["end_date"] == "2025-12-31"


@pytest.mark.asyncio
async def test_get_financial_history_reports_hithink_only_after_tushare_failure(monkeypatch):
    class _Database:
        def __init__(self):
            self.rows = {}

        def get_financial_history(self, code, limit):
            return {name: list(rows) for name, rows in self.rows.items()}

        def upsert_financial_history(self, code, statements, **kwargs):
            for name, rows in statements.items():
                self.rows.setdefault(name, []).extend(rows)

    class _FailingTushare:
        async def fetch_financial_history(self, code, periods):
            raise TimeoutError("tushare unavailable")

    import src.infrastructure.storage.market_database as database_module

    database = _Database()
    monkeypatch.setattr(database_module, "market_db", database)
    monkeypatch.setattr(source_manager_module, "tushare_provider", _FailingTushare())
    monkeypatch.setattr(source_manager_module, "hithink_provider", _FakeFinancialHiThink())
    monkeypatch.setattr(settings, "HITHINK_FINANCIAL_MODE", "fallback")

    data, provenance = await source_manager.get_financial_history("600519.SH", periods=1)

    assert data["available"] is True
    assert data["source"] == "hithink"
    assert data["period_counts"]["income"] == 1
    assert provenance.provider == "hithink"
    assert provenance.source_name == "HiThink多期财报"
    assert provenance.is_cached is True
