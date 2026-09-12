"""System routes — 健康检查 / 状态"""

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter

from config.settings import settings
from src.infrastructure.market_data.hithink_provider import hithink_provider
from src.infrastructure.market_data.provider_metrics import reliability_engine
from src.infrastructure.market_data.provider_resilience import (
    get_provider_resilience_status,
)

router = APIRouter(tags=["system"])
_RELEASE = json.loads(
    (Path(__file__).resolve().parents[3] / "config/release.json").read_text("utf-8")
)
PRODUCT_VERSION = _RELEASE["product_version"]


@router.get("/system/health")
async def health_check():
    return {"status": "ok", "version": _RELEASE["product_version"], **_RELEASE}


@router.get("/system/runtime")
async def runtime_identity():
    """Expose the startup-frozen runtime identity and disk drift separately."""
    from src.infrastructure.runtime_identity import startup_identity

    # Hashing the critical runtime files is synchronous disk I/O.  Keep this
    # diagnostic endpoint from blocking the API event loop under disk/AV load.
    return await asyncio.to_thread(startup_identity)


@router.get("/system/status")
async def system_status():
    from src.infrastructure.ai import ai_router

    return {
        "app": "Adaptive Investment Intelligence Platform",
        "version": _RELEASE["product_version"],
        "ai": ai_router.status(),
        "modules": [
            "plugin_registry",
            "market_gateway",
            "repository",
            "knowledge_base",
            "signal_engine",
            "scanner",
            "research_pipeline",
            "ai_agents",
            "backtest",
        ],
    }


@router.get("/system/providers/hithink")
async def hithink_provider_health():
    """Expose redacted HiThink capability health for canary operations."""
    stats = hithink_provider.runtime_stats()
    metrics = reliability_engine.get_metrics_summary("hithink")
    resilience = get_provider_resilience_status("hithink")
    calls = int(stats.get("calls") or 0)
    successes = int(stats.get("successes") or 0)
    if not hithink_provider.configured:
        status = "not_configured"
    elif resilience["state"] == "open" or metrics.get("status") == "degraded":
        status = "degraded"
    elif calls:
        status = "healthy"
    else:
        status = "unknown"
    return {
        "provider": "hithink",
        "status": status,
        "configured": hithink_provider.configured,
        "rollout": {
            "symbol_search": settings.HITHINK_SYMBOL_MODE,
            "valuation": settings.HITHINK_VALUATION_MODE,
            "special_data": settings.HITHINK_SPECIAL_MODE,
            "daily_kline": settings.HITHINK_DAILY_MODE,
            "financials": settings.HITHINK_FINANCIAL_MODE,
            "realtime_quote": settings.HITHINK_REALTIME_MODE,
        },
        "health": {
            "calls": calls,
            "successes": successes,
            "failures": int(stats.get("failures") or 0),
            "success_rate": round(successes / calls, 4) if calls else None,
            "avg_latency_ms": stats.get("avg_latency_ms", 0.0),
            "p95_latency_ms": stats.get("p95_latency_ms", 0.0),
            "last_success_at": metrics.get("last_success_at", ""),
            "recent_errors": list(stats.get("recent_errors") or [])[-20:],
        },
        "by_capability": stats.get("by_capability", {}),
        "circuit": resilience,
    }
