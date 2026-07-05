"""System routes — 健康检查 / 状态"""

from fastapi import APIRouter

router = APIRouter(tags=["system"])


@router.get("/system/health")
async def health_check():
    return {"status": "ok", "version": "6.0.0"}


@router.get("/system/status")
async def system_status():
    return {
        "app": "Adaptive Investment Intelligence Platform",
        "version": "6.0.0",
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
