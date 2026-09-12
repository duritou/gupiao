import asyncio
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from config.settings import settings
from src.agents import codex_stock_analyzer as analyzer
from src.infrastructure.market_data import (
    cninfo_announcements,
    eastmoney_billboard,
    eastmoney_reports,
    native_quote_views,
    sina_financials,
    vibe_provider,
)
from src.infrastructure.market_data.source_manager import DataProvenance, source_manager


@pytest.mark.asyncio
async def test_unavailable_codex_returns_fail_closed_diagnostics(monkeypatch):
    monkeypatch.setattr(analyzer, "availability_status", lambda: {
        "available": False,
        "reasons": ["codex_cli_or_login_missing"],
    })

    results = await analyzer.analyze_candidates(
        [{"stock_code": "000001.SZ"}], "2026-08-24", limit=1
    )

    assert results[0]["available"] is False
    assert results[0]["provider"] == "codex_cli"
    assert results[0]["model"] == settings.CODEX_MODEL


@pytest.mark.asyncio
async def test_valid_codex_analysis_preserves_terra_metadata(monkeypatch):
    monkeypatch.setattr(analyzer, "_collect_evidence", AsyncMock(return_value={
        "quote": 10,
        "kline_summary": {"visible_count": 60, "visible_last_date": "2026-08-21"},
        "kline_provenance": {"provider": "tickflow"},
    }))
    generate = AsyncMock(return_value=SimpleNamespace(
        text=(
            '{"rating":"Overweight","score":74,"thesis":"证据偏多",'
            '"decision":"回踩确认后考虑","trader_plan":"上限5%",'
            '"evidence_gaps":["北向资金"]}'
        ),
        provider="codex_cli",
        model="gpt-5.6-terra",
    ))
    monkeypatch.setattr(analyzer.ai_router, "generate", generate)

    result = await analyzer._analyze_one(
        {"stock_code": "000001.SZ", "stock_name": "测试"},
        "2026-08-24",
        "历史复盘",
    )

    assert result["available"] is True
    assert result["rating"] == "Overweight"
    assert result["direction"] == "buy"
    assert result["provider"] == "codex_cli"
    assert result["model"] == "gpt-5.6-terra"
    assert result["falsification_conditions"] == []
    assert result["monitoring_signals"] == []
    assert result["kline_evidence"]["visible_last_date"] == "2026-08-21"
    assert result["kline_evidence"]["provenance"]["provider"] == "tickflow"
    assert generate.await_args.kwargs["allow_fallback"] is False
    assert generate.await_args.kwargs["primary_provider"] == "codex_cli"
    assert "falsification_conditions" in generate.await_args.kwargs["prompt"]


@pytest.mark.asyncio
async def test_malformed_codex_output_is_not_actionable(monkeypatch):
    monkeypatch.setattr(analyzer, "availability_status", lambda: {
        "available": True,
        "reasons": [],
    })
    monkeypatch.setattr(analyzer, "_collect_evidence", AsyncMock(return_value={}))
    monkeypatch.setattr(
        analyzer.ai_router,
        "generate",
        AsyncMock(return_value=SimpleNamespace(
            text="not-json", provider="codex_cli", model="gpt-5.6-terra"
        )),
    )

    results = await analyzer.analyze_candidates(
        [{
            "stock_code": "000001.SZ",
            "market_sources": ["sina"],
            "market_price": 10.0,
        }], "2026-08-24", limit=1
    )

    assert results[0]["available"] is False
    assert results[0]["error_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_candidate_order_is_stable_with_bounded_concurrency(monkeypatch):
    monkeypatch.setattr(analyzer, "availability_status", lambda: {
        "available": True,
        "reasons": [],
    })
    monkeypatch.setattr(settings, "CODEX_ANALYSIS_MAX_CONCURRENCY", 2)
    active = 0
    peak = 0

    async def analyze(candidate, trade_date, context):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {"available": True, "stock_code": candidate["stock_code"]}

    monkeypatch.setattr(analyzer, "_analyze_one", analyze)
    results = await analyzer.analyze_candidates(
        [{
            "stock_code": code,
            "market_sources": ["sina"],
            "market_price": 10.0,
        } for code in ("A", "B", "C")],
        "2026-08-24",
        limit=3,
    )

    assert peak == 2
    assert [item["stock_code"] for item in results] == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_missing_market_evidence_never_enters_deep_analysis(monkeypatch):
    monkeypatch.setattr(analyzer, "availability_status", lambda: {
        "available": True,
        "reasons": [],
    })
    analyze = AsyncMock()
    monkeypatch.setattr(analyzer, "_analyze_one", analyze)

    results = await analyzer.analyze_candidates(
        [{"stock_code": "000001.SZ"}], "2026-08-24", limit=1
    )

    assert results[0]["error_type"] == "MarketEvidenceUnavailable"
    assert results[0]["market_evidence_reasons"] == [
        "market_sources_missing", "market_quote_missing"
    ]
    analyze.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("bar_count,reverse", [(0, False), (8, False), (80, False), (80, True)])
async def test_collect_evidence_uses_native_financials_before_vibe(monkeypatch, bar_count, reverse):
    bars = [{
        "date": (date(2026, 9, 3) - timedelta(days=bar_count - i - 1)).isoformat(),
        "close": 10.0 + i,
    } for i in range(bar_count)]
    async def native(code):
        return {
            "data": {
                "code": code,
                "period": "2026-03-31",
                "revenue": "130",
            },
            "_meta": {
                "provider": "sina",
                "source_layer": "adaptive_native",
                "available": True,
                "point_in_time": True,
            },
        }

    async def native_announcements(code):
        return {
            "announcements": [{"title": "annual report", "date": "2026-08-30"}],
            "count": 1,
            "_meta": {"provider": "cninfo", "source_layer": "adaptive_native"},
        }

    async def kline(code, count=80):
        del code, count
        return list(reversed(bars)) if reverse else bars, DataProvenance(provider="test", is_live=True)

    class Provider:
        async def get_financials(self, code):
            raise AssertionError(f"Vibe financials should not be called for {code}")

        async def get_valuation(self, code):
            del code
            return {"data": {}}

        async def get_announcements(self, code):
            raise AssertionError(f"Vibe announcements should not be called for {code}")

        async def get_fundflow(self, code):
            del code
            return {"data": {}}

        async def get_dragon_tiger(self, code):
            del code
            return {"data": {}}

        async def get_reports(self, code):
            del code
            return {"data": {}}

    class Cache:
        def __init__(self, path):
            del path

        def remember_or_stale(self, key, evidence):
            del key
            return evidence

    monkeypatch.setattr(sina_financials, "fetch_sina_financials", native)
    monkeypatch.setattr(cninfo_announcements, "fetch_cninfo_announcements", native_announcements)
    monkeypatch.setattr(
        eastmoney_billboard,
        "fetch_eastmoney_dragon_tiger",
        AsyncMock(return_value={"data": {}, "_meta": {"available": False}}),
    )
    monkeypatch.setattr(
        eastmoney_reports,
        "fetch_eastmoney_reports",
        AsyncMock(return_value={"reports": [], "count": 0, "_meta": {"available": False}}),
    )
    monkeypatch.setattr(native_quote_views, "get_native_valuation", AsyncMock(return_value=None))
    monkeypatch.setattr(native_quote_views, "get_native_fundflow", AsyncMock(return_value=None))
    monkeypatch.setattr(source_manager, "get_kline", kline)

    async def unavailable_statements(code):
        del code
        return {}, DataProvenance(provider="tushare", error_message="test unavailable")

    async def unavailable_financial_history(code, periods=8):
        del code, periods
        return {}, DataProvenance(provider="tushare", error_message="test unavailable")

    async def unavailable_flow_history(code, days=20):
        del code, days
        return {}, DataProvenance(provider="tushare", error_message="test unavailable")

    async def unavailable_eod_quote(code):
        del code
        return None, DataProvenance(provider="none", error_message="test unavailable")

    async def unavailable_evidence(code):
        del code
        return {"quote": {}, "fundamental": {}, "fund_flow": {}}

    async def unavailable_board(code):
        del code
        return {}, DataProvenance(provider="tushare", error_message="test unavailable")

    monkeypatch.setattr(source_manager, "get_financial_statements", unavailable_statements)
    monkeypatch.setattr(source_manager, "get_financial_history", unavailable_financial_history)
    monkeypatch.setattr(source_manager, "get_fund_flow_history", unavailable_flow_history)
    monkeypatch.setattr(source_manager, "get_eod_quote", unavailable_eod_quote)
    monkeypatch.setattr(source_manager, "get_stock_evidence", unavailable_evidence)
    monkeypatch.setattr(source_manager, "get_dragon_tiger", unavailable_board)
    monkeypatch.setattr(analyzer, "EvidenceDossierCache", Cache)
    monkeypatch.setattr(vibe_provider, "get_vibe_provider", lambda: Provider())

    result = await analyzer._collect_evidence({"stock_code": "600519.SH"})

    assert result["kline"] == bars[-60:]
    assert result["kline_summary"]["received_count"] == bar_count
    assert result["kline_summary"]["visible_count"] == min(bar_count, 60)
    assert result["kline_summary"]["available"] is bool(bar_count)
    assert result["kline_provenance"]["provider"] == "test"
    if bars:
        assert result["kline_summary"]["visible_last_date"] == "2026-09-03"
        assert result["kline_summary"]["visible_first_date"] == bars[-60:][0]["date"]

    financials = result["fact_dossier"]["items"]["financials"]
    assert financials["status"] == "available"
    assert "adaptive_native" in financials["payload"]
    assert "2026-03-31" in financials["payload"]
    announcements = result["fact_dossier"]["items"]["announcements"]
    assert announcements["status"] == "available"
    assert "cninfo" in announcements["payload"]


def test_kline_compaction_does_not_change_other_list_sampling():
    evidence = analyzer._compact({"reports": list(range(80))})
    assert evidence["reports"] == list(range(20))
