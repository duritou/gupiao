"""Native CNINFO announcement adapter for Adaptive.

CNINFO is used for stock-specific disclosure records because it is the primary
official disclosure source.  The response is normalized to the fields already
used by the Adaptive UI, while keeping publication dates and PDF/detail links.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from src.infrastructure.market_data.stock_skill_bridge import normalize_stock_code

CNINFO_STOCK_MAP_URL = "https://www.cninfo.com.cn/new/data/szse_stock.json"
CNINFO_ANNOUNCEMENT_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://www.cninfo.com.cn/new/disclosure",
    "Origin": "https://www.cninfo.com.cn",
}
_ORGID_CACHE: dict[str, str] = {}


def _normalized_code(code: str) -> tuple[str, str] | None:
    normalized = normalize_stock_code(code)
    if not normalized:
        return None
    plain, exchange = normalized.split(".", 1)
    if exchange not in {"SH", "SZ"}:
        return None
    return plain, exchange.lower()


def _timestamp_to_date(value: object) -> str:
    if isinstance(value, int | float):
        try:
            china_tz = timezone(timedelta(hours=8))
            return datetime.fromtimestamp(value / 1000, tz=china_tz).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return ""
    return str(value or "")[:10]


def parse_cninfo_announcements(payload: object, *, limit: int = 30) -> list[dict[str, Any]]:
    """Normalize a CNINFO ``announcements`` response."""
    if not isinstance(payload, dict):
        return []
    rows: list[dict[str, Any]] = []
    for item in payload.get("announcements") or []:
        if not isinstance(item, dict):
            continue
        announcement_id = str(item.get("announcementId") or "")
        title = str(item.get("announcementTitle") or item.get("title") or "").strip()
        if not title:
            continue
        adjunct = str(item.get("adjunctUrl") or item.get("attachPath") or "").strip()
        if adjunct and not adjunct.startswith(("http://", "https://")):
            adjunct = f"https://static.cninfo.com.cn/{adjunct.lstrip('/')}"
        rows.append({
            "title": title,
            "type": str(item.get("announcementTypeName") or item.get("type") or ""),
            "date": _timestamp_to_date(item.get("announcementTime") or item.get("publishTime")),
            "url": (
                f"https://www.cninfo.com.cn/new/disclosure/detail?annoId={announcement_id}"
                if announcement_id
                else str(item.get("url") or adjunct)
            ),
            "pdf": adjunct,
            "source": "cninfo",
        })
        if len(rows) >= max(1, int(limit)):
            break
    return rows


def _fallback_org_id(plain: str, market: str) -> str:
    return f"gs{market}0{plain}"


async def _load_orgid_map(client: httpx.AsyncClient) -> dict[str, str]:
    if _ORGID_CACHE:
        return _ORGID_CACHE
    response = await client.get(CNINFO_STOCK_MAP_URL)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("stockList") if isinstance(payload, dict) else None
    if isinstance(rows, list):
        _ORGID_CACHE.update({
            str(item.get("code")): str(item.get("orgId"))
            for item in rows
            if isinstance(item, dict) and item.get("code") and item.get("orgId")
        })
    return _ORGID_CACHE


async def fetch_cninfo_announcements(code: str, *, limit: int = 30) -> dict[str, Any]:
    """Fetch dated CNINFO disclosure records for one A-share."""
    parsed = _normalized_code(code)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if parsed is None:
        return {
            "announcements": [],
            "count": 0,
            "_meta": {
                "provider": "cninfo",
                "source_layer": "adaptive_native",
                "available": False,
                "error": "invalid A-share code",
                "fetched_at": fetched_at,
            },
        }

    plain, market = parsed
    safe_limit = max(1, min(100, int(limit)))
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    timeout = httpx.Timeout(connect=3.0, read=8.0, write=2.0, pool=1.0)
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            headers=_HEADERS,
            follow_redirects=True,
        ) as client:
            try:
                orgid_map = await _load_orgid_map(client)
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                orgid_map = _ORGID_CACHE
                errors.append(f"orgid map: {str(exc)[:120]}")
            org_id = orgid_map.get(plain) or _fallback_org_id(plain, market)
            response = await client.post(
                CNINFO_ANNOUNCEMENT_URL,
                data={
                    "stock": f"{plain},{org_id}",
                    "tabName": "fulltext",
                    "pageSize": str(safe_limit),
                    "pageNum": "1",
                    "column": "",
                    "category": "",
                    "plate": "",
                    "seDate": "",
                    "searchkey": "",
                    "secid": "",
                    "sortName": "",
                    "sortType": "",
                    "isHLtitle": "true",
                },
            )
            response.raise_for_status()
            rows = parse_cninfo_announcements(response.json(), limit=safe_limit)
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        errors.append(str(exc)[:120])

    return {
        "announcements": rows,
        "count": len(rows),
        "_meta": {
            "provider": "cninfo",
            "source_name": "CNINFO official disclosure",
            "source_url": CNINFO_ANNOUNCEMENT_URL,
            "source_layer": "adaptive_native",
            "available": bool(rows),
            "historical": True,
            "fetched_at": fetched_at,
            "error": "; ".join(errors) if not rows and errors else "",
        },
    }
