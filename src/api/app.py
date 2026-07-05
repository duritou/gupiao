"""FastAPI Application — Adaptive Investment Intelligence Platform API"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
)

# Portfolio routes — direct import
from src.api.routes import portfolio_routes as portfolio_mod
from src.api.routes import morning_brief_routes as morning_mod

app = FastAPI(
    title="Adaptive Investment Intelligence Platform",
    version="6.0.0",
    description="Adaptive Investment Intelligence Platform — REST API",
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
app.include_router(portfolio_mod.router, prefix="/api/v1")
app.include_router(morning_mod.router, prefix="/api/v1")
