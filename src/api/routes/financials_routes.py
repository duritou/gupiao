"""财务数据路由 - 提供个股财务指标查询功能。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from config.settings import settings
from src.infrastructure.market_data.sina_financials import fetch_sina_financials
from src.infrastructure.market_data.source_manager import source_manager
from src.infrastructure.market_data.vibe_provider import get_vibe_provider

router = APIRouter(tags=["financials"])


@router.get("/financials")
async def get_financials(code: str = Query(..., description="股票代码")):
    """获取指定股票的财务数据。

    Args:
        code: 股票代码（如 "000001"）

    Returns:
        dict: 财务数据，包含营收、净利润、EPS、ROE等关键指标
    """
    try:
        history, history_provenance = await source_manager.get_financial_history(
            code.strip().upper(), periods=settings.DATA_COMPLETION_FINANCIAL_PERIODS
        )
        if history.get("available") and history.get("statements"):
            return {
                "data": history,
                "_meta": {
                    **history_provenance.to_dict(),
                    "provider": "tushare",
                    "source_layer": "adaptive_tushare_history",
                    "available": True,
                    "data_date": history.get("data_date") or "",
                    "endpoint": history.get("endpoint") or history_provenance.endpoint,
                    "is_realtime": False,
                    "warning": "Tushare 财务数据按公告/报告期提供，不是实时数据",
                    "requested_periods": history.get("requested_periods"),
                    "period_counts": history.get("period_counts") or {},
                    "history_complete": bool(history.get("history_complete")),
                },
            }
    except Exception:
        pass
    try:
        statements, provenance = await source_manager.get_financial_statements(
            code.strip().upper()
        )
        if statements.get("available"):
            return {
                "data": statements,
                "_meta": {
                    "provider": "tushare",
                    "source_layer": "adaptive_tushare",
                    "available": True,
                    "data_date": statements.get("data_date") or "",
                    "endpoint": statements.get("endpoint") or provenance.endpoint,
                    "is_realtime": False,
                    "warning": "Tushare 财务数据按公告/报告期提供，不是实时数据",
                },
            }
    except Exception:
        pass
    try:
        native = await fetch_sina_financials(code)
    except Exception as exc:  # Native transport/parser failures use the compatibility source.
        native = {
            "data": {},
            "_meta": {
                "provider": "sina",
                "source_layer": "adaptive_native",
                "available": False,
                "error": f"{type(exc).__name__}: {str(exc)[:160]}",
            },
        }
    if native.get("data"):
        return native

    # Keep the existing Vibe path as a transparent fallback when Sina is
    # unavailable or returns no usable report rows.
    vibe = get_vibe_provider()
    return await vibe.get_financials(code)
