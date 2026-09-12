import json
from types import SimpleNamespace

import pytest

import src.ai_os.pipeline_runner as pipeline_module
from config.settings import settings
from src.agents import codex_stock_analyzer
from src.infrastructure.ai import ai_router
import src.infrastructure.storage.market_database as market_database_module
from src.infrastructure.market_data.real_data_provider import RealSignalResult, real_data
from src.infrastructure.storage.market_database import MarketDatabase
from src.ai_os.universe_policy import UniverseAssessment


@pytest.mark.asyncio
async def test_morning_continues_after_first_batch_has_no_approval(
    tmp_path, monkeypatch
):
    database = MarketDatabase(tmp_path / "continuation.db")
    monkeypatch.setattr(market_database_module, "market_db", database)
    monkeypatch.setattr(settings, "SCANNER_AI_DEEP_ANALYSIS_N", 5)
    monkeypatch.setattr(settings, "SCANNER_AI_DEEP_ANALYSIS_MORNING_MAX", 10)
    monkeypatch.setattr(settings, "SCANNER_AI_DEEP_ANALYSIS_DAILY_MAX", 15)
    monkeypatch.setattr(settings, "REMOTE_MARKET_DISCOVERY_ENABLED", False)

    codes = [f"00000{index}.SZ" for index in range(1, 11)]
    bars = [
        {
            "date": f"2026-08-{index:02d}",
            "open": 10.0,
            "high": 10.5,
            "low": 9.5,
            "close": 10.0,
            "volume": 1000.0,
            "amount": 10000.0,
        }
        for index in range(1, 26)
    ]

    async def get_bars(code, days=250, prefer_remote=False):
        return bars

    def compute_signals(code, name, source_bars):
        return RealSignalResult(
            stock_code=code,
            stock_name=name,
            fusion_score=72.0,
            macd_score=72.0,
            rsi_score=72.0,
            kdj_score=72.0,
            ma_score=72.0,
            volume_score=72.0,
            data_days=len(source_bars),
            data_source="isolated-fixture",
        )

    async def enrich(decisions, discovery_by_code, **kwargs):
        for decision in decisions:
            decision.update({
                "market_sources": ["isolated-fixture"],
                "market_flow": {"status": "positive", "main_net": 100},
                "flow_status": "positive",
                "market_price": 10.0,
                "market_price_date": "2026-09-07",
                "market_price_source": "isolated-fixture",
                "market_price_fetched_at": "2026-09-07T09:35:00+08:00",
                "fundamental_evidence_available": True,
                "quote_enrichment_status": "confirmed",
                "market_evidence_complete": True,
            })
        return {
            "eligible_count": len(decisions),
            "quote_ready_count": len(decisions),
            "attempted_count": len(decisions),
            "quote_success_count": len(decisions),
            "quote_failure_count": 0,
            "not_scheduled_count": 0,
            "source_counts": {"isolated-fixture": len(decisions)},
            "errors": [],
        }

    async def no_preselection(*args, **kwargs):
        return 0, False, ""

    deep_calls = []

    async def analyze(candidates, trade_date, past_context, limit):
        deep_calls.append([item["stock_code"] for item in candidates])
        return [
            {
                "available": True,
                "stock_code": item["stock_code"],
                "rating": "Buy" if item["stock_code"] == "000001.SZ" else "Hold",
                "direction": "buy" if item["stock_code"] == "000001.SZ" else "neutral",
                "score": 82.0 if item["stock_code"] == "000001.SZ" else 60.0,
                "decision": "fixture decision",
                "thesis": "fixture thesis",
                "trader_plan": "fixture plan",
                "provider": "codex_cli",
                "model": "fixture-model",
                "source": "isolated-fixture",
                "runtime": "test",
                "duration_seconds": 0.1,
                "kline_evidence": {"last_date": "2026-09-07"},
                "deep_evidence_consumption": {"quote": {"data_date": "2026-09-07"}},
            }
            for item in candidates
        ]

    review_calls = []

    async def generate(**kwargs):
        review_calls.append(kwargs["prompt"])
        if len(review_calls) == 1:
            text = "[]"
        else:
            text = json.dumps([
                {"code": "000001.SZ", "verdict": "approve", "reason": "fixture", "risk": "fixture"}
            ])
        return SimpleNamespace(
            text=text,
            provider="codex_cli",
            model="fixture-review",
            fallback_used=False,
        )

    async def no_paper_cycle(decisions, *, execute_paper_trades):
        return {
            "paper_result": {
                "actions": [],
                "cash": 100000.0,
                "position_count": 0,
                "execution_status": "deferred",
                "execution_at": "",
                "rejections": [],
            },
            "execution_quotes": {},
            "execution_decisions": [],
            "causal_rejections": [],
            "trading_calendar_verified": True,
            "trading_calendar_source": "fixture",
            "pre_trade_portfolio_mark": {},
            "portfolio_mark": {},
        }

    monkeypatch.setattr(real_data, "get_daily_bars", get_bars)
    monkeypatch.setattr(real_data, "compute_signals", compute_signals)
    monkeypatch.setattr(
        pipeline_module,
        "assess_stock",
        lambda *args, **kwargs: UniverseAssessment(
            stock_code=args[0].get("code", ""),
            industry=f"fixture-{args[0].get('code', '')}",
        ),
    )
    monkeypatch.setattr(
        pipeline_module,
        "_apply_ai_preselection",
        no_preselection,
    )
    monkeypatch.setattr(
        "src.ai_os.candidate_evidence_enricher.enrich_candidate_evidence",
        enrich,
    )
    monkeypatch.setattr(codex_stock_analyzer, "analyze_candidates", analyze)
    monkeypatch.setattr(
        codex_stock_analyzer,
        "availability_status",
        lambda: {"available": True, "runtime": "test"},
    )
    monkeypatch.setattr(ai_router, "generate", generate)
    monkeypatch.setattr(ai_router, "status", lambda: {"primary_configured": False})
    monkeypatch.setattr(pipeline_module, "_execute_paper_cycle", no_paper_cycle)
    monkeypatch.setattr(database, "get_paper_portfolio", lambda: {
        "positions": [], "cash": 100000.0, "total_value": 100000.0,
    })
    monkeypatch.setattr(database, "get_latest_market_date_on_or_before", lambda _: "2026-09-07")
    monkeypatch.setattr(database, "get_learning_log", lambda limit: [])
    monkeypatch.setattr(database, "upsert_daily_learning", lambda *args, **kwargs: None)

    result = await pipeline_module.AIPipelineRunner().run_daily_pipeline(
        codes=codes,
        save_to_journal=False,
        execute_paper_trades=False,
        research_window="morning",
    )

    quality = result.market_data_quality
    assert [len(batch) for batch in deep_calls] == [5, 5]
    assert len(review_calls) == 2
    assert quality["deep_analysis_continuation_triggered"] is True
    assert quality["deep_analysis_continuation_count"] == 5
    assert quality["deep_analysis_target"] == 10
    assert result.deep_analysis_count == 10
    assert result.final_review_count == 1
    assert quality["deep_analysis_continuation_stop_reason"] == "continuation_completed"
