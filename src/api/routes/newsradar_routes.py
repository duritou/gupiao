"""News Radar routes - 新闻雷达（实时新闻聚合）。"""

import asyncio
from datetime import datetime

from fastapi import APIRouter

from src.infrastructure.market_data.eastmoney_news import fetch_eastmoney_global_news
from src.infrastructure.market_data.vibe_provider import get_vibe_provider

router = APIRouter(tags=["newsradar"], prefix="/newsradar")

_MAX_NEWS_AGE_HOURS = 72
_refresh_task: asyncio.Task | None = None


def _apply_freshness(data: dict) -> dict:
    updated_at = str(data.get("updated_at") or "").strip()
    metadata = dict(data.get("_meta") or {})
    age_hours = None
    if updated_at:
        try:
            parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            now = datetime.now(parsed.tzinfo) if parsed.tzinfo else datetime.now()
            age_hours = max(0.0, (now - parsed).total_seconds() / 3600)
        except ValueError:
            age_hours = None
    has_content = bool(data.get("news"))
    stale = age_hours is None or age_hours > _MAX_NEWS_AGE_HOURS
    if stale or not has_content:
        metadata.update({
            "available": False,
            "stale": stale,
            "age_hours": round(age_hours, 1) if age_hours is not None else None,
            "error": (
                f"新闻缓存已超过 {_MAX_NEWS_AGE_HOURS} 小时，请刷新后再使用"
                if stale and age_hours is not None else
                "新闻数据缺少有效更新时间，请刷新后再使用"
                if stale else "资讯源没有返回有效内容"
            ),
        })
    else:
        metadata.update({"stale": False, "age_hours": round(age_hours, 1)})
    return {**data, "_meta": metadata}


def _schedule_refresh(vibe) -> bool:
    """Start one non-blocking refresh when a client observes stale data."""
    global _refresh_task
    if _refresh_task is not None and not _refresh_task.done():
        return False
    _refresh_task = asyncio.create_task(vibe.refresh_news_radar())
    return True


@router.get("/latest")
async def get_news_radar():
    """获取最新新闻雷达数据。"""
    vibe = get_vibe_provider()
    data = _apply_freshness(await fetch_eastmoney_global_news())
    if not (data.get("_meta") or {}).get("available"):
        data = _apply_freshness(await vibe.get_news_radar())
    if not (data.get("_meta") or {}).get("available"):
        metadata = dict(data.get("_meta") or {})
        metadata["refresh_scheduled"] = _schedule_refresh(vibe)
        data["_meta"] = metadata
    return {
        "news": data.get("news", []),
        "total_count": data.get("total_count", len(data.get("news", []))),
        "updated_at": data.get("updated_at", ""),
        "_meta": data.get("_meta", {}),
    }


@router.post("/refresh")
async def refresh_news_radar():
    """刷新新闻雷达数据（强制重新抓取）。"""
    vibe = get_vibe_provider()
    data = _apply_freshness(await fetch_eastmoney_global_news())
    if not (data.get("_meta") or {}).get("available"):
        data = _apply_freshness(await vibe.refresh_news_radar())
    return {
        "news": data.get("news", []),
        "total_count": data.get("total_count", len(data.get("news", []))),
        "updated_at": data.get("updated_at", ""),
        "_meta": data.get("_meta", {}),
    }
