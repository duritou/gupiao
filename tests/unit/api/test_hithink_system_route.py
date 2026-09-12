from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.api.routes import system_routes


@pytest.mark.asyncio
async def test_hithink_health_is_redacted_and_reports_rollout(monkeypatch):
    fake = SimpleNamespace(
        configured=True,
        runtime_stats=lambda: {
            "calls": 4,
            "successes": 3,
            "failures": 1,
            "avg_latency_ms": 120.0,
            "p95_latency_ms": 200.0,
            "by_capability": {"valuation": {"calls": 2, "p95_latency_ms": 200.0}},
            "recent_errors": [{"category": "server", "status_code": 503}],
        },
    )
    monkeypatch.setattr(system_routes, "hithink_provider", fake)
    monkeypatch.setattr(
        system_routes.reliability_engine,
        "get_metrics_summary",
        lambda provider: {"status": "active", "last_success_at": "2026-09-12T10:00:00+08:00"},
    )
    monkeypatch.setattr(
        system_routes,
        "get_provider_resilience_status",
        lambda provider: {
            "provider": "hithink",
            "state": "closed",
            "cooldown_remaining_seconds": 0.0,
            "consecutive_failures": 0,
            "cooldown_reason": "",
        },
    )

    result = await system_routes.hithink_provider_health()

    assert result["status"] == "healthy"
    assert result["health"]["success_rate"] == 0.75
    assert result["health"]["p95_latency_ms"] == 200.0
    assert result["rollout"]["realtime_quote"] == system_routes.settings.HITHINK_REALTIME_MODE
    assert "api_key" not in str(result).lower()


@pytest.mark.asyncio
async def test_hithink_health_marks_unconfigured_without_metrics(monkeypatch):
    fake = SimpleNamespace(configured=False, runtime_stats=lambda: {"calls": 0})
    monkeypatch.setattr(system_routes, "hithink_provider", fake)
    monkeypatch.setattr(
        system_routes,
        "get_provider_resilience_status",
        lambda provider: {"provider": "hithink", "state": "closed"},
    )

    result = await system_routes.hithink_provider_health()

    assert result["status"] == "not_configured"
    assert result["configured"] is False
    assert result["health"]["success_rate"] is None
