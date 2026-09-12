"""研报管理路由 - 提供研报查询、收藏和下载功能。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.infrastructure.market_data.eastmoney_reports import fetch_eastmoney_reports
from src.infrastructure.market_data.vibe_provider import get_vibe_provider

router = APIRouter(tags=["reports"])


class SaveReportRequest(BaseModel):
    """收藏研报请求体。"""
    rid: str
    code: str
    title: str


@router.get("/reports")
async def get_reports(code: str = Query(..., description="股票代码")):
    """获取指定股票的研报列表。

    Args:
        code: 股票代码（如 "000001"）

    Returns:
        dict: 研报数据，包含 reports 和 count 字段
    """
    try:
        native = await fetch_eastmoney_reports(code)
    except Exception as exc:  # Native transport/parser failures use the compatibility source.
        native = {
            "reports": [],
            "count": 0,
            "_meta": {
                "provider": "eastmoney",
                "source_layer": "adaptive_native",
                "available": False,
                "error": f"{type(exc).__name__}: {str(exc)[:160]}",
            },
        }
    if native.get("reports"):
        return native

    # Keep Vibe as a transparent fallback when Eastmoney has no usable rows.
    vibe = get_vibe_provider()
    return await vibe.get_reports(code)


@router.get("/myreports")
async def get_my_reports():
    """获取本地收藏的研报列表。

    Returns:
        dict: 收藏的研报数据，包含 reports 和 count 字段
    """
    vibe = get_vibe_provider()
    data = await vibe.get_my_reports()
    return data


@router.post("/myreports")
async def save_report(req: SaveReportRequest):
    """收藏一份研报到本地。

    Args:
        req: 包含研报ID、股票代码和标题的请求体

    Returns:
        dict: 操作结果
    """
    vibe = get_vibe_provider()
    result = await vibe.save_report(req.rid, req.code, req.title)

    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error", "收藏研报失败"))

    return result


@router.get("/myreports/file/{rid}")
async def get_report_file(rid: str):
    """获取研报PDF文件下载URL（重定向到Vibe Research后端）。

    Args:
        rid: 研报ID

    Returns:
        dict: 包含PDF文件URL的字典
    """
    vibe = get_vibe_provider()
    url = vibe.get_report_file_url(rid)
    return {"url": url}
