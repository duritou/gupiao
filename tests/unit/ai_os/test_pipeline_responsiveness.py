import asyncio
import threading
import time

import pytest

import src.ai_os.pipeline_runner as pipeline_module
from config.settings import settings
from src.agents import codex_stock_analyzer
from src.infrastructure.ai import ai_router
from src.infrastructure.market_data.real_data_provider import (
    RealSignalResult,
    real_data,
)
from src.infrastructure.storage.market_database import market_db


@pytest.mark.asyncio
async def test_full_market_scan_keeps_event_loop_responsive(monkeypatch):
    universe = [
        {"code": f"60{index:04d}.SH", "name": f"stock-{index}"}
        for index in range(80)
    ]
    bars = [
        {
            "date": "2026-08-24",
            "open": 10.0,
            "high": 10.5,
            "low": 9.5,
            "close": 10.0,
            "volume": 1000.0,
            "amount": 10000.0,
        }
        for _ in range(25)
    ]
    main_thread = threading.get_ident()
    worker_threads: set[int] = set()

    async def get_universe(min_count):
        return universe

    def get_bars(code, limit):
        worker_threads.add(threading.get_ident())
        time.sleep(0.003)
        return bars

    def compute_signals(code, name, source_bars):
        worker_threads.add(threading.get_ident())
        time.sleep(0.002)
        return RealSignalResult(
            stock_code=code,
            stock_name=name,
            fusion_score=60.0,
            macd_score=60.0,
            rsi_score=60.0,
            kdj_score=60.0,
            ma_score=60.0,
            volume_score=60.0,
            data_days=len(source_bars),
            data_source="test-local",
        )

    async def no_deep_analysis(candidates, trade_date, past_context, limit):
        return []

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
            "trading_calendar_source": "test",
            "pre_trade_portfolio_mark": {},
            "portfolio_mark": {},
        }

    monkeypatch.setattr(settings, "REMOTE_MARKET_DISCOVERY_ENABLED", False)
    monkeypatch.setattr(settings, "SCANNER_AI_DEEP_ANALYSIS_N", 0)
    monkeypatch.setattr(real_data, "get_stock_universe", get_universe)
    monkeypatch.setattr(market_db, "get_daily_bars", get_bars)
    monkeypatch.setattr(real_data, "compute_signals", compute_signals)
    monkeypatch.setattr(market_db, "get_paper_portfolio", lambda: {"positions": []})
    monkeypatch.setattr(market_db, "get_market_learning_profile", lambda **kwargs: {})
    monkeypatch.setattr(market_db, "upsert_daily_learning", lambda *args, **kwargs: None)
    monkeypatch.setattr(market_db, "get_learning_log", lambda limit: [])
    monkeypatch.setattr(market_db, "get_cached_deep_analyses", lambda *args, **kwargs: {})
    monkeypatch.setattr(market_db, "count_cached_deep_analyses", lambda *args, **kwargs: 0)
    monkeypatch.setattr(market_db, "count_daily_deep_attempts", lambda *args, **kwargs: 0)
    monkeypatch.setattr(ai_router, "status", lambda: {"primary_configured": False})
    monkeypatch.setattr(codex_stock_analyzer, "analyze_candidates", no_deep_analysis)
    monkeypatch.setattr(
        codex_stock_analyzer,
        "availability_status",
        lambda: {"available": False, "runtime": "test"},
    )
    monkeypatch.setattr(pipeline_module, "_execute_paper_cycle", no_paper_cycle)

    heartbeat_ticks = 0
    running = True

    async def heartbeat():
        nonlocal heartbeat_ticks
        while running:
            heartbeat_ticks += 1
            await asyncio.sleep(0.01)

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        result = await pipeline_module.AIPipelineRunner().run_daily_pipeline(
            save_to_journal=False,
            execute_paper_trades=False,
        )
    finally:
        running = False
        await heartbeat_task

    assert result.stocks_scanned == len(universe)
    assert result.signals_computed == len(universe)
    assert heartbeat_ticks >= 10
    assert worker_threads
    assert main_thread not in worker_threads


@pytest.mark.asyncio
async def test_saved_audit_carries_the_candidate_enrichment_summary(monkeypatch):
    """The run must record how much candidate evidence it actually fetched.

    The summary was computed into market_data_quality on every run and then
    dropped when the audit payload was assembled, so no endpoint could report
    it and a run that fetched nothing looked identical to one that fetched
    everything.
    """
    universe = [{"code": "600000.SH", "name": "stock-0"}]
    bars = [
        {
            "date": "2026-08-24",
            "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0,
            "volume": 1000.0, "amount": 10000.0,
        }
        for _ in range(25)
    ]

    async def get_universe(min_count):
        return universe

    def get_bars(code, limit):
        return bars

    def compute_signals(code, name, source_bars):
        return RealSignalResult(
            stock_code=code, stock_name=name, fusion_score=60.0,
            macd_score=60.0, rsi_score=60.0, kdj_score=60.0,
            ma_score=60.0, volume_score=60.0,
            data_days=len(source_bars), data_source="test-local",
        )

    async def no_deep_analysis(candidates, trade_date, past_context, limit):
        return []

    async def no_paper_cycle(decisions, *, execute_paper_trades):
        return {
            "paper_result": {
                "actions": [], "cash": 100000.0, "position_count": 0,
                "execution_status": "deferred", "execution_at": "",
                "rejections": [],
            },
            "execution_quotes": {}, "execution_decisions": [],
            "causal_rejections": [], "trading_calendar_verified": True,
            "trading_calendar_source": "test", "pre_trade_portfolio_mark": {},
            "portfolio_mark": {},
        }

    captured: dict = {}

    def capture_audit(payload):
        captured.update(payload)

    monkeypatch.setattr(settings, "REMOTE_MARKET_DISCOVERY_ENABLED", False)
    monkeypatch.setattr(settings, "SCANNER_AI_DEEP_ANALYSIS_N", 0)
    monkeypatch.setattr(real_data, "get_stock_universe", get_universe)
    monkeypatch.setattr(market_db, "get_daily_bars", get_bars)
    monkeypatch.setattr(real_data, "compute_signals", compute_signals)
    monkeypatch.setattr(market_db, "get_paper_portfolio", lambda: {"positions": []})
    monkeypatch.setattr(market_db, "get_market_learning_profile", lambda **kw: {})
    monkeypatch.setattr(market_db, "upsert_daily_learning", lambda *a, **k: None)
    monkeypatch.setattr(market_db, "get_learning_log", lambda limit: [])
    monkeypatch.setattr(market_db, "get_cached_deep_analyses", lambda *a, **k: {})
    monkeypatch.setattr(market_db, "count_cached_deep_analyses", lambda *a, **k: 0)
    monkeypatch.setattr(market_db, "count_daily_deep_attempts", lambda *a, **k: 0)
    monkeypatch.setattr(market_db, "save_pipeline_run_audit", capture_audit)
    monkeypatch.setattr(market_db, "save_decisions_batch", lambda decisions: [1] * len(decisions))
    monkeypatch.setattr(market_db, "save_strategy_decisions_batch", lambda decisions: len(decisions))
    monkeypatch.setattr(ai_router, "status", lambda: {"primary_configured": False})
    monkeypatch.setattr(codex_stock_analyzer, "analyze_candidates", no_deep_analysis)
    monkeypatch.setattr(
        codex_stock_analyzer, "availability_status",
        lambda: {"available": False, "runtime": "test"},
    )
    monkeypatch.setattr(pipeline_module, "_execute_paper_cycle", no_paper_cycle)

    await pipeline_module.AIPipelineRunner().run_daily_pipeline(
        save_to_journal=True,
        execute_paper_trades=False,
    )

    assert captured, "audit payload was never saved"
    assert "candidate_evidence_enrichment" in captured
