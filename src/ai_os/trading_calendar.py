"""A-share trading-day checks with an explicit fallback."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class TradingDayStatus:
    is_trading_day: bool
    source: str
    degraded: bool = False
    error: str = ""


@dataclass(frozen=True)
class CompletedTradingDayStatus:
    day: date | None
    source: str
    degraded: bool = False
    error: str = ""


def paper_execution_calendar_verified(status: TradingDayStatus) -> bool:
    """Require an official, non-degraded calendar before paper fills."""
    return bool(status.is_trading_day and not status.degraded)


_cache: dict[str, TradingDayStatus] = {}
_completed_day_cache: dict[str, CompletedTradingDayStatus] = {}


async def get_trading_day_status(day: date | None = None) -> TradingDayStatus:
    """Return the official A-share calendar status when available."""
    target = day or date.today()
    key = target.isoformat()
    cached = _cache.get(key)
    if cached is not None:
        return cached

    try:
        status = await asyncio.wait_for(
            asyncio.to_thread(_query_baostock_calendar, key),
            timeout=15,
        )
    except Exception as exc:
        status = TradingDayStatus(
            is_trading_day=target.weekday() < 5,
            source="weekday_fallback",
            degraded=True,
            error=str(exc)[:200],
        )
    _cache[key] = status
    return status


def _query_baostock_calendar(day: str) -> TradingDayStatus:
    import baostock as bs

    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"baostock login failed: {login.error_msg}")
    try:
        result = bs.query_trade_dates(start_date=day, end_date=day)
        if result.error_code != "0":
            raise RuntimeError(f"trade calendar failed: {result.error_msg}")
        if not result.next():
            raise RuntimeError("trade calendar returned no row")
        row = dict(zip(result.fields, result.get_row_data(), strict=False))
        return TradingDayStatus(
            is_trading_day=str(row.get("is_trading_day", "0")) == "1",
            source="baostock_trade_calendar",
        )
    finally:
        bs.logout()


async def get_latest_completed_trading_day(
    day: date | None = None,
) -> CompletedTradingDayStatus:
    """Return the latest exchange trading day completed before ``day``."""
    target = day or date.today()
    key = target.isoformat()
    cached = _completed_day_cache.get(key)
    if cached is not None:
        return cached
    try:
        status = await asyncio.wait_for(
            asyncio.to_thread(_query_latest_completed_trading_day, target),
            timeout=15,
        )
    except Exception as exc:
        fallback = target - timedelta(days=1)
        while fallback.weekday() >= 5:
            fallback -= timedelta(days=1)
        status = CompletedTradingDayStatus(
            day=fallback,
            source="weekday_fallback",
            degraded=True,
            error=str(exc)[:200],
        )
    _completed_day_cache[key] = status
    return status


def _query_latest_completed_trading_day(target: date) -> CompletedTradingDayStatus:
    import baostock as bs

    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"baostock login failed: {login.error_msg}")
    try:
        result = bs.query_trade_dates(
            start_date=(target - timedelta(days=14)).isoformat(),
            end_date=(target - timedelta(days=1)).isoformat(),
        )
        if result.error_code != "0":
            raise RuntimeError(f"trade calendar failed: {result.error_msg}")
        completed: list[date] = []
        while result.next():
            row = dict(zip(result.fields, result.get_row_data(), strict=False))
            if str(row.get("is_trading_day", "0")) == "1":
                completed.append(date.fromisoformat(str(row["calendar_date"])))
        if not completed:
            raise RuntimeError("trade calendar returned no completed trading day")
        return CompletedTradingDayStatus(
            day=max(completed),
            source="baostock_trade_calendar",
        )
    finally:
        bs.logout()
