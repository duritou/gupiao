"""Native Eastmoney limit-up sentiment adapter for Adaptive."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import httpx

from src.infrastructure.market_data.eastmoney_common import (
    EASTMONEY_HEADERS,
    get_cached,
    mark_cached,
    pace,
    set_cached,
)

ZTP_UT = "7eea3edcaed734bea9cbfc24409ed989"
_POOL_ENDPOINTS = {
    "limit_up": ("getTopicZTPool", "fbt:asc"),
    "broken_board": ("getTopicZBPool", "fbt:asc"),
    "limit_down": ("getTopicDTPool", "fund:asc"),
    "yesterday_limit_up": ("getYesterdayZTPool", "zs:desc"),
}
_POOL_HEADERS = {**EASTMONEY_HEADERS, "Referer": "https://quote.eastmoney.com/"}


def _number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _time(value: object) -> str:
    text = str(value or "").zfill(6)
    return f"{text[:2]}:{text[2:4]}:{text[4:6]}" if len(text) >= 6 else ""


def parse_limit_pool(payload: object, pool_type: str, *, limit: int = 200) -> list[dict[str, Any]]:
    """Normalize one Eastmoney limit-up pool response."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    pool = data.get("pool") if isinstance(data, dict) else None
    if not isinstance(pool, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in pool:
        if not isinstance(item, dict):
            continue
        stats = item.get("zttj") if isinstance(item.get("zttj"), dict) else {}
        row = {
            "code": str(item.get("c") or ""),
            "name": str(item.get("n") or ""),
            "price": round(_number(item.get("p")) / 1000, 3),
            "change_pct": round(_number(item.get("zdp")), 2),
            "turnover_pct": round(_number(item.get("hs")), 2),
            "amount": _number(item.get("amount")),
            "industry": str(item.get("hybk") or ""),
            "limit_days": _int(item.get("lbc")),
            "board_stat": f"{stats.get('days', '?')}天{stats.get('ct', '?')}板",
            "first_seal": _time(item.get("fbt")),
            "last_seal": _time(item.get("lbt")),
            "break_times": _int(item.get("zbc")),
            "seal_fund": _number(item.get("fund")),
            "pool_type": pool_type,
        }
        if pool_type == "broken_board":
            row.update({
                "limit_price": round(_number(item.get("ztp")) / 1000, 3),
                "amplitude_pct": round(_number(item.get("zf")), 2),
                "speed_pct": round(_number(item.get("zs")), 2),
            })
        elif pool_type == "limit_down":
            row.update({
                "consecutive_limit_down": _int(item.get("days")),
                "open_times": _int(item.get("oc")),
                "board_amount": _number(item.get("fba")),
            })
        elif pool_type == "yesterday_limit_up":
            row.update({"yesterday_limit_days": _int(item.get("ylbc"))})
        rows.append(row)
        if len(rows) >= max(1, int(limit)):
            break
    return rows


async def _fetch_pool(
    client: httpx.AsyncClient,
    pool_type: str,
    trade_date: str,
    errors: list[str],
) -> list[dict[str, Any]]:
    endpoint, sort = _POOL_ENDPOINTS[pool_type]
    try:
        await pace()
        response = await client.get(
            f"https://push2ex.eastmoney.com/{endpoint}",
            params={
                "ut": ZTP_UT,
                "dpt": "wz.ztzt",
                "Pageindex": 0,
                "pagesize": 10000,
                "sort": sort,
                "date": trade_date,
            },
        )
        response.raise_for_status()
        return parse_limit_pool(response.json(), pool_type)
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        errors.append(f"{pool_type}: {str(exc)[:120]}")
        return []


async def fetch_limit_up_sentiment(trade_date: str | None = None) -> dict[str, Any]:
    """Calculate point-in-time limit-up sentiment from four public pools."""
    requested_date = trade_date or date.today().strftime("%Y%m%d")
    try:
        requested_date = date.fromisoformat(requested_date).strftime("%Y%m%d")
    except ValueError:
        requested_date = str(requested_date).replace("-", "")[:8]
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    metadata = {
        "provider": "eastmoney",
        "source_name": "Eastmoney limit-up pools",
        "source_url": "https://push2ex.eastmoney.com/getTopicZTPool",
        "source_layer": "adaptive_native",
        "historical": True,
        "point_in_time": True,
        "trade_date": requested_date,
        "fetched_at": fetched_at,
    }
    cache_key = f"emotion:{requested_date}"
    cached = get_cached(cache_key, 60)
    if cached is not None:
        value, age = cached
        return mark_cached(value, age)
    errors: list[str] = []
    pools: dict[str, list[dict[str, Any]]] = {}
    timeout = httpx.Timeout(connect=3.0, read=10.0, write=2.0, pool=1.0)
    try:
        async with httpx.AsyncClient(
            timeout=timeout, headers=_POOL_HEADERS, follow_redirects=True
        ) as client:
            for pool_type in _POOL_ENDPOINTS:
                pools[pool_type] = await _fetch_pool(client, pool_type, requested_date, errors)
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        errors.append(str(exc)[:160])

    limit_up = pools.get("limit_up", [])
    broken = pools.get("broken_board", [])
    limit_down = pools.get("limit_down", [])
    yesterday = pools.get("yesterday_limit_up", [])
    ladder: dict[str, int] = {}
    for item in limit_up:
        height = str(max(0, _int(item.get("limit_days"))))
        ladder[height] = ladder.get(height, 0) + 1
    promoted = sum(1 for item in yesterday if _number(item.get("change_pct")) >= 9.8)
    total_board_events = len(limit_up) + len(broken)
    data = {
        "date": requested_date,
        "zt_count": len(limit_up),
        "zb_count": len(broken),
        "dt_count": len(limit_down),
        "break_rate": (
            round(len(broken) / total_board_events * 100, 1)
            if total_board_events else 0.0
        ),
        "seal_rate": (
            round(len(limit_up) / total_board_events * 100, 1)
            if total_board_events else 0.0
        ),
        "max_height": max((_int(item.get("limit_days")) for item in limit_up), default=0),
        "ladder": dict(sorted(ladder.items(), key=lambda pair: int(pair[0]))),
        "yesterday_limit_up_count": len(yesterday),
        "promotion_count": promoted,
        "promotion_rate": round(promoted / len(yesterday) * 100, 1) if yesterday else 0.0,
        "limit_up_stocks": limit_up[:100],
        "broken_board_stocks": broken[:100],
        "limit_down_stocks": limit_down[:100],
    }
    available = bool(limit_up or broken or limit_down or yesterday)
    result = {
        "data": data if available else {},
        "_meta": {
            **metadata,
            "available": available,
            "error": "; ".join(errors) if errors else ("no limit-up data" if not available else ""),
        },
    }
    if available:
        set_cached(cache_key, result)
    return result
