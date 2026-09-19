"""Keep reference-index bars current in the local index_daily table.

The learning label scores against the equal-weight universe and reads none of
this.  These series exist so a person comparing the strategy to 沪深300 can do
it offline: the benchmark used to be fetched over the network on every backfill
and existed nowhere afterwards, so the comparison depended on whether that
particular run's fetch succeeded.

Writes are insert-only, so a daily refresh re-fetching an overlapping window
neither duplicates nor rewrites history.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from src.infrastructure.market_data.tushare_provider import tushare_provider
from src.infrastructure.storage.market_database import market_db

logger = logging.getLogger("uvicorn.error")

DEFAULT_INDEX_CODES = ("000300.SH",)

# Enough overlap that a few missed sessions still heal on the next run.
DEFAULT_REFRESH_DAYS = 30
DEFAULT_CHUNK_DAYS = 365


async def sync_reference_indices(
    codes: tuple[str, ...] | list[str] = DEFAULT_INDEX_CODES,
    *,
    days: int = DEFAULT_REFRESH_DAYS,
    chunk_days: int = DEFAULT_CHUNK_DAYS,
    end_date: str = "",
) -> dict[str, Any]:
    """Fetch and store reference-index bars. Returns a per-code summary."""
    result: dict[str, Any] = {"synced": {}, "errors": [], "source": "tushare"}
    if not tushare_provider.configured:
        result["errors"].append("tushare_token_missing")
        return result

    end = date.fromisoformat(end_date) if end_date else date.today()
    start = end - timedelta(days=max(1, int(days)))
    for code in codes:
        normalized = str(code or "").strip().upper()
        if not normalized:
            continue
        before = market_db.get_index_coverage(normalized)
        fetched = 0
        cursor = start
        while cursor <= end:
            window_end = min(cursor + timedelta(days=max(1, int(chunk_days))), end)
            try:
                payload = await tushare_provider.fetch_index_history(
                    normalized,
                    start_date=cursor.isoformat(),
                    end_date=window_end.isoformat(),
                    count=1000,
                )
            except Exception as exc:
                # One bad window must not discard the windows that worked.
                message = f"{normalized} {cursor}..{window_end}: {type(exc).__name__}: {exc}"
                result["errors"].append(message)
                logger.warning("[index] %s", message)
                cursor = window_end + timedelta(days=1)
                continue
            if payload.data:
                market_db.upsert_index_daily(payload.data)
                fetched += len(payload.data)
            cursor = window_end + timedelta(days=1)

        after = market_db.get_index_coverage(normalized)
        result["synced"][normalized] = {
            "fetched": fetched,
            "bars_before": before["bars"],
            "bars_after": after["bars"],
            "stored": after["bars"] - before["bars"],
            "first_date": after["first_date"],
            "last_date": after["last_date"],
        }
    return result
