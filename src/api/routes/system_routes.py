"""System routes — 健康检查 / 状态"""

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter

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
