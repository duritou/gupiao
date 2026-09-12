"""Causal quote acquisition for paper fills without look-ahead bias."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, time, timedelta, timezone
from typing import Any

CHINA_TZ = timezone(timedelta(hours=8))


def parse_timestamp(value: str, default_timezone=CHINA_TZ) -> datetime | None:
    """Parse provider or ISO timestamps into timezone-aware datetimes."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if len(text) >= 14 and text[:14].isdigit():
            parsed = datetime.strptime(text[:14], "%Y%m%d%H%M%S")
            return parsed.replace(tzinfo=CHINA_TZ)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=default_timezone)
    except ValueError:
        return None


def in_a_share_session(timestamp: datetime) -> bool:
    """Return whether a quote is in a supported continuous-auction session.

    The simulator intentionally excludes opening and closing call auctions
    because it does not model an order book, auction queue, or final match.
    """
    local = timestamp.astimezone(CHINA_TZ)
    if local.weekday() >= 5:
        return False
    current = local.time().replace(tzinfo=None)
    return (
        time(9, 30) <= current <= time(11, 30)
        or time(13, 0) <= current < time(14, 57)
    )


def validate_post_signal_quote(
    decision: dict[str, Any],
    quote: dict[str, Any],
    *,
    max_source_lag_seconds: float = 30.0,
) -> tuple[dict[str, Any] | None, str]:
    """Accept only a fresh exchange quote observed after the final signal."""
    signal_at = parse_timestamp(str(decision.get("signal_at") or ""))
    data_cutoff_at = parse_timestamp(str(decision.get("data_cutoff_at") or ""))
    exchange_at = parse_timestamp(str(quote.get("exchange_timestamp") or ""))
    fetched_at = parse_timestamp(str(quote.get("fetched_at") or ""), timezone.utc)
    if signal_at is None:
        return None, "missing_or_invalid_signal_timestamp"
    if data_cutoff_at is None:
        return None, "missing_or_invalid_data_cutoff"
    if data_cutoff_at > signal_at:
        return None, "data_cutoff_after_signal"
    if exchange_at is None:
        return None, "missing_or_invalid_exchange_timestamp"
    if fetched_at is None:
        return None, "missing_or_invalid_quote_fetch_timestamp"
    fetched_local = fetched_at.astimezone(CHINA_TZ)
    # Tencent timestamps have one-second precision. Requiring a strictly later
    # second prevents a pre-signal snapshot from becoming a simulated fill.
    signal_second = signal_at.astimezone(CHINA_TZ).replace(microsecond=0)
    if exchange_at <= signal_second:
        return None, "quote_not_after_signal"
    if exchange_at > fetched_local + timedelta(seconds=5):
        return None, "future_dated_exchange_quote"
    source_lag = (fetched_local - exchange_at.astimezone(CHINA_TZ)).total_seconds()
    if source_lag < -5 or source_lag > max_source_lag_seconds:
        return None, "stale_exchange_quote"
    if not in_a_share_session(exchange_at):
        return None, "quote_outside_market_session"
    if not in_a_share_session(fetched_local):
        return None, "quote_received_outside_market_session"
    price = float(quote.get("price") or 0)
    if price <= 0:
        return None, "missing_market_price"
    data_date = str(quote.get("data_date") or "")
    if data_date != exchange_at.astimezone(CHINA_TZ).date().isoformat():
        return None, "quote_date_timestamp_mismatch"
    source = str(quote.get("source") or "")
    if not source or not any(
        provider in source.lower()
        for provider in ("tencent", "tickflow", "tushare_rt_min")
    ):
        return None, "unverified_execution_quote_source"
    normalized = dict(quote)
    normalized.update({
        "exchange_at": exchange_at.isoformat(),
        "fetched_at": fetched_local.isoformat(),
        "source_lag_seconds": round(source_lag, 3),
        "causality_status": "verified_post_signal_quote",
    })
    return normalized, "verified_post_signal_quote"


async def fetch_post_signal_quotes(
    decisions: list[dict[str, Any]],
    fetch_quotes: Callable[[list[str]], Awaitable[dict[str, dict[str, Any]]]],
    *,
    attempts: int = 4,
    retry_delay_seconds: float = 1.0,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Fetch a new quote after each final signal, retrying timestamp lag only."""
    by_code = {
        str(decision.get("stock_code") or ""): decision
        for decision in decisions
        if decision.get("stock_code")
    }
    accepted: dict[str, dict[str, Any]] = {}
    reasons: dict[str, str] = {}
    pending = set(by_code)
    for attempt in range(max(1, int(attempts))):
        if not pending:
            break
        try:
            quotes = await fetch_quotes(sorted(pending))
        except Exception as exc:
            for code in pending:
                reasons[code] = f"execution_quote_fetch_failed:{str(exc)[:120]}"
            quotes = {}
        for code in list(pending):
            quote = quotes.get(code)
            if not quote:
                reasons[code] = "missing_execution_quote"
                continue
            verified, reason = validate_post_signal_quote(by_code[code], quote)
            reasons[code] = reason
            if verified is not None:
                accepted[code] = verified
                pending.remove(code)
        if pending and attempt + 1 < attempts:
            await asyncio.sleep(max(0.0, retry_delay_seconds))
    rejected = [
        {
            "stock_code": code,
            "signal_at": by_code[code].get("signal_at", ""),
            "data_cutoff_at": by_code[code].get("data_cutoff_at", ""),
            "reason": reasons.get(code, "execution_quote_unavailable"),
        }
        for code in sorted(pending)
    ]
    return accepted, rejected
