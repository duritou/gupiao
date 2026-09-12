"""Bounded current quote metadata sync for the live stock universe.

Tencent quotes provide valuation fields that BaoStock does not expose in the
local universe table.  This job refreshes the latest-state cache in batches;
only quotes whose own data date matches the requested market date are copied
into the replay metadata table.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any

from src.infrastructure.market_data.remote_market_discovery import (
    RemoteMarketDiscovery,
    normalize_a_share_code,
)


def _normalized_codes(codes: list[str] | None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in codes or []:
        code = normalize_a_share_code(value)
        if code and code not in seen:
            result.append(code)
            seen.add(code)
    return result


async def _try_tushare_metadata(
    codes: list[str], target_date: str
) -> dict[str, Any] | None:
    """Use one dated Tushare snapshot before remote quote fallbacks."""
    from src.infrastructure.market_data.tushare_provider import tushare_provider
    from src.infrastructure.storage.market_database import market_db

    try:
        snapshot, metadata = await asyncio.gather(
            tushare_provider.fetch_daily_snapshot(target_date),
            tushare_provider.fetch_stock_metadata(),
        )
        coverage = snapshot.coverage_ratio
        if not target_date or coverage is None or coverage < 0.80:
            return None
        metadata_by_code = {
            str(item.get("ts_code") or ""): item for item in metadata.data
        }
        allowed = set(codes)
        rows = []
        for item in snapshot.data:
            code = str(item.get("ts_code") or "").upper()
            if code not in allowed:
                continue
            basic = metadata_by_code.get(code, {})
            rows.append({
                "ts_code": code,
                "name": basic.get("name") or code,
                "industry": basic.get("industry") or "",
                "list_date": basic.get("list_date") or "",
                "market_cap_yi": item.get("market_cap_yi"),
                "float_mcap_yi": item.get("float_mcap_yi"),
                "turnover_pct": item.get("turnover"),
                "data_date": str(item.get("trade_date") or target_date),
                "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "source": "tushare",
            })
        stored = await asyncio.to_thread(
            market_db.upsert_current_stock_metadata, rows, target_date
        )
        return {
            "status": "ok" if len(rows) == len(codes) else "partial",
            "as_of_date": target_date,
            "requested_count": len(codes),
            "quote_count": len(rows),
            "market_cap_count": sum(
                item.get("market_cap_yi") not in (None, "") for item in rows
            ),
            "current_count": int(stored.get("current_count", 0)),
            "history_count": int(stored.get("history_count", 0)),
            "missing_count": len(codes) - len(rows),
            "source": "tushare",
            "coverage_ratio": coverage,
            "errors": [] if len(rows) == len(codes) else ["tushare_code_coverage_partial"],
        }
    except Exception as exc:
        return {
            "status": "failed",
            "as_of_date": target_date,
            "requested_count": len(codes),
            "quote_count": 0,
            "market_cap_count": 0,
            "current_count": 0,
            "history_count": 0,
            "missing_count": len(codes),
            "source": "tushare",
            "errors": [f"tushare_metadata:{type(exc).__name__}:{str(exc)[:160]}"],
        }


async def sync_current_stock_metadata(
    codes: list[str] | None = None,
    *,
    as_of_date: str = "",
    timeout_seconds: float | None = None,
    stock_skill_enabled: bool | None = None,
) -> dict[str, Any]:
    """Refresh quote-derived metadata without weakening fail-closed policy."""
    from config.settings import settings
    from src.infrastructure.storage.market_database import market_db

    if codes is None:
        universe = await asyncio.to_thread(
            market_db.get_stock_universe,
            min_bars=20,
            limit=int(getattr(settings, "SCANNER_FULL_UNIVERSE_COUNT", 6000)),
        )
        codes = [str(item.get("code") or "") for item in universe]
    normalized = _normalized_codes(codes)
    target_date = as_of_date or market_db.get_latest_market_date_on_or_before(
        date.today().isoformat()
    ) or ""
    if not normalized:
        return {
            "status": "skipped",
            "as_of_date": target_date,
            "requested_count": 0,
            "quote_count": 0,
            "market_cap_count": 0,
            "current_count": 0,
            "history_count": 0,
            "missing_count": 0,
            "errors": ["empty_a_share_universe"],
        }

    status_snapshot = await asyncio.to_thread(
        market_db.sync_stock_metadata_snapshot,
        target_date,
        codes=normalized,
    )
    status_errors = list(status_snapshot.get("errors") or [])
    if status_snapshot.get("status") not in {"ok", "empty"} and not status_errors:
        status_errors.append(
            f"trading_status_snapshot:{status_snapshot.get('status') or 'unknown'}"
        )

    tushare_result = await _try_tushare_metadata(normalized, target_date)
    if tushare_result and tushare_result.get("status") == "ok":
        tushare_result["trading_status_snapshot"] = status_snapshot
        tushare_result["errors"] = [
            *status_errors,
            *(tushare_result.get("errors") or []),
        ]
        if status_errors:
            tushare_result["status"] = "partial"
        return tushare_result

    discovery = RemoteMarketDiscovery(
        timeout_seconds=(
            float(timeout_seconds)
            if timeout_seconds is not None
            else float(getattr(settings, "REMOTE_MARKET_TIMEOUT_SECONDS", 12.0))
        ),
        stock_skill_enabled=(
            bool(stock_skill_enabled)
            if stock_skill_enabled is not None
            else bool(getattr(settings, "STOCK_SKILL_BRIDGE_ENABLED", True))
        ),
        max_quote_count=max(1, len(normalized)),
    )
    try:
        quotes = await discovery.fetch_live_quotes(normalized)
    except Exception as exc:
        return {
            "status": "failed",
            "as_of_date": target_date,
            "requested_count": len(normalized),
            "quote_count": 0,
            "market_cap_count": 0,
            "current_count": 0,
            "history_count": 0,
            "missing_count": len(normalized),
            "errors": [f"quote_fetch_failed:{type(exc).__name__}:{str(exc)[:180]}"],
        }

    rows: list[dict[str, Any]] = []
    market_cap_count = 0
    for code, quote in quotes.items():
        normalized_code = normalize_a_share_code(code)
        if not normalized_code or not isinstance(quote, dict):
            continue
        market_cap = quote.get("market_cap_yi") or quote.get("mcap_yi")
        try:
            has_market_cap = float(market_cap or 0) > 0
        except (TypeError, ValueError):
            has_market_cap = False
        market_cap_count += int(has_market_cap)
        rows.append(
            {
                "ts_code": normalized_code,
                "name": quote.get("name") or normalized_code,
                "market_cap_yi": market_cap if has_market_cap else None,
                "float_mcap_yi": quote.get("float_mcap_yi"),
                "turnover_pct": quote.get("turnover_pct"),
                "data_date": str(quote.get("data_date") or ""),
                "fetched_at": str(quote.get("fetched_at") or ""),
                "source": str(quote.get("source") or ""),
            }
        )

    stored = await asyncio.to_thread(
        market_db.upsert_current_stock_metadata,
        rows,
        target_date,
    )
    missing_count = len(set(normalized) - set(quotes))
    errors: list[str] = []
    errors.extend(status_errors)
    if missing_count:
        errors.append(f"quote_missing:{missing_count}")
    missing_market_cap = len(rows) - market_cap_count
    if missing_market_cap:
        errors.append(f"market_cap_missing:{missing_market_cap}")
    status = "ok" if not errors and len(rows) == len(normalized) else "partial"
    return {
        "status": status,
        "as_of_date": target_date,
        "requested_count": len(normalized),
        "quote_count": len(rows),
        "market_cap_count": market_cap_count,
        "current_count": int(stored.get("current_count", 0)),
        "history_count": int(stored.get("history_count", 0)),
        "missing_count": missing_count,
        "trading_status_snapshot": status_snapshot,
        "errors": errors,
    }
