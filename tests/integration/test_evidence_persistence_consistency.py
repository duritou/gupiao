"""Verify the evidence contract from enrichment through persisted execution."""

import json

import pytest

from src.ai_os.candidate_evidence_enricher import enrich_candidate_evidence
from src.ai_os.cross_sectional_scoring import refresh_execution_gate
from src.ai_os.execution_policy import evaluate_entry_execution
from src.ai_os.score_guard import apply_score_guard
from src.infrastructure.storage.market_database import MarketDatabase


@pytest.mark.asyncio
async def test_flow_state_source_and_gate_survive_db_round_trip(tmp_path):
    database = MarketDatabase(tmp_path / "evidence-round-trip.db")
    decision = {
        "date": "2026-09-04",
        "stock_code": "000001.SZ",
        "stock_name": "evidence round trip",
        "ranking_score": 88.0,
        "ai_score": 88.0,
        "technical_score": 78.0,
        "discovery_score": 70.0,
        "strategy_confirmations": 3,
        "buy_signals": 3,
        "direction": "neutral",
        "final_direction": "neutral",
        "pre_gate_direction": "buy",
        "gate_reasons": ["fund_flow_missing"],
        "non_flow_gates_passed": True,
        "flow_status": "missing",
        "market_flow": {},
        "market_sources": [],
        "evidence": "{}",
    }
    discovery = {
        "000001.SZ": {
            "stock_code": "000001.SZ",
            "sources": [],
            "reasons": [],
        }
    }

    async def fetch(_codes):
        return {
            "000001.SZ": {
                "quote": {
                    "price": 10.0,
                    "source": "tushare",
                    "data_date": "2026-09-04",
                    "fetched_at": "2026-09-05T09:00:00+08:00",
                },
                "evidence": {
                    "fundamental": {
                        "available": True,
                        "source": "tushare",
                        "data_date": "2026-06-30",
                        "net_profit": 10.0,
                    },
                    "fund_flow": {
                        "status": "positive",
                        "source": "tushare.moneyflow",
                        "main_net": 100.0,
                        "data_date": "2026-09-04",
                    },
                },
            }
        }

    await enrich_candidate_evidence(
        [decision], discovery, quote_fetcher=fetch, max_candidates=1
    )
    refresh_execution_gate(decision)
    apply_score_guard(decision, discovery["000001.SZ"])
    decision["strategy_version"] = "2.2.0-evidence-routing"
    decision["signal_at"] = "2026-09-05T09:00:00+08:00"
    decision["data_cutoff_at"] = "2026-09-05T08:59:00+08:00"

    journal_id = database.save_decision(decision)
    database.save_strategy_decision(decision, journal_id)
    loaded = database.get_decisions_for_date("2026-09-04", limit=10)[0]
    persisted_analysis = database.get_strategy_context("000001.SZ", limit=1)[0]["analysis"]

    assert loaded["flow_state"] == "positive"
    assert loaded["flow_status"] == "positive"
    assert "tushare.moneyflow" in loaded["flow_sources"]
    assert loaded["market_flow"]["main_net"] == 100.0
    assert loaded["market_sources"] == ["tushare", "tushare.moneyflow"]
    assert loaded["quote_enrichment_status"] == "available"
    assert loaded["quote_enrichment_reason"] == "fetched"
    assert persisted_analysis["market_price_source"] == "tushare"
    assert json.loads(loaded["evidence"])["market_discovery"]["fund_flow"]["status"] == "positive"
    assert evaluate_entry_execution(loaded)["flow_state"] == "positive"


@pytest.mark.asyncio
async def test_positive_flow_does_not_clear_fundamental_guard(monkeypatch):
    from src.infrastructure.storage.market_database import market_db

    # Keep this guard test independent from the production warehouse.  The
    # production backfill may legitimately make this symbol's local evidence
    # complete; this case specifically verifies the missing-fundamental path.
    monkeypatch.setattr(market_db, "get_fund_flow_history", lambda *_args: [])
    monkeypatch.setattr(
        market_db,
        "get_financial_history",
        lambda *_args: {
            name: []
            for name in ("income", "balancesheet", "cashflow", "fina_indicator")
        },
    )
    decision = {
        "date": "2026-09-04",
        "stock_code": "000002.SZ",
        "stock_name": "risk round trip",
        "ranking_score": 88.0,
        "ai_score": 88.0,
        "technical_score": 78.0,
        "strategy_confirmations": 3,
        "buy_signals": 3,
        "direction": "neutral",
        "final_direction": "neutral",
        "pre_gate_direction": "buy",
        "gate_reasons": ["fund_flow_missing"],
        "non_flow_gates_passed": True,
        "flow_status": "missing",
        "market_flow": {},
        "evidence": "{}",
    }
    discovery = {"000002.SZ": {"stock_code": "000002.SZ", "sources": []}}

    async def fetch(_codes):
        return {
            "000002.SZ": {
                "quote": {"price": 10.0, "source": "tushare", "data_date": "2026-09-04"},
                "evidence": {
                    "fund_flow": {
                        "status": "positive",
                        "source": "tushare.moneyflow",
                        "main_net": 100.0,
                    }
                },
            }
        }

    await enrich_candidate_evidence(
        [decision], discovery, quote_fetcher=fetch, max_candidates=1
    )
    refresh_execution_gate(decision)
    apply_score_guard(decision, discovery["000002.SZ"])

    assert decision["flow_state"] == "positive"
    assert decision["direction"] == "neutral"
    assert "fundamental_evidence_missing" in decision["score_guard_reasons"]
    assert evaluate_entry_execution(decision)["tier"] == "blocked"


@pytest.mark.asyncio
async def test_failed_quote_provenance_survives_sqlite_reopen(tmp_path):
    database_path = tmp_path / "failed-quote-round-trip.db"
    database = MarketDatabase(database_path)
    decision = {
        "date": "2026-09-05",
        "stock_code": "300792.SZ",
        "stock_name": "failed quote round trip",
        "ranking_score": 88.0,
        "ai_score": 88.0,
        "technical_score": 86.0,
        "discovery_score": 84.0,
        "direction": "neutral",
        "recommendation": "Hold",
        "evidence": "{}",
    }
    discovery = {"300792.SZ": {"stock_code": "300792.SZ", "sources": []}}

    async def failed_fetch(_codes):
        return {
            "300792.SZ": {
                "error": "quote_missing",
                "provenance": {
                    "quote": {
                        "provider": "none",
                        "available": False,
                        "error": (
                            "tushare_primary:TimeoutError;"
                            "tushare_retry:skipped_inflight;"
                            "fallback:unavailable"
                        ),
                    }
                },
            }
        }

    await enrich_candidate_evidence(
        [decision], discovery, quote_fetcher=failed_fetch, max_candidates=1
    )
    journal_id = database.save_decision(decision)
    database.save_strategy_decision(decision, journal_id)
    del database

    reopened = MarketDatabase(database_path)
    loaded = reopened.get_decisions_for_date("2026-09-05", limit=10)[0]
    saved_evidence = json.loads(loaded["evidence"])
    saved_provenance = (
        saved_evidence["market_discovery"]
        ["evidence_enrichment"]["provenance"]["quote"]
    )

    assert loaded["stock_code"] == "300792.SZ"
    assert loaded["market_price"] is None
    assert saved_provenance["available"] is False
    assert "tushare_retry:skipped_inflight" in saved_provenance["error"]


@pytest.mark.asyncio
async def test_quote_failure_keeps_components_after_sqlite_reopen(tmp_path):
    database_path = tmp_path / "failed-quote-components-round-trip.db"
    database = MarketDatabase(database_path)
    code = "999996.SZ"
    decision = {
        "date": "2026-09-05",
        "stock_code": code,
        "stock_name": "failed quote components",
        "ranking_score": 88.0,
        "ai_score": 88.0,
        "technical_score": 86.0,
        "discovery_score": 84.0,
        "direction": "neutral",
        "recommendation": "Hold",
        "flow_status": "missing",
        "market_flow": {},
        "evidence": "{}",
    }
    discovery = {code: {"stock_code": code, "sources": []}}

    async def failed_fetch(_codes):
        return {
            code: {
                "error": "quote_missing",
                "provenance": {"provider": "tushare"},
                "evidence": {
                    "fundamental": {
                        "available": True,
                        "source": "tushare",
                        "period_counts": {"income": 8},
                    },
                    "fund_flow": {
                        "status": "positive",
                        "source": "tushare.moneyflow",
                        "main_net": 100.0,
                        "data_date": "2026-09-04",
                    },
                },
            }
        }

    await enrich_candidate_evidence(
        [decision], discovery, quote_fetcher=failed_fetch, max_candidates=1
    )
    journal_id = database.save_decision(decision)
    database.save_strategy_decision(decision, journal_id)
    del database

    reopened = MarketDatabase(database_path)
    loaded = reopened.get_decisions_for_date("2026-09-05", limit=10)[0]
    persisted = reopened.get_strategy_context(code, limit=1)[0]["analysis"]
    persisted_evidence = json.loads(loaded["evidence"])

    assert loaded["market_price"] is None
    assert loaded["flow_state"] == "positive"
    assert loaded["fundamental_evidence_available"] is True
    assert persisted["market_flow"]["status"] == "positive"
    assert persisted_evidence["market_discovery"]["fundamental"]["available"] is True
