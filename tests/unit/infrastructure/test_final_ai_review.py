from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.ai_os.pipeline_runner import _apply_final_ai_review


def _decision(rating="Buy", direction="buy", score=85.0):
    return {
        "stock_code": "000001.SZ",
        "stock_name": "测试股票",
        "ai_score": score,
        "technical_score": 70.0,
        "direction": direction,
        "recommendation": rating,
        "deep_analysis_available": True,
        "deep_rating": rating,
        "deep_analysis": "TradingAgents evidence",
        "market_sources": ["test"],
        "market_reasons": ["reason"],
    }


@pytest.mark.asyncio
async def test_final_review_approves_existing_buy():
    decision = _decision()
    router = SimpleNamespace(generate=AsyncMock(return_value=SimpleNamespace(
        text='[{"code":"000001.SZ","verdict":"approve","reason":"证据一致"}]',
        provider="codex_cli",
        model="gpt-5.6-terra",
        fallback_used=False,
    )))

    status = await _apply_final_ai_review(
        [decision], router, [], "codex_cli"
    )

    assert status["matched"] == 1
    assert decision["direction"] == "buy"
    assert decision["final_buy_approved"] is True
    assert decision["final_review_provider"] == "codex_cli"


@pytest.mark.asyncio
async def test_final_review_veto_downgrades_buy_to_hold():
    decision = _decision()
    router = SimpleNamespace(generate=AsyncMock(return_value=SimpleNamespace(
        text='[{"code":"000001.SZ","verdict":"veto","reason":"追高风险"}]',
        provider="codex_cli",
        model="gpt-5.6-terra",
        fallback_used=False,
    )))

    await _apply_final_ai_review([decision], router, [], "codex_cli")

    assert decision["tradingagents_rating"] == "Buy"
    assert decision["final_buy_approved"] is False
    assert decision["direction"] == "neutral"
    assert decision["recommendation"] == "Hold"
    assert decision["ai_score"] == 50.0
    assert decision["decision_status"] == "review_blocked"


@pytest.mark.asyncio
async def test_final_review_never_upgrades_hold_to_buy():
    decision = _decision(rating="Hold", direction="neutral", score=50.0)
    router = SimpleNamespace(generate=AsyncMock(return_value=SimpleNamespace(
        text='[{"code":"000001.SZ","verdict":"approve","reason":"可观察"}]',
        provider="codex_cli",
        model="gpt-5.6-terra",
        fallback_used=False,
    )))

    await _apply_final_ai_review([decision], router, [], "codex_cli")

    assert decision["direction"] == "neutral"
    assert decision["recommendation"] == "Hold"


@pytest.mark.asyncio
async def test_final_review_failure_blocks_completed_deep_buy():
    decision = _decision()
    router = SimpleNamespace(generate=AsyncMock(side_effect=RuntimeError("both down")))

    status = await _apply_final_ai_review(
        [decision], router, [], "codex_cli"
    )

    assert status["called"] is False
    assert "both down" in status["error"]
    assert decision["final_review_available"] is False
    assert decision["final_buy_approved"] is False
    assert decision["direction"] == "neutral"
    assert decision["decision_status"] == "review_blocked"
