import pytest

from src.ai_os.candidate_evidence_enricher import (
    _apply_component_evidence,
    enrich_candidate_evidence,
)
from src.ai_os.cross_sectional_scoring import refresh_execution_gate
from src.ai_os.execution_policy import ExecutionTier, evaluate_entry_execution


def _decision(code: str, score: float) -> dict:
    return {
        "stock_code": code,
        "stock_name": code,
        "ranking_score": score,
        "technical_score": score - 2,
        "discovery_score": score - 4,
        "evidence": "{}",
    }


@pytest.mark.asyncio
async def test_failed_quote_provenance_survives_evidence_serialization():
    import json
    decisions = [_decision('300792.SZ', 88)]
    discovery = {'300792.SZ': {'stock_code': '300792.SZ', 'sources': []}}
    provenance = {'quote': {'error': 'tushare_primary:TimeoutError'}}

    async def fetch(codes):
        return {'300792.SZ': {'error': 'quote_missing', 'provenance': provenance}}

    await enrich_candidate_evidence(decisions, discovery, quote_fetcher=fetch)
    assert decisions[0]['evidence_enrichment']['provenance'] == provenance
    saved = json.loads(decisions[0]['evidence'])
    assert saved['market_discovery']['evidence_enrichment']['provenance'] == provenance


@pytest.mark.asyncio
async def test_enrichment_fetches_only_bounded_high_score_candidates(monkeypatch):
    from src.infrastructure.storage.market_database import market_db

    monkeypatch.setattr(
        market_db, "get_fund_flow_history", lambda *_args: []
    )
    monkeypatch.setattr(
        market_db, "get_financial_history", lambda *_args: {}
    )
    decisions = [_decision("000001.SZ", 88), _decision("600000.SH", 80)]
    decisions.append(_decision("000002.SZ", 64))
    discovery = {code: {"stock_code": code, "sources": []} for code in (
        "000001.SZ", "600000.SH", "000002.SZ"
    )}
    requested = []

    async def fetch(codes):
        requested.extend(codes)
        return {
            code: {
                "quote": {
                    "price": 10.0,
                    "source": "tickflow_live_quote",
                    "data_date": "2026-09-01",
                }
            }
            for code in codes
        }

    stats = await enrich_candidate_evidence(
        decisions,
        discovery,
        quote_fetcher=fetch,
        max_candidates=1,
    )

    assert requested == ["000001.SZ"]
    assert stats["eligible_count"] == 2
    assert stats["attempted_count"] == 1
    assert stats["quote_success_count"] == 1
    assert stats["not_scheduled_count"] == 2
    assert stats["not_scheduled_reason_counts"] == {
        "below_min_ranking_score": 1,
        "enrichment_queue_budget_exhausted": 1,
    }
    assert discovery["000001.SZ"]["quote"]["price"] == 10.0
    assert "tickflow_live_quote" in decisions[0]["market_sources"]
    assert decisions[0]["evidence_enrichment"]["quote_available"] is True
    assert decisions[2]["quote_enrichment_status"] == "not_scheduled"
    assert decisions[2]["quote_enrichment_reason"] == "below_min_ranking_score"
    assert decisions[2]["flow_fallback_observation"] == {
        "attempted": False,
        "status": "not_scheduled",
        "reason": "below_min_ranking_score",
    }
    assert decisions[1]["quote_enrichment_reason"] == "enrichment_queue_budget_exhausted"
    assert decisions[1]["flow_fallback_observation"]["status"] == "not_scheduled"
    assert decisions[1].get("evidence_enrichment") is None


@pytest.mark.asyncio
async def test_enrichment_preserves_existing_quote_and_records_failures():
    decisions = [_decision("000001.SZ", 88), _decision("600000.SH", 82)]
    discovery = {
        "000001.SZ": {
            "stock_code": "000001.SZ",
            "sources": ["tickflow_live_quote"],
            "quote": {"price": 11.0, "source": "tickflow_live_quote"},
        },
        "600000.SH": {"stock_code": "600000.SH", "sources": []},
    }
    requested = []

    async def fetch(codes):
        requested.extend(codes)
        return {"600000.SH": {"error": "provider_circuit_open"}}

    stats = await enrich_candidate_evidence(
        decisions,
        discovery,
        quote_fetcher=fetch,
    )

    assert requested == ["000001.SZ", "600000.SH"]
    assert stats["quote_success_count"] == 0
    assert stats["quote_failure_count"] == 2
    assert decisions[0]["evidence_enrichment"]["reason"] == "evidence_enrichment_quote_failed"
    assert decisions[0]["market_price"] == 11.0
    assert "evidence_enrichment_quote_failed" in decisions[1]["market_evidence_reasons"]


@pytest.mark.asyncio
async def test_enrichment_refreshes_flow_metadata_without_recomputing_score():
    decision = _decision("000001.SZ", 88)
    decision.update({
        "ranking_score": 88.0,
        "technical_score": 78.0,
        "strategy_confirmations": 3,
        "pre_gate_direction": "buy",
        "direction": "neutral",
        "final_direction": "neutral",
        "gate_reasons": ["fund_flow_missing"],
        "flow_status": "missing",
        "market_flow": {},
    })
    discovery = {"000001.SZ": {"stock_code": "000001.SZ", "sources": []}}

    async def fetch(_codes):
        return {
            "000001.SZ": {
                "quote": {
                    "price": 10.0,
                    "source": "tushare",
                    "data_date": "2026-09-04",
                },
                "evidence": {
                    "fund_flow": {
                        "status": "positive",
                        "main_net": 100.0,
                        "source": "tushare.moneyflow",
                    }
                },
            }
        }

    await enrich_candidate_evidence([decision], discovery, quote_fetcher=fetch)

    assert decision["ranking_score"] == 88.0
    assert decision["flow_state"] == "positive"
    assert decision["flow_status"] == "positive"
    assert "tushare.moneyflow" in decision["flow_sources"]
    assert decision["direction"] == "neutral"

    refresh_execution_gate(decision)

    assert decision["ranking_score"] == 88.0
    assert decision["pre_gate_direction"] == "buy"
    assert decision["direction"] == "buy"
    assert decision["gate_reasons"] == []


@pytest.mark.asyncio
async def test_quote_failure_keeps_successful_component_evidence():
    decision = _decision("999998.SZ", 88)
    discovery = {"999998.SZ": {"stock_code": "999998.SZ", "sources": []}}
    evidence = {
        "fundamental": {"available": True, "source": "tushare"},
        "fund_flow": {
            "status": "positive",
            "main_net": 12.0,
            "source": "tushare.moneyflow",
        },
    }

    async def fetch(_codes):
        return {
            "999998.SZ": {
                "error": "quote_missing",
                "evidence": evidence,
                "provenance": {"provider": "tushare"},
            }
        }

    await enrich_candidate_evidence([decision], discovery, quote_fetcher=fetch)

    assert decision["flow_state"] == "positive"
    assert decision["fundamental_evidence_available"] is True
    assert decision.get("market_price", 0) == 0
    assert decision["evidence_enrichment"]["quote_available"] is False


@pytest.mark.asyncio
async def test_flow_provider_failure_is_attempted_but_remains_blocked():
    decision = _decision("999996.SZ", 88)
    decision.update({
        "pre_gate_direction": "buy",
        "final_direction": "neutral",
        "market_flow": {},
        "flow_status": "missing",
    })
    discovery = {"999996.SZ": {"stock_code": "999996.SZ", "sources": []}}
    provenance = {
        "fund_flow": {
            "provider": "tushare",
            "available": False,
            "error": "Tushare 资金流获取失败: TimeoutError",
        }
    }

    async def fetch(_codes):
        return {
            "999996.SZ": {
                "error": "quote_missing",
                "evidence": {
                    "fund_flow": {},
                    "provenance": provenance,
                },
                "provenance": provenance,
            }
        }

    await enrich_candidate_evidence(
        [decision], discovery, quote_fetcher=fetch
    )

    assert decision["fallback_attempted"] is True
    assert decision["fallback_status"] == "provider_error"
    assert decision["flow_fallback_observation"]["status"] == "provider_error"
    gate = evaluate_entry_execution(decision)
    assert gate["tier"] == ExecutionTier.BLOCKED.value
    assert gate["reason"] == "flow_fallback_incomplete"


@pytest.mark.asyncio
async def test_local_complete_components_are_hydrated_before_network(monkeypatch):
    from src.infrastructure.storage.market_database import market_db

    code = "999997.SZ"
    flow_rows = [
        {
            "ts_code": code,
            "trade_date": f"2026-09-{20 - index:02d}",
            "main_net": 1.0,
            "source": "tushare",
        }
        for index in range(20)
    ]
    financials = {
        name: [{"end_date": f"202{6 - index}-12-31"} for index in range(8)]
        for name in ("income", "balancesheet", "cashflow", "fina_indicator")
    }
    monkeypatch.setattr(
        market_db, "get_fund_flow_history", lambda _code, _limit: flow_rows
    )
    monkeypatch.setattr(
        market_db, "get_financial_history", lambda _code, _limit: financials
    )
    decision = _decision(code, 64)
    discovery = {code: {"stock_code": code, "sources": []}}
    requested = []

    async def fetch(codes):
        requested.extend(codes)
        return {}

    stats = await enrich_candidate_evidence(
        [decision], discovery, quote_fetcher=fetch
    )

    assert requested == []
    assert stats["cached_flow_count"] == 1
    assert stats["cached_financial_count"] == 1
    assert decision["flow_state"] == "positive"
    assert decision["fundamental_evidence_available"] is True


def test_summary_does_not_replace_complete_financial_history():
    decision = _decision("000069.SZ", 88)
    item = {"stock_code": "000069.SZ", "sources": []}
    complete = {
        "available": True,
        "statements": {
            name: [{"end_date": f"202{i}-12-31"} for i in range(8)]
            for name in ("income", "balancesheet", "cashflow", "fina_indicator")
        },
        "period_counts": {name: 8 for name in (
            "income", "balancesheet", "cashflow", "fina_indicator"
        )},
        "requested_periods": 8,
        "source_layer": "adaptive_local_cache",
    }
    _apply_component_evidence(decision, item, {"fundamental": complete})
    _apply_component_evidence(decision, item, {"fundamental": {
        "available": True, "eps": 1.2, "roe": 9.0, "source": "tushare"
    }})

    fundamental = decision["fundamentals"]
    assert all(len(fundamental["statements"][name]) == 8 for name in fundamental["statements"])
    assert fundamental["period_counts"]["cashflow"] == 8
    assert fundamental["eps"] == 1.2
