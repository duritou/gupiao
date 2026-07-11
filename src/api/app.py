"""FastAPI Application — Adaptive Investment Intelligence Platform API"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, date as dt_date

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger("uvicorn.error")  # 复用 uvicorn 日志 handler,确保启动同步日志可见

from src.api.routes import (
    system_routes,
    knowledge_routes,
    signals_routes,
    scanner_routes,
    research_routes,
    backtest_routes,
    market_routes,
    compare_routes,
    timeline_routes,
    alerts_routes,
    dailybrief_routes,
    detail_routes,
    explain_routes,
    trust_routes,
    user_routes,
    ai_os_routes,
    replay_routes,
    knowledge_graph_routes,
    decision_routes,
)

# Portfolio routes — direct import
from src.api.routes import portfolio_routes as portfolio_mod
from src.api.routes import morning_brief_routes as morning_mod

@asynccontextmanager
async def lifespan(app):
    """启动时:若本地数据仓库落后,后台触发一次全 A 股增量同步(不阻塞 API)。"""
    try:
        from src.infrastructure.storage.market_database import market_db
        stats = market_db.get_stats()
        latest = stats.get("latest_data_date")
        stale = True
        if latest:
            try:
                stale = (dt_date.today() - dt_date.fromisoformat(latest)).days > 3
            except Exception:
                stale = True

        if stale:
            logger.info(
                "[sync] 本地数据落后(latest=%s),启动后台增量同步(全 A 股,约 30-60 分钟)...",
                latest,
            )
            from src.api.routes.market_routes import _run_sync, _sync_state
            _sync_state["running"] = True
            _sync_state["started_at"] = datetime.now().isoformat()
            _sync_state["progress"] = {"done": 0, "total": 0, "current": "startup"}
            _sync_state["result"] = None
            _sync_state["error"] = None
            asyncio.create_task(_run_sync(None, 30, True))
        else:
            logger.info("[sync] 本地数据新鲜(latest=%s),跳过启动同步。", latest)
    except Exception as e:
        logger.warning("[sync] 启动同步检查失败: %s", e)
    yield


app = FastAPI(
    title="Adaptive Investment Intelligence Platform",
    version="6.0.0",
    description="Adaptive Investment Intelligence Platform — REST API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(system_routes.router, prefix="/api/v1")
app.include_router(knowledge_routes.router, prefix="/api/v1")
app.include_router(signals_routes.router, prefix="/api/v1")
app.include_router(scanner_routes.router, prefix="/api/v1")
app.include_router(research_routes.router, prefix="/api/v1")
app.include_router(backtest_routes.router, prefix="/api/v1")
app.include_router(market_routes.router, prefix="/api/v1")
app.include_router(compare_routes.router, prefix="/api/v1")
app.include_router(timeline_routes.router, prefix="/api/v1")
app.include_router(alerts_routes.router, prefix="/api/v1")
app.include_router(dailybrief_routes.router, prefix="/api/v1")
app.include_router(detail_routes.router, prefix="/api/v1")
app.include_router(explain_routes.router, prefix="/api/v1")
app.include_router(trust_routes.router, prefix="/api/v1")
app.include_router(user_routes.router, prefix="/api/v1")
app.include_router(ai_os_routes.router, prefix="/api/v1")
app.include_router(replay_routes.router, prefix="/api/v1")
app.include_router(knowledge_graph_routes.router, prefix="/api/v1")
app.include_router(decision_routes.router, prefix="/api/v1")
app.include_router(portfolio_mod.router, prefix="/api/v1")
app.include_router(morning_mod.router, prefix="/api/v1")
