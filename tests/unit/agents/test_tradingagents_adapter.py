from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.agents import tradingagents_adapter as adapter


def test_daily_profile_defaults_to_three_analysts_and_zero_debate(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_ANALYSTS", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_DEBATE_ROUNDS", raising=False)

    assert adapter._selected_analysts() == ["market", "news", "fundamentals"]
    assert adapter._bounded_env_int("TRADINGAGENTS_DEBATE_ROUNDS", 0, 0, 3) == 0


def test_daily_profile_filters_invalid_overrides(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_ANALYSTS", "market,bogus,policy")
    monkeypatch.setenv("TRADINGAGENTS_RISK_ROUNDS", "99")

    assert adapter._selected_analysts() == ["market", "policy"]
    assert adapter._bounded_env_int("TRADINGAGENTS_RISK_ROUNDS", 0, 0, 3) == 3


def test_isolated_worker_is_preferred_over_adaptive_process(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_EXECUTION_MODE", raising=False)
    monkeypatch.setattr(adapter, "_in_process_available", lambda: True)
    monkeypatch.setattr(adapter, "_worker_python", lambda: Path("worker-python"))

    assert adapter._use_in_process() is False


@pytest.mark.asyncio
async def test_unavailable_runtime_returns_one_diagnostic_per_candidate(monkeypatch):
    monkeypatch.setattr(adapter, "availability_status", lambda: {
        "available": False,
        "runtime": "unavailable",
        "reasons": ["deepseek_key_missing"],
    })

    results = await adapter.analyze_candidates(
        [{"stock_code": "600000.SH"}, {"stock_code": "000001.SZ"}],
        "2026-08-14",
        limit=2,
    )

    assert len(results) == 2
    assert all(item["error_type"] == "RuntimeUnavailable" for item in results)
    assert "deepseek_key_missing" in results[0]["error"]


@pytest.mark.asyncio
async def test_candidate_analysis_has_bounded_concurrency_and_stable_order(monkeypatch):
    monkeypatch.setattr(adapter, "availability_status", lambda: {
        "available": True,
        "runtime": "codex_cli",
        "reasons": [],
    })
    codex = AsyncMock(side_effect=lambda candidates, trade_date, past_context, limit: [
        {"available": True, "stock_code": item["stock_code"]}
        for item in candidates[:limit]
    ])
    monkeypatch.setattr("src.agents.codex_stock_analyzer.analyze_candidates", codex)
    results = await adapter.analyze_candidates(
        [{"stock_code": code} for code in ["A", "B", "C"]],
        "2026-08-14",
        past_context="历史复盘",
        limit=3,
    )

    assert [item["stock_code"] for item in results] == ["A", "B", "C"]
    codex.assert_awaited_once_with(
        [{"stock_code": "A"}, {"stock_code": "B"}, {"stock_code": "C"}],
        "2026-08-14",
        "历史复盘",
        limit=3,
    )


def test_displayed_plan_declares_twenty_percent_execution_guardrail():
    plan = adapter._guarded_plan("建议五成仓位")

    assert plan.startswith("**Execution Guardrail**")
    assert "硬上限为账户总资产20%" in plan


@pytest.mark.asyncio
async def test_analyze_candidates_uses_codex_native_path(monkeypatch):
    monkeypatch.setattr(adapter, "availability_status", lambda: {
        "available": True,
        "runtime": "codex_cli",
        "reasons": [],
    })
    codex = AsyncMock(return_value=[{
        "available": True,
        "stock_code": "600000.SH",
        "rating": "Buy",
        "direction": "buy",
        "score": 85.0,
    }])
    monkeypatch.setattr("src.agents.codex_stock_analyzer.analyze_candidates", codex)

    results = await adapter.analyze_candidates(
        [{"stock_code": "600000.SH"}], "2026-08-14", limit=1
    )

    assert results[0]["available"] is True
    assert results[0]["stock_code"] == "600000.SH"
    codex.assert_awaited_once()


@pytest.mark.asyncio
async def test_codex_failure_is_returned_per_stock(monkeypatch):
    monkeypatch.setattr(adapter, "availability_status", lambda: {
        "available": True,
        "runtime": "codex_cli",
        "reasons": [],
    })
    monkeypatch.setattr(
        "src.agents.codex_stock_analyzer.analyze_candidates",
        AsyncMock(return_value=[{
            "available": False,
            "stock_code": "600000.SH",
            "error": "Codex unavailable",
            "error_type": "RuntimeError",
        }]),
    )

    results = await adapter.analyze_candidates(
        [{"stock_code": "600000.SH"}], "2026-08-14", limit=1
    )

    assert results[0]["available"] is False
    assert "Codex unavailable" in results[0]["error"]
