"""Dated Tushare flow for research, never a realtime execution quote."""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Any


async def completed_research_day():
    from src.ai_os.trading_calendar import get_latest_completed_trading_day

    now = datetime.now(timezone(timedelta(hours=8)))
    # After the daily publication window, require today's close if it is open.
    cutoff = now.date() + timedelta(days=int(now.hour >= 16))
    return await get_latest_completed_trading_day(cutoff)


def aggregate_flow(rows: list[dict[str, Any]], days: int, expected: str) -> dict[str, Any]:
    selected = sorted(rows, key=lambda row: str(row.get("trade_date", "")), reverse=True)[:days]
    if len(selected) < days or str(selected[0].get("trade_date")) != expected:
        raise ValueError("incomplete_or_stale_flow_window")
    dates = [str(row.get("trade_date", "")) for row in selected]
    if len(set(dates)) != days:
        raise ValueError("duplicate_flow_dates")
    values = [float(row["main_net"]) for row in selected]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("invalid_flow_values")
    total = round(sum(values), 2)
    return {
        "status": "positive" if total > 0 else "negative",
        "main_net": total, "latest_main_net": values[0], "row_count": days,
        "trade_date": expected, "data_date": expected, "source": "tushare",
        "endpoint": "local.fund_flow_history", "is_realtime": False,
        "granularity": f"daily_{days}d_fallback", "is_cached": True,
        "attempted": True, "fallback_attempted": True, "fallback_status": "confirmed",
        "fetched_at": selected[0].get("fetched_at", ""),
    }


async def get_research_flow(code: str, days: int = 5) -> dict[str, Any]:
    from src.infrastructure.market_data.tushare_provider import tushare_provider
    from src.infrastructure.storage import market_database as database_module

    calendar = await completed_research_day()
    if calendar.degraded or not calendar.day:
        raise ValueError("research_calendar_unverified")
    expected = calendar.day.isoformat()
    rows = await asyncio.to_thread(database_module.market_db.get_fund_flow_history, code, days)
    try:
        return aggregate_flow(rows, days, expected)
    except (ValueError, TypeError, KeyError):
        pass
    payload = await tushare_provider.fetch_moneyflow(code, days)
    flow = dict(payload.data)
    if flow.get("data_date") != expected or int(flow.get("row_count", 0)) < days:
        raise ValueError("tushare_flow_incomplete_or_stale")
    if not math.isfinite(float(flow.get("main_net"))):
        raise ValueError("tushare_flow_invalid")
    return {**flow, "is_realtime": False}
