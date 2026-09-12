from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from config.settings import settings
from src.infrastructure.market_data import source_manager as source_manager_module
from src.infrastructure.market_data.hithink_consistency import (
    compare_financial_indicators,
)
from src.infrastructure.market_data.source_manager import DataProvenance, SourceManager


def test_indicator_comparison_reports_match_mismatch_without_values():
    result = compare_financial_indicators(
        {"eps": 1.0, "roe": 10.0},
        {
            "report": "2026-2",
            "abilities": [
                {
                    "ability": "quality",
                    "indicators": [
                        {"index_id": "basic_eps", "value": 1.005},
                        {"index_id": "roe", "value": 12.0},
                    ],
                }
            ],
        },
    )

    assert result["status"] == "mismatch"
    assert result["compared_fields"] == 2
    assert result["matches"] == 1
    assert result["mismatches"] == 1
    assert all("value" not in item for item in result["fields"])


def test_indicator_comparison_is_insufficient_when_null_or_missing():
    result = compare_financial_indicators(
        {"eps": None, "roe": 10.0},
        {"abilities": [{"indicators": [{"index_id": "roe", "value": None}]}]},
    )

    assert result["status"] == "insufficient"
    assert result["compared_fields"] == 0


@pytest.mark.asyncio
async def test_stock_evidence_keeps_tushare_values_and_attaches_hithink_audit(monkeypatch):
    class _FakeHiThink:
        configured = True

        async def fetch_financial_indicators(self, code, report):
            return SimpleNamespace(
                data={
                    "report": report,
                    "abilities": [
                        {
                            "ability": "quality",
                            "indicators": [
                                {"index_id": "eps", "value": 1.0},
                                {"index_id": "roe", "value": 10.0},
                            ],
                        }
                    ],
                },
                request_id="req-indicator-audit",
                data_date="2026-06-30",
                fetched_at="2026-09-12T01:00:00+00:00",
            )

    class _FakeTushare:
        async def fetch_fundamental(self, code):
            return SimpleNamespace(
                data={
                    "eps": 1.0,
                    "roe": 10.0,
                    "data_date": "2026-06-30",
                },
                data_date="2026-06-30",
                endpoint="fina_indicator+income",
            )

    async def flow(code, days):
        return {
            "status": "positive",
            "main_net": 1.0,
            "data_date": "2026-09-11",
            "endpoint": "moneyflow",
        }

    manager = SourceManager()
    monkeypatch.setattr(source_manager_module, "hithink_provider", _FakeHiThink())
    monkeypatch.setattr(source_manager_module, "tushare_provider", _FakeTushare())
    monkeypatch.setattr(settings, "HITHINK_FINANCIAL_MODE", "validator")
    monkeypatch.setattr(
        manager,
        "_bounded_research_quote",
        AsyncMock(
            return_value=(
                {"stock_code": "600519.SH", "price": 100.0},
                DataProvenance(provider="tushare"),
            )
        ),
    )
    monkeypatch.setattr(
        "src.infrastructure.market_data.research_flow.get_research_flow",
        flow,
    )

    evidence = await manager.get_stock_evidence("600519.SH")

    assert evidence["fundamental"]["roe"] == 10.0
    audit = evidence["provenance"]["fundamental"]["hithink_validation"]
    assert audit["status"] == "match"
    assert audit["provider"] == "hithink"
    assert audit["request_id"] == "req-indicator-audit"
