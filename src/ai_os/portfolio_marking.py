"""Remote quote marking for the persistent paper portfolio."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any


async def refresh_paper_portfolio_quotes(
    valuation_date: str | None = None,
    database: Any | None = None,
    quote_source: Any | None = None,
) -> dict[str, Any]:
    """Fetch every held symbol and persist an auditable portfolio snapshot."""
    if database is None:
        from src.infrastructure.storage.market_database import market_db

        database = market_db
    if quote_source is None:
        from src.infrastructure.market_data.source_manager import source_manager

        quote_source = source_manager

    snapshot_date = valuation_date or date.today().isoformat()
    positions = await asyncio.to_thread(database.get_paper_positions)

    async def fetch(position: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        code = str(position["stock_code"])
        quote, provenance = await quote_source.get_realtime_quote(code)
        if quote is None:
            return code, {
                "source": provenance.provider or "unavailable",
                "fetched_at": provenance.fetched_at,
                "error": provenance.error_message,
            }

        normalized = dict(quote)
        normalized["source"] = provenance.provider or normalized.get("source") or "unknown"
        normalized["fetched_at"] = provenance.fetched_at
        # Live providers do not all expose an exchange timestamp. During an
        # active/finished trading session their real-time mark belongs to the
        # requested valuation date; providers with an explicit date keep it.
        if not normalized.get("data_date") and provenance.is_live:
            normalized["data_date"] = snapshot_date
        return code, normalized

    fetched = await asyncio.gather(*(fetch(position) for position in positions))
    quotes = dict(fetched)
    return await asyncio.to_thread(
        database.mark_paper_portfolio,
        snapshot_date,
        quotes,
    )

