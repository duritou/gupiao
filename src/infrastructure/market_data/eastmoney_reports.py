"""Native Eastmoney individual-stock research-report adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from src.infrastructure.market_data.eastmoney_common import (
    EASTMONEY_HEADERS,
    REPORT_API_URL,
    REPORT_PDF_TEMPLATE,
    get_cached,
    mark_cached,
    pace,
    plain_code,
    set_cached,
)


def parse_eastmoney_reports(payload: object, *, limit: int = 100) -> list[dict[str, Any]]:
    """Normalize Eastmoney reportapi rows to the Vibe report contract."""
    if not isinstance(payload, dict):
        return []
    rows = payload.get("data")
    if not isinstance(rows, list):
        return []
    reports: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        info_code = str(row.get("infoCode") or row.get("info_code") or "")
        reports.append({
            **row,
            "id": row.get("id") or info_code,
            "publish_date": row.get("publish_date") or row.get("publishDate") or "",
            "author": row.get("author") or row.get("researcher") or "",
            "institution": (
                row.get("institution") or row.get("orgSName") or row.get("orgName") or ""
            ),
            "pdfUrl": row.get("pdfUrl") or (
                REPORT_PDF_TEMPLATE.format(info_code=info_code) if info_code else ""
            ),
        })
        if len(reports) >= max(1, int(limit)):
            break
    return reports


async def fetch_eastmoney_reports(
    code: str, *, max_pages: int = 2, limit: int = 100
) -> dict[str, Any]:
    """Fetch recent stock research reports from Eastmoney reportapi."""
    plain = plain_code(code)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    metadata = {
        "provider": "eastmoney",
        "source_name": "Eastmoney research reports",
        "source_url": REPORT_API_URL,
        "source_layer": "adaptive_native",
        "historical": True,
        "point_in_time": True,
        "fetched_at": fetched_at,
    }
    if plain is None:
        return {
            "reports": [],
            "count": 0,
            "_meta": {**metadata, "available": False, "error": "invalid A-share code"},
        }
    cache_key = f"reports:{plain}:{max_pages}:{limit}"
    cached = get_cached(cache_key, 900)
    if cached is not None:
        value, age = cached
        return mark_cached(value, age)

    reports: list[dict[str, Any]] = []
    errors: list[str] = []
    timeout = httpx.Timeout(connect=3.0, read=15.0, write=2.0, pool=1.0)
    try:
        async with httpx.AsyncClient(
            timeout=timeout, headers=EASTMONEY_HEADERS, follow_redirects=True
        ) as client:
            for page in range(1, max(1, min(5, int(max_pages))) + 1):
                await pace()
                try:
                    response = await client.get(
                        REPORT_API_URL,
                        params={
                            "industryCode": "*", "pageSize": "100", "industry": "*",
                            "rating": "*", "ratingChange": "*", "beginTime": "2000-01-01",
                            "endTime": "2030-01-01", "pageNo": str(page), "fields": "",
                            "qType": "0", "orgCode": "", "code": plain, "rcode": "",
                            "p": str(page), "pageNum": str(page), "pageNumber": str(page),
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                    page_rows = parse_eastmoney_reports(payload, limit=limit)
                    if not page_rows:
                        break
                    reports.extend(page_rows)
                    total_pages = (
                        int(payload.get("TotalPage") or 1)
                        if isinstance(payload, dict)
                        else 1
                    )
                    if page >= total_pages:
                        break
                except (httpx.HTTPError, ValueError, TypeError) as exc:
                    errors.append(str(exc)[:180])
                    break
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        errors.append(str(exc)[:180])

    unique: dict[str, dict[str, Any]] = {}
    for report in reports:
        key = str(report.get("id") or "") or (
            f"{report.get('title', '')}|{report.get('publish_date', '')}"
        )
        unique.setdefault(key, report)
    reports = list(unique.values())[: max(1, int(limit))]
    result = {
        "reports": reports,
        "count": len(reports),
        "_meta": {
            **metadata,
            "available": bool(reports),
            "error": "; ".join(errors) if errors else ("no reports" if not reports else ""),
        },
    }
    if reports:
        set_cached(cache_key, result)
    return result
