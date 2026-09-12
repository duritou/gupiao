from datetime import date

import pytest

from src.api.routes.scanner_routes import latest_scanner_result
from src.infrastructure.storage.market_database import market_db


def _decision(code: str, score: float, *, blocked: bool = False) -> dict:
    return {
        "decision_date": date.today().isoformat(),
        "stock_code": code,
        "stock_name": code,
        "ai_score": score,
        "ranking_score": score,
        "action_score": score if not blocked else 60.0,
        "technical_score": score,
        "discovery_score": score,
        "direction": "neutral",
        "decision_status": "data_blocked" if blocked else "hold",
        "deep_analysis_available": True,
        "execution_evidence_complete": not blocked,
        "score_guard_reasons": ["market_data_degraded"] if blocked else [],
        "publication_blocked": blocked,
        "recommendation_tier": "data_blocked" if blocked else "research_complete",
        "confidence": 0.7,
        "macd_score": score,
        "rsi_score": score,
        "kdj_score": score,
        "ma_score": score,
        "volume_score": score,
        "recommendation": "观望",
    }


@pytest.mark.asyncio
async def test_latest_scanner_returns_only_publishable_deep_results(monkeypatch):
    requested_limits = []

    def get_recent_decision_summaries(*, limit):
        requested_limits.append(limit)
        return [
            _decision("000001.SZ", 95.0, blocked=True),
            _decision("000003.SZ", 72.0),
            _decision("000002.SZ", 85.0),
        ]

    monkeypatch.setattr(
        market_db,
        "get_recent_decision_summaries",
        get_recent_decision_summaries,
    )

    result = await latest_scanner_result(top_n=10)

    assert result["status"] == "ok"
    assert result["recommendation_available"] is True
    assert [item["stock_code"] for item in result["candidates"]] == [
        "000002.SZ",
        "000003.SZ",
    ]
    assert result["candidates"][0]["ranking_score"] == 85.0
    assert result["candidates"][0]["score_display"]["display_score"] == 85.0
    assert requested_limits == [5000]


@pytest.mark.asyncio
async def test_latest_scanner_reports_no_valid_recommendation(monkeypatch):
    monkeypatch.setattr(
        market_db,
        "get_recent_decision_summaries",
        lambda limit: [_decision("000001.SZ", 95.0, blocked=True)],
    )

    result = await latest_scanner_result(top_n=10)

    assert result["status"] == "no_valid_recommendation"
    assert result["recommendation_available"] is False
    assert result["candidates"] == []
    assert "没有可发布" in result["blocked_note"]
