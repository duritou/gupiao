import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.api.routes import research_routes, unified_research_routes
from src.agents import codex_stock_analyzer
from src.infrastructure.market_data import (
    cninfo_announcements,
    native_quote_views,
    sina_financials,
)
from src.infrastructure.market_data.source_manager import DataProvenance, source_manager


def _observations(days: int = 3) -> list[dict]:
    rows = []
    for offset in range(days):
        signal = date(2026, 1, 5) + timedelta(days=offset)
        forward = signal + timedelta(days=1)
        for rank, symbol in enumerate(("A", "B", "C"), start=1):
            rows.append(
                {
                    "date": signal.isoformat(),
                    "forward_date": forward.isoformat(),
                    "symbol": symbol,
                    "factor": rank + offset / 10,
                    "forward_return": rank / 100,
                    "horizon": 1,
                    "industry": "industry-a" if symbol != "C" else "industry-b",
                }
            )
    return rows


@pytest.mark.asyncio
async def test_factor_validation_endpoint_returns_point_in_time_report():
    request = research_routes.FactorValidationRequest(
        factor_name="momentum",
        observations=_observations(),
        horizons=[1],
        neutralize_by_industry=True,
    )

    response = await research_routes.validate_factor_endpoint(request)

    assert response["status"] == "ok"
    assert response["point_in_time"] is True
    assert response["neutralized_by_industry"] is True
    assert response["by_horizon"]["1"]["usable"] is True
    assert response["by_horizon"]["1"]["mean_ic"] > 0
    assert response["weight_update"] == "not_applied"


@pytest.mark.asyncio
async def test_factor_validation_rejects_lookahead_and_reports_sparse_data():
    invalid = research_routes.FactorValidationRequest(
        observations=[
            {
                "date": "2026-01-05",
                "forward_date": "2026-01-05",
                "symbol": "A",
                "factor": 1,
                "forward_return": 0.01,
            }
        ],
        horizons=[1],
    )
    with pytest.raises(HTTPException) as exc_info:
        await research_routes.validate_factor_endpoint(invalid)
    assert exc_info.value.status_code == 422
    assert "after date" in str(exc_info.value.detail)

    sparse = research_routes.FactorValidationRequest(
        observations=_observations(days=1)[:2],
        horizons=[1],
    )
    response = await research_routes.validate_factor_endpoint(sparse)
    assert response["status"] == "insufficient_data"
    assert response["by_horizon"]["1"]["usable"] is False


@pytest.mark.asyncio
async def test_unified_research_financials_use_native_before_vibe(monkeypatch):
    async def native(code):
        return {
            "data": {"code": code, "period": "2026-03-31"},
            "_meta": {"provider": "sina", "source_layer": "adaptive_native"},
        }

    class Provider:
        async def get_financials(self, code):
            raise AssertionError(f"Vibe financials should not be called for {code}")

    monkeypatch.setattr(sina_financials, "fetch_sina_financials", native)
    async def unavailable_statements(code):
        del code
        return {}, DataProvenance(provider="tushare", error_message="test unavailable")

    async def unavailable_history(code, periods=8):
        del code, periods
        return {}, DataProvenance(provider="tushare", error_message="test unavailable")

    monkeypatch.setattr(source_manager, "get_financial_statements", unavailable_statements)
    monkeypatch.setattr(source_manager, "get_financial_history", unavailable_history)

    result = await unified_research_routes._financials_with_native_fallback(
        "600519", Provider()
    )

    assert result["data"]["period"] == "2026-03-31"
    assert result["_meta"]["source_layer"] == "adaptive_native"


@pytest.mark.asyncio
async def test_unified_research_quote_views_use_native_before_vibe(monkeypatch):
    valuation = {
        "data": {"pe": 18.0},
        "_meta": {"source_layer": "adaptive_source_manager_quote"},
    }
    fundflow = {
        "data": {"main_net_pct": 11.11},
        "_meta": {"is_proxy": True, "source_layer": "adaptive_source_manager_quote"},
    }

    class Provider:
        async def get_valuation(self, code):
            raise AssertionError(f"Vibe valuation should not be called for {code}")

        async def get_fundflow(self, code):
            raise AssertionError(f"Vibe fundflow should not be called for {code}")

    monkeypatch.setattr(
        native_quote_views, "get_native_valuation", AsyncMock(return_value=valuation)
    )
    monkeypatch.setattr(
        native_quote_views, "get_native_fundflow", AsyncMock(return_value=fundflow)
    )
    async def unavailable_eod_quote(code):
        del code
        return None, DataProvenance(provider="none", error_message="test unavailable")

    async def unavailable_evidence(code):
        del code
        return {"quote": {}, "fund_flow": {}}

    async def unavailable_flow_history(code, days=20):
        del code, days
        return {}, DataProvenance(provider="tushare", error_message="test unavailable")

    monkeypatch.setattr(source_manager, "get_eod_quote", unavailable_eod_quote)
    monkeypatch.setattr(source_manager, "get_stock_evidence", unavailable_evidence)
    monkeypatch.setattr(source_manager, "get_fund_flow_history", unavailable_flow_history)

    result_valuation, result_fundflow = await asyncio.gather(
        unified_research_routes._valuation_with_native_fallback("600519", Provider()),
        unified_research_routes._fundflow_with_native_fallback("600519", Provider()),
    )

    assert result_valuation["data"]["pe"] == 18.0
    assert result_fundflow["data"]["main_net_pct"] == 11.11
    assert result_fundflow["_meta"]["is_proxy"] is True


@pytest.mark.asyncio
async def test_unified_research_announcements_use_cninfo_before_vibe(monkeypatch):
    native = {
        "announcements": [{"title": "annual report", "date": "2026-08-30"}],
        "count": 1,
        "_meta": {"provider": "cninfo", "source_layer": "adaptive_native"},
    }

    class Provider:
        async def get_announcements(self, code):
            raise AssertionError(f"Vibe announcements should not be called for {code}")

    monkeypatch.setattr(
        cninfo_announcements, "fetch_cninfo_announcements", AsyncMock(return_value=native)
    )

    result = await unified_research_routes._announcements_with_native_fallback(
        "600519", Provider()
    )

    assert result["announcements"][0]["date"] == "2026-08-30"
    assert result["_meta"]["provider"] == "cninfo"


@pytest.mark.asyncio
async def test_unified_research_candidate_preserves_market_evidence(monkeypatch):
    packet = {
        "quote": {
            "price": 25.91,
            "pre_close": 25.40,
            "change_pct": 2.01,
        },
        "fundamental": {"available": True},
        "fund_flow": {"data_date": "2026-09-04"},
        "sources": ["tushare", "tushare.fundamental", "tushare.moneyflow"],
        "provenance": {
            "quote": {
                "provider": "tushare",
                "data_date": "2026-09-04",
                "fetched_at": "2026-09-05T01:02:03",
            }
        },
    }
    monkeypatch.setattr(
        source_manager,
        "get_stock_evidence",
        AsyncMock(return_value=packet),
    )

    candidate = await unified_research_routes._candidate_with_market_evidence("300792.SZ")

    assert candidate["market_price"] == 25.91
    assert candidate["market_price_source"] == "tushare"
    assert candidate["market_price_date"] == "2026-09-04"
    assert candidate["market_sources"] == packet["sources"]
    assert candidate["stock_skill_evidence"]["quote"]["price"] == 25.91
    assert candidate["evidence_enrichment"]["provenance"] == packet["provenance"]


@pytest.mark.asyncio
async def test_unified_research_candidate_fetch_failure_stays_fail_closed(monkeypatch):
    monkeypatch.setattr(
        source_manager,
        "get_stock_evidence",
        AsyncMock(side_effect=TimeoutError("evidence timeout")),
    )

    candidate = await unified_research_routes._candidate_with_market_evidence("300792.SZ")

    assert candidate["market_sources"] == []
    assert "market_price" not in candidate
    assert candidate["market_reasons"] == [
        "market_evidence_fetch_failed:TimeoutError"
    ]
    assert "error" in candidate["evidence_enrichment"]


@pytest.mark.asyncio
async def test_unified_research_run_passes_enriched_candidate_to_deep_analyzer(monkeypatch):
    packet = {
        "quote": {"price": 25.91},
        "sources": ["tushare"],
        "provenance": {"quote": {"provider": "tushare", "data_date": "2026-09-04"}},
    }
    analyze = AsyncMock(return_value=[{
        "available": True,
        "stock_code": "300792",
        "direction": "neutral",
        "rating": "Hold",
        "score": 50.0,
    }])
    monkeypatch.setattr(source_manager, "get_stock_evidence", AsyncMock(return_value=packet))
    monkeypatch.setattr(codex_stock_analyzer, "analyze_candidates", analyze)
    monkeypatch.setattr(unified_research_routes, "_persist", lambda job: None)

    job_id = "research-unit-market-evidence"
    unified_research_routes._JOBS[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "stage": "queued",
        "progress": 0,
    }
    try:
        await unified_research_routes._run_job(
            job_id,
            unified_research_routes.UnifiedResearchRequest(
                code="300792",
                trade_date="2026-09-04",
                include_vibe=False,
                include_tradingagents=True,
            ),
            "300792",
            "2026-09-04",
        )
    finally:
        unified_research_routes._JOBS.pop(job_id, None)

    candidate = analyze.call_args.args[0][0]
    assert candidate["market_price"] == 25.91
    assert candidate["market_sources"] == ["tushare"]
    assert candidate["market_price_date"] == "2026-09-04"
