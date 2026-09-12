"""公告中心路由 - 提供公司公告查询功能。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from src.infrastructure.market_data.cninfo_announcements import (
    fetch_cninfo_announcements,
)
from src.infrastructure.market_data.vibe_provider import get_vibe_provider

router = APIRouter(tags=["announcements"])


@router.get("/announcements")
async def get_announcements(code: str = Query(..., description="股票代码")):
    """获取指定股票的公告列表。

    Args:
        code: 股票代码（如 "000001"）

    Returns:
        dict: 公告数据，包含 announcements 和 count 字段
    """
    try:
        native = await fetch_cninfo_announcements(code)
    except Exception as exc:  # Native transport/parser failures use the compatibility source.
        native = {
            "announcements": [],
            "count": 0,
            "_meta": {
                "provider": "cninfo",
                "source_layer": "adaptive_native",
                "available": False,
                "error": f"{type(exc).__name__}: {str(exc)[:160]}",
            },
        }
    if native.get("announcements"):
        return native

    # Keep Vibe as a transparent fallback for sources without a usable
    # CNINFO response.
    vibe = get_vibe_provider()
    return await vibe.get_announcements(code)


@router.get("/announcements/latest")
async def get_latest_announcements(limit: int = Query(50, description="返回公告数量")):
    """获取最新公告列表（全市场）。

    Args:
        limit: 返回公告数量，默认50

    Returns:
        dict: 公告数据，包含 announcements 和 updated_at 字段
    """
    vibe = get_vibe_provider()
    data = await vibe.get_latest_announcements(limit)
    return data
