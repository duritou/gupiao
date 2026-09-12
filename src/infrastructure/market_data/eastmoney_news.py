"""Native Eastmoney news adapters for Adaptive's news radar."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from src.infrastructure.market_data.eastmoney_common import (
    EASTMONEY_HEADERS,
    get_cached,
    mark_cached,
    pace,
    plain_code,
    set_cached,
)

STOCK_NEWS_URL = "https://search-api-web.eastmoney.com/search/jsonp"
GLOBAL_NEWS_URL = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
_STOCK_NEWS_HEADERS = {**EASTMONEY_HEADERS, "Referer": "https://so.eastmoney.com/"}
_GLOBAL_NEWS_HEADERS = {**EASTMONEY_HEADERS, "Referer": "https://kuaixun.eastmoney.com/"}


def _strip_html(value: object) -> str:
    return re.sub(r"<[^>]+>", "", str(value or "")).strip()


def _parse_jsonp(text: str) -> object:
    raw = str(text or "").strip()
    if raw.startswith("{") or raw.startswith("["):
        return json.loads(raw)
    start = raw.find("(")
    end = raw.rfind(")")
    if start < 0 or end <= start:
        raise ValueError("Eastmoney response is not valid JSONP")
    return json.loads(raw[start + 1:end])


def parse_stock_news(payload: object, *, limit: int = 20) -> list[dict[str, Any]]:
    """Normalize Eastmoney stock-search articles."""
    if not isinstance(payload, dict):
        return []
    result = payload.get("result")
    articles = result.get("cmsArticleWebOld") if isinstance(result, dict) else None
    if not isinstance(articles, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in articles:
        if not isinstance(item, dict):
            continue
        title = _strip_html(item.get("title"))
        if not title:
            continue
        rows.append({
            "title": title,
            "content": _strip_html(item.get("content"))[:400],
            "time": str(item.get("date") or item.get("showTime") or ""),
            "source": str(item.get("mediaName") or item.get("source") or ""),
            "url": str(item.get("url") or ""),
        })
        if len(rows) >= max(1, int(limit)):
            break
    return rows


def parse_global_news(payload: object, *, limit: int = 50) -> list[dict[str, Any]]:
    """Normalize Eastmoney 7x24 fast-news rows to the radar contract."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    items = data.get("fastNewsList") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = _strip_html(item.get("title") or item.get("brief"))
        if not title:
            continue
        rows.append({
            "title": title,
            "summary": _strip_html(
                item.get("summary") or item.get("brief") or item.get("content")
            )[:400],
            "time": str(item.get("showTime") or item.get("time") or ""),
            "source": str(item.get("source") or item.get("mediaName") or "东方财富"),
            "url": str(item.get("url") or item.get("link") or ""),
            "industry": "",
            "industry_key": "",
            "published_ts": int(item.get("ts") or item.get("ctime") or 0),
        })
        if len(rows) >= max(1, int(limit)):
            break
    return rows


async def fetch_eastmoney_stock_news(code: str, *, page_size: int = 20) -> dict[str, Any]:
    """Fetch stock-specific news from Eastmoney's public search endpoint."""
    plain = plain_code(code)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    metadata = {
        "provider": "eastmoney",
        "source_name": "Eastmoney stock news",
        "source_url": STOCK_NEWS_URL,
        "source_layer": "adaptive_native",
        "historical": True,
        "fetched_at": fetched_at,
    }
    if plain is None:
        return {
            "news": [],
            "total_count": 0,
            "updated_at": "",
            "_meta": {**metadata, "available": False, "error": "invalid A-share code"},
        }
    cache_key = f"stock_news:{plain}:{page_size}"
    cached = get_cached(cache_key, 300)
    if cached is not None:
        value, age = cached
        return mark_cached(value, age)

    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    inner_params = json.dumps({
        "uid": "",
        "keyword": plain,
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {"cmsArticleWebOld": {
            "searchScope": "default", "sort": "default", "pageIndex": 1,
            "pageSize": max(1, min(100, int(page_size))), "preTag": "", "postTag": "",
        }},
    }, separators=(",", ":"))
    timeout = httpx.Timeout(connect=3.0, read=10.0, write=2.0, pool=1.0)
    try:
        async with httpx.AsyncClient(
            timeout=timeout, headers=_STOCK_NEWS_HEADERS, follow_redirects=True
        ) as client:
            await pace()
            response = await client.get(
                STOCK_NEWS_URL,
                params={"cb": "jQuery_news", "param": inner_params},
            )
            response.raise_for_status()
            rows = parse_stock_news(_parse_jsonp(response.text), limit=page_size)
    except (httpx.HTTPError, ValueError, TypeError, IndexError) as exc:
        errors.append(str(exc)[:180])
    result = {
        "news": rows,
        "total_count": len(rows),
        "updated_at": fetched_at,
        "_meta": {**metadata, "available": bool(rows), "error": "; ".join(errors)},
    }
    if rows:
        set_cached(cache_key, result)
    return result


async def fetch_eastmoney_global_news(*, page_size: int = 50) -> dict[str, Any]:
    """Fetch the Eastmoney 7x24 stream in the radar response shape."""
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    metadata = {
        "provider": "eastmoney",
        "source_name": "Eastmoney 7x24 fast news",
        "source_url": GLOBAL_NEWS_URL,
        "source_layer": "adaptive_native",
        "scope": "global_fast_news",
        "fetched_at": fetched_at,
    }
    cache_key = f"global_news:{page_size}"
    cached = get_cached(cache_key, 30)
    if cached is not None:
        value, age = cached
        return mark_cached(value, age)
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    timeout = httpx.Timeout(connect=3.0, read=10.0, write=2.0, pool=1.0)
    try:
        async with httpx.AsyncClient(
            timeout=timeout, headers=_GLOBAL_NEWS_HEADERS, follow_redirects=True
        ) as client:
            await pace()
            response = await client.get(
                GLOBAL_NEWS_URL,
                params={
                    "client": "web", "biz": "web_724", "fastColumn": "102",
                    "sortEnd": "", "pageSize": max(1, min(100, int(page_size))),
                    "req_trace": str(uuid.uuid4()),
                },
            )
            response.raise_for_status()
            rows = parse_global_news(response.json(), limit=page_size)
    except (httpx.HTTPError, ValueError, TypeError, IndexError) as exc:
        errors.append(str(exc)[:180])
    result = {
        "news": rows,
        "total_count": len(rows),
        "updated_at": fetched_at,
        "_meta": {**metadata, "available": bool(rows), "error": "; ".join(errors)},
    }
    if rows:
        set_cached(cache_key, result)
    return result
