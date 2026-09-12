"""Shared transport helpers for native Eastmoney adapters."""

from __future__ import annotations

import asyncio
import copy
import threading
import time

import httpx

from src.infrastructure.market_data.stock_skill_bridge import normalize_stock_code

DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
REPORT_API_URL = "https://reportapi.eastmoney.com/report/list"
REPORT_PDF_TEMPLATE = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"
EASTMONEY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
}
_RATE_LOCK = asyncio.Lock()
_LAST_REQUEST = 0.0
_MIN_INTERVAL_SECONDS = 0.8
_CACHE_GUARD = threading.Lock()
_CACHE: dict[str, tuple[float, object]] = {}


def plain_code(code: str) -> str | None:
    normalized = normalize_stock_code(code)
    if not normalized:
        return None
    return normalized.split(".", 1)[0]


def number(value: object, default: float = 0.0) -> float:
    text = str(value or "").strip().replace(",", "")
    if not text or text in {"-", "--", "None", "null"}:
        return default
    try:
        return float(text.replace("%", ""))
    except (TypeError, ValueError):
        return default


async def pace() -> None:
    """Serialize Eastmoney calls and maintain a conservative request gap."""
    global _LAST_REQUEST
    async with _RATE_LOCK:
        wait = _MIN_INTERVAL_SECONDS - (time.monotonic() - _LAST_REQUEST)
        if wait > 0:
            await asyncio.sleep(wait)
        _LAST_REQUEST = time.monotonic()


def get_cached(key: str, ttl_seconds: float) -> tuple[object, float] | None:
    """Return a deep-copied fresh value and its age, if present."""
    now = time.monotonic()
    with _CACHE_GUARD:
        entry = _CACHE.get(key)
        if entry is None:
            return None
        stored_at, value = entry
        age = now - stored_at
        if age > max(0.0, float(ttl_seconds)):
            _CACHE.pop(key, None)
            return None
        return copy.deepcopy(value), age


def set_cached(key: str, value: object) -> None:
    """Store a successful native response for later in-process reuse."""
    with _CACHE_GUARD:
        if len(_CACHE) >= 256 and key not in _CACHE:
            oldest = min(_CACHE, key=lambda item: _CACHE[item][0])
            _CACHE.pop(oldest, None)
        _CACHE[key] = (time.monotonic(), copy.deepcopy(value))


def mark_cached(value: object, age_seconds: float) -> object:
    """Annotate a cached response without mutating the shared cache entry."""
    if not isinstance(value, dict):
        return value
    result = copy.deepcopy(value)
    metadata = dict(result.get("_meta") or {})
    metadata.update({
        "cached": True,
        "cache_age_seconds": round(max(0.0, age_seconds), 1),
    })
    result["_meta"] = metadata
    return result


async def query_datacenter(
    client: httpx.AsyncClient, report_name: str, params: dict[str, str]
) -> list[dict]:
    await pace()
    response = await client.get(
        DATACENTER_URL,
        params={
            "reportName": report_name,
            "columns": "ALL",
            "pageNumber": "1",
            "source": "WEB",
            "client": "WEB",
            **params,
        },
    )
    response.raise_for_status()
    payload = response.json()
    result = payload.get("result") if isinstance(payload, dict) else None
    rows = result.get("data") if isinstance(result, dict) else None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
