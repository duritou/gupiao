"""Freshness metadata for internal market-news ingestion.

The news radar page/API was removed, but the scheduled market-news task still
uses this small policy when preparing evidence for the AI pipeline.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


MAX_NEWS_AGE_HOURS = 72


def apply_news_freshness(data: dict[str, Any]) -> dict[str, Any]:
    """Annotate an internal news payload without exposing a UI route."""
    updated_at = str(data.get("updated_at") or "").strip()
    metadata = dict(data.get("_meta") or {})
    age_hours: float | None = None
    if updated_at:
        try:
            parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            now = datetime.now(parsed.tzinfo) if parsed.tzinfo else datetime.now()
            age_hours = max(0.0, (now - parsed).total_seconds() / 3600)
        except ValueError:
            age_hours = None
    has_content = bool(data.get("news"))
    stale = age_hours is None or age_hours > MAX_NEWS_AGE_HOURS
    if stale or not has_content:
        metadata.update({
            "available": False,
            "stale": stale,
            "age_hours": round(age_hours, 1) if age_hours is not None else None,
            "error": (
                f"新闻缓存已超过 {MAX_NEWS_AGE_HOURS} 小时，请刷新后再使用"
                if stale and age_hours is not None else
                "新闻数据缺少有效更新时间，请刷新后再使用"
                if stale else "资讯源没有返回有效内容"
            ),
        })
    else:
        metadata.update({"stale": False, "age_hours": round(age_hours, 1)})
    return {**data, "_meta": metadata}
