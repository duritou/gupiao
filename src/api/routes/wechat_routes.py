"""Optional WeChat public-account article archive routes."""

import asyncio
from typing import Any

from fastapi import APIRouter, Query

from config.settings import settings
from src.knowledge.wechat_rss import (
    get_wechat_methodology,
    get_wechat_review_section,
    get_sync_state,
    learn_wechat_methodology,
    list_stored_articles,
    sync_wechat_articles,
)

router = APIRouter(tags=["wechat-knowledge"], prefix="/knowledge/wechat")


@router.get("/status")
async def wechat_status() -> dict[str, Any]:
    """Show local archive health without exposing feed credentials."""

    state = get_sync_state()
    articles = list_stored_articles(limit=200)
    return {
        "enabled": bool(settings.WECHAT_RSS_ENABLED),
        "configured": bool(settings.WECHAT_RSS_URL),
        "article_count": len(articles),
        "latest_published_at": articles[0].published_at if articles else "",
        "last_sync": state,
        "data_source": "configured_rss_bridge + local_yaml_archive",
    }


@router.get("/articles")
async def wechat_articles(
    limit: int = Query(20, ge=1, le=200),
    as_of: str = Query("", description="只返回发布时间不晚于 YYYY-MM-DD 的文章"),
    include_content: bool = Query(False, description="是否返回原始 HTML 正文"),
) -> dict[str, Any]:
    """List archived articles; ``as_of`` is used by point-in-time replay."""

    normalized_as_of = str(as_of or "").strip()
    if normalized_as_of:
        try:
            from datetime import date

            normalized_as_of = date.fromisoformat(normalized_as_of).isoformat()
        except ValueError:
            return {"error": "as_of must be YYYY-MM-DD", "articles": []}
    articles = list_stored_articles(limit=limit, as_of=normalized_as_of)
    return {
        "articles": [
            article.to_dict(include_content=include_content) for article in articles
        ],
        "count": len(articles),
        "as_of": normalized_as_of,
        "data_source": "local_yaml_archive",
    }


@router.post("/sync")
async def sync_wechat() -> dict[str, Any]:
    """Manually trigger one bounded RSS sync using the configured feed URL."""

    return await asyncio.to_thread(sync_wechat_articles)


@router.get("/review")
async def wechat_review_section(
    limit: int = Query(200, ge=1, le=200),
) -> dict[str, Any]:
    """Dedicated latest/history view model for the public-account review page."""

    return await asyncio.to_thread(get_wechat_review_section, limit=limit)


@router.get("/methodology")
async def wechat_methodology() -> dict[str, Any]:
    """Return the isolated AI methodology snapshot, if one exists."""

    return await asyncio.to_thread(get_wechat_methodology)


@router.post("/learn")
async def learn_wechat(force: bool = Query(False)) -> dict[str, Any]:
    """Run one bounded methodology-learning pass without touching production learning."""

    return await learn_wechat_methodology(force=force)


@router.post("/refresh")
async def refresh_wechat() -> dict[str, Any]:
    """Sync the feed, then update the isolated methodology snapshot."""

    sync = await asyncio.to_thread(sync_wechat_articles)
    learning = await learn_wechat_methodology()
    return {"sync": sync, "learning": learning}
