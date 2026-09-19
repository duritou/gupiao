from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from config.settings import settings
from src.ai_os.task_executor import TaskExecutor
from src.infrastructure.ai import ai_router
from src.infrastructure.storage.market_database import market_db


@pytest.mark.asyncio
async def test_ai_reflection_uses_codex_review_provider_and_persists_metadata(
    monkeypatch,
):
    saved = {}
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "sk-test-non-placeholder")
    monkeypatch.setattr(settings, "AI_REVIEW_PROVIDER", "codex_cli")
    monkeypatch.setattr(settings, "AI_FAST_MODEL", "gpt-5.6-luna")
    monkeypatch.setattr(
        market_db,
        "get_paper_portfolio",
        lambda: {
            "total_value": 100000.0,
            "total_pl": 0.0,
            "positions": [],
            "trades": [],
            "cash": 100000.0,
        },
    )
    monkeypatch.setattr(
        market_db, "get_decisions_for_date", lambda day, limit: []
    )
    monkeypatch.setattr(market_db, "get_learning_log", lambda limit: [])

    def save_learning(day, category, lesson, evidence):
        saved.update(
            day=day, category=category, lesson=lesson, evidence=evidence
        )

    monkeypatch.setattr(market_db, "save_learning", save_learning)
    generate = AsyncMock(return_value=SimpleNamespace(
        text="做对：保持空仓；明日调整：等待有效信号。",
        provider="codex_cli",
        model="gpt-5.6-terra",
        fallback_used=False,
        fallback_reason=None,
    ))
    monkeypatch.setattr(ai_router, "generate", generate)
    executor = TaskExecutor(persist=False)
    monkeypatch.setattr(executor, "_notify_wechat", AsyncMock(return_value=False))

    result = await executor._ai_reflection(None)

    assert result["status"] == "reflected"
    assert result["ai_provider"] == "codex_cli"
    assert result["ai_model"] == "gpt-5.6-terra"
    assert saved["category"] == "ai_reflection"
    assert saved["evidence"]["ai_status"] == "ok"
    assert saved["evidence"]["ai_provider"] == "codex_cli"
    assert saved["evidence"]["ai_model"] == "gpt-5.6-terra"
    assert generate.await_args.kwargs["primary_provider"] == "codex_cli"
    assert generate.await_args.kwargs["allow_fallback"] is False
    # Reflection is routine work, so it must ask for the fast model.  Without
    # this the test only ever asserted against its own mocked response, and
    # would pass no matter which model the caller requested.
    assert generate.await_args.kwargs["model"] == settings.AI_FAST_MODEL
    assert "20%" in generate.await_args.kwargs["prompt"]
    assert "Codex-Terra" in generate.await_args.kwargs["prompt"]


@pytest.mark.asyncio
async def test_ai_reflection_bounds_large_decision_evidence(monkeypatch):
    monkeypatch.setattr(settings, "AI_REVIEW_PROVIDER", "codex_cli")
    monkeypatch.setattr(settings, "AI_FAST_MODEL", "gpt-5.6-luna")
    monkeypatch.setattr(market_db, "get_paper_portfolio", lambda: {
        "total_value": 100000.0, "total_pl": 0.0, "positions": [],
    })
    oversized = [{
        "stock_code": f"600{index:03d}.SH",
        "stock_name": "测试",
        "ai_score": 80 - index,
        "decision_status": "hold",
        "deep_rating": "Hold",
        "evidence": "x" * 100_000,
        "analysis_json": "y" * 100_000,
    } for index in range(20)]
    monkeypatch.setattr(
        market_db, "get_decisions_for_date", lambda day, limit: oversized
    )
    monkeypatch.setattr(market_db, "get_learning_log", lambda limit: [])
    monkeypatch.setattr(market_db, "save_learning", lambda *args: None)
    generate = AsyncMock(return_value=SimpleNamespace(
        text="复盘完成", provider="codex_cli", model="gpt-5.6-terra",
        fallback_used=False, fallback_reason=None,
    ))
    monkeypatch.setattr(ai_router, "generate", generate)
    executor = TaskExecutor(persist=False)
    monkeypatch.setattr(executor, "_notify_wechat", AsyncMock(return_value=False))

    await executor._ai_reflection(None)

    prompt = generate.await_args.kwargs["prompt"]
    assert len(prompt) < 100_000
    assert "analysis_json" not in prompt
    assert "evidence" not in prompt
