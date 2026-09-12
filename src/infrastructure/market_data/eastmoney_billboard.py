"""Native Eastmoney individual-stock billboard (龙虎榜) adapter."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from src.infrastructure.market_data.eastmoney_common import (
    DATACENTER_URL,
    EASTMONEY_HEADERS,
    get_cached,
    mark_cached,
    number,
    plain_code,
    query_datacenter,
    set_cached,
)


def parse_dragon_tiger_records(rows: object, *, limit: int = 50) -> list[dict[str, Any]]:
    """Normalize Eastmoney billboard summary rows into Adaptive fields."""
    if not isinstance(rows, list):
        return []
    parsed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        parsed.append({
            "date": str(row.get("TRADE_DATE") or "")[:10],
            "reason": row.get("EXPLANATION") or row.get("REASON") or "",
            "net_buy": round(number(row.get("BILLBOARD_NET_AMT")) / 10000, 1),
            "turnover": round(number(row.get("TURNOVERRATE")), 2),
        })
        if len(parsed) >= max(1, int(limit)):
            break
    return parsed


def parse_dragon_tiger_seats(rows: object, *, limit: int = 5) -> list[dict[str, Any]]:
    """Normalize buy/sell seat rows while retaining amounts in 万元."""
    if not isinstance(rows, list):
        return []
    seats: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        seats.append({
            "name": row.get("OPERATEDEPT_NAME") or row.get("SEAT_NAME") or "",
            "buy_amt": round(number(row.get("BUY")) / 10000, 1),
            "sell_amt": round(number(row.get("SELL")) / 10000, 1),
            "net": round(number(row.get("NET")) / 10000, 1),
        })
        if len(seats) >= max(1, int(limit)):
            break
    return seats


def _institution(buy_rows: object, sell_rows: object) -> dict[str, float]:
    buy_amount = 0.0
    sell_amount = 0.0
    for rows, side in ((buy_rows, "buy"), (sell_rows, "sell")):
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or str(row.get("OPERATEDEPT_CODE", "")) != "0":
                continue
            value = row.get("BUY") if side == "buy" else row.get("SELL")
            if side == "buy":
                buy_amount += number(value)
            else:
                sell_amount += number(value)
    buy_wan = round(buy_amount / 10000, 1)
    sell_wan = round(sell_amount / 10000, 1)
    return {"buy_amt": buy_wan, "sell_amt": sell_wan, "net_amt": round(buy_wan - sell_wan, 1)}


async def fetch_eastmoney_dragon_tiger(
    code: str, *, trade_date: str | None = None, look_back: int = 30, limit: int = 50
) -> dict[str, Any]:
    """Fetch one stock's dated billboard records and latest trading seats."""
    plain = plain_code(code)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    requested_date = trade_date or date.today().isoformat()
    metadata = {
        "provider": "eastmoney",
        "source_name": "Eastmoney datacenter billboard",
        "source_url": DATACENTER_URL,
        "source_layer": "adaptive_native",
        "historical": True,
        "point_in_time": True,
        "trade_date": requested_date,
        "fetched_at": fetched_at,
    }
    if plain is None:
        return {
            "data": {},
            "_meta": {**metadata, "available": False, "error": "invalid A-share code"},
        }
    cache_key = f"billboard:{plain}:{requested_date}:{look_back}:{limit}"
    cached = get_cached(cache_key, 300)
    if cached is not None:
        value, age = cached
        return mark_cached(value, age)

    try:
        end = date.fromisoformat(requested_date)
    except ValueError:
        end = date.today()
        requested_date = end.isoformat()
        metadata["trade_date"] = requested_date
    start = end - timedelta(days=max(1, min(180, int(look_back))))
    errors: list[str] = []
    records: list[dict[str, Any]] = []
    buy_rows: list[dict[str, Any]] = []
    sell_rows: list[dict[str, Any]] = []
    timeout = httpx.Timeout(connect=3.0, read=10.0, write=2.0, pool=1.0)
    try:
        async with httpx.AsyncClient(
            timeout=timeout, headers=EASTMONEY_HEADERS, follow_redirects=True
        ) as client:
            try:
                raw_records = await query_datacenter(
                    client,
                    "RPT_DAILYBILLBOARD_DETAILSNEW",
                    {
                        "filter": (
                            f"(TRADE_DATE>='{start.isoformat()}')"
                            f"(TRADE_DATE<='{requested_date}')"
                            f"(SECURITY_CODE=\"{plain}\")"
                        ),
                        "pageSize": str(max(1, min(100, int(limit)))),
                        "sortColumns": "TRADE_DATE",
                        "sortTypes": "-1",
                    },
                )
                records = parse_dragon_tiger_records(raw_records, limit=limit)
                if records:
                    latest_date = records[0]["date"]
                    buy_rows = await query_datacenter(
                        client,
                        "RPT_BILLBOARD_DAILYDETAILSBUY",
                        {
                            "filter": f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{plain}\")",
                            "pageSize": "10", "sortColumns": "BUY", "sortTypes": "-1",
                        },
                    )
                    sell_rows = await query_datacenter(
                        client,
                        "RPT_BILLBOARD_DAILYDETAILSSELL",
                        {
                            "filter": f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{plain}\")",
                            "pageSize": "10", "sortColumns": "SELL", "sortTypes": "-1",
                        },
                    )
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                errors.append(str(exc)[:180])
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        errors.append(str(exc)[:180])

    data = {
        "records": records,
        "seats": {
            "buy": parse_dragon_tiger_seats(buy_rows),
            "sell": parse_dragon_tiger_seats(sell_rows),
        },
        "institution": _institution(buy_rows, sell_rows),
    }
    has_data = bool(records or data["seats"]["buy"] or data["seats"]["sell"])
    result = {
        "data": data if has_data else {},
        "_meta": {
            **metadata,
            "available": has_data,
            "record_count": len(records),
            "error": (
                "; ".join(errors)
                if errors
                else ("no billboard records" if not has_data else "")
            ),
        },
    }
    if has_data:
        set_cached(cache_key, result)
    return result
