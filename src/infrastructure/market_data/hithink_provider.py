"""Public HiThink provider facade and endpoint-specific mappings."""

from __future__ import annotations

import re
from typing import Any

from src.infrastructure.market_data.hithink_client import HiThinkClient, HiThinkError
from src.infrastructure.market_data.hithink_contracts import (
    FINANCIAL_PATHS,
    LIMIT_POOL_PATHS,
    SUPPORTED_ADJUSTMENTS,
    HiThinkPayload,
    date_text,
    iso_now,
    map_bar,
    map_financial_row,
    map_pool_row,
    map_snapshot,
    map_symbol,
    map_valuation,
    normalize_codes,
    normalize_thscode,
    timestamp_iso,
    to_ms,
)


class HiThinkProvider(HiThinkClient):
    """Async HiThink REST adapter; provider JSON never leaves this boundary."""

    async def fetch_symbol_search(self, query: str, limit: int = 10) -> HiThinkPayload:
        if not str(query or "").strip():
            raise ValueError("query_required")
        if not 1 <= int(limit) <= 50:
            raise ValueError("invalid_symbol_limit")
        data, request_id, _ = await self._send("symbol_search", "/api/meta/tickers/search", {"q": str(query).strip(), "limit": int(limit)})
        items = data.get("item") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise HiThinkError("symbol_item_not_array", category="contract_error", request_id=request_id)
        stamp = data.get("timestamp") if isinstance(data, dict) else None
        return HiThinkPayload([map_symbol(row) for row in items if isinstance(row, dict)], "symbol_search", "/api/meta/tickers/search", request_id, stamp, timestamp_iso(stamp)[:10], False, len(items), iso_now())

    async def fetch_snapshot(self, codes: str | list[str] | tuple[str, ...]) -> HiThinkPayload:
        normalized = normalize_codes(codes)
        data, request_id, _ = await self._send("snapshot", "/api/a-share/prices/snapshot", {"thscodes": ",".join(normalized)})
        if not isinstance(data, dict) or not isinstance(data.get("item"), list):
            raise HiThinkError("snapshot_item_not_array", category="contract_error", request_id=request_id)
        stamp = data.get("timestamp")
        return HiThinkPayload([map_snapshot(row, stamp) for row in data["item"] if isinstance(row, dict)], "snapshot", "/api/a-share/prices/snapshot", request_id, stamp, timestamp_iso(stamp)[:10], False, len(data["item"]), iso_now())

    async def fetch_daily_history(self, code: str, start: Any, end: Any, adjust: str = "forward") -> HiThinkPayload:
        thscode = normalize_thscode(code)
        adjustment = str(adjust or "forward").lower()
        if adjustment not in SUPPORTED_ADJUSTMENTS:
            raise ValueError("invalid_adjustment")
        start_ms, end_ms = to_ms(start), to_ms(end)
        if end_ms < start_ms:
            raise ValueError("invalid_date_range")
        data, request_id, _ = await self._send("daily_kline", "/api/a-share/prices/historical", {"thscode": thscode, "interval": "1d", "start": start_ms, "end": end_ms, "adjust": adjustment})
        if not isinstance(data, dict) or not isinstance(data.get("item"), list):
            raise HiThinkError("history_item_not_array", category="contract_error", request_id=request_id)
        bars = [map_bar(row) for row in data["item"] if isinstance(row, dict)]
        stamp = data.get("timestamp")
        return HiThinkPayload(bars, "daily_kline", "/api/a-share/prices/historical", request_id, stamp, timestamp_iso(stamp)[:10], False, len(bars), iso_now())

    async def fetch_financial_history(self, code: str, period: str = "annual", limit: int = 4) -> HiThinkPayload:
        thscode = normalize_thscode(code)
        if period not in {"annual", "quarterly"} or not 1 <= int(limit) <= 20:
            raise ValueError("invalid_financial_query")
        statements: dict[str, list[dict[str, Any]]] = {}
        timestamps: list[int] = []
        request_ids: list[str] = []
        for name, path in FINANCIAL_PATHS.items():
            data, request_id, _ = await self._send("financial_statements", path, {"thscode": thscode, "period": period, "limit": int(limit)})
            if not isinstance(data, dict) or not isinstance(data.get("item"), list):
                raise HiThinkError(f"{name}_item_not_array", category="contract_error", request_id=request_id)
            statements[name] = [map_financial_row(row) for row in data["item"] if isinstance(row, dict)]
            if isinstance(data.get("timestamp"), int):
                timestamps.append(data["timestamp"])
            request_ids.append(request_id)
        latest = max(timestamps, default=None)
        return HiThinkPayload({"statements": statements, "period": period, "limit": int(limit)}, "financial_statements", ";".join(FINANCIAL_PATHS), ";".join(request_ids)[:120], latest, timestamp_iso(latest)[:10], False, sum(len(rows) for rows in statements.values()), iso_now())

    async def fetch_financial_indicators(self, code: str, report: str) -> HiThinkPayload:
        thscode = normalize_thscode(code)
        if not re.fullmatch(r"\d{4}-[1-4]", str(report or "")):
            raise ValueError("invalid_report")
        data, request_id, _ = await self._send("financial_indicators", "/api/a-share/financials/indicators", {"thscode": thscode, "report": report})
        if not isinstance(data, dict) or not isinstance(data.get("abilities"), list):
            raise HiThinkError("abilities_not_array", category="contract_error", request_id=request_id)
        abilities = []
        for block in data["abilities"]:
            if not isinstance(block, dict) or not isinstance(block.get("indicators"), list):
                raise HiThinkError("indicators_not_array", category="contract_error", request_id=request_id)
            abilities.append({"ability": block.get("ability"), "indicators": [{"index_id": item.get("index_id"), "value": item.get("value")} for item in block["indicators"] if isinstance(item, dict)]})
        return HiThinkPayload({"thscode": data.get("thscode", thscode), "report": data.get("report", report), "abilities": abilities}, "financial_indicators", "/api/a-share/financials/indicators", request_id, None, "", False, len(abilities), iso_now())

    async def fetch_valuation_snapshot(self, codes: str | list[str] | tuple[str, ...]) -> HiThinkPayload:
        normalized = normalize_codes(codes)
        data, request_id, _ = await self._send("valuation", "/api/a-share/valuations/snapshot", {"thscodes": ",".join(normalized)})
        if not isinstance(data, dict) or not isinstance(data.get("item"), list):
            raise HiThinkError("valuation_item_not_array", category="contract_error", request_id=request_id)
        stamp = data.get("timestamp")
        return HiThinkPayload([map_valuation(row) for row in data["item"] if isinstance(row, dict)], "valuation", "/api/a-share/valuations/snapshot", request_id, stamp, timestamp_iso(stamp)[:10], False, len(data["item"]), iso_now())

    async def fetch_limit_pool(self, kind: str = "up", trade_date: Any = None, page: int = 1, size: int = 50) -> HiThinkPayload:
        path = LIMIT_POOL_PATHS.get(str(kind or "").lower())
        if not path or int(page) < 1 or not 1 <= int(size) <= 200:
            raise ValueError("invalid_limit_pool_query")
        params: dict[str, Any] = {"page": int(page), "size": int(size)}
        if trade_date is not None:
            params["date_ms"] = to_ms(trade_date)
        data, request_id, _ = await self._send("special_data", path, params)
        if not isinstance(data, dict) or not isinstance(data.get("item"), list):
            raise HiThinkError("limit_pool_item_not_array", category="contract_error", request_id=request_id)
        stamp = data.get("timestamp")
        rows = [map_pool_row(row) for row in data["item"] if isinstance(row, dict)]
        return HiThinkPayload({"pagination": data.get("pagination") or {}, "item": rows}, "special_data", path, request_id, stamp, timestamp_iso(stamp)[:10], False, len(rows), iso_now())

    async def fetch_dragon_tiger(self, trade_date: Any = None, board_type: str = "all") -> HiThinkPayload:
        if board_type not in {"all", "org", "hot_money"}:
            raise ValueError("invalid_board_type")
        params: dict[str, Any] = {"board_type": board_type}
        if trade_date is not None:
            params["date"] = date_text(trade_date)
        data, request_id, _ = await self._send("dragon_tiger", "/api/a-share/special-data/dragon-tiger-list", params)
        if not isinstance(data, dict):
            raise HiThinkError("dragon_tiger_data_not_object", category="contract_error", request_id=request_id)
        stock_items, hot_money_items = data.get("stock_items"), data.get("hot_money_items")
        if not isinstance(stock_items, list) or not isinstance(hot_money_items, list):
            raise HiThinkError("dragon_tiger_items_not_array", category="contract_error", request_id=request_id)
        stamp = data.get("timestamp")
        return HiThinkPayload({"board_type": data.get("board_type", board_type), "trade_date": data.get("trade_date"), "count": data.get("count"), "stock_count": data.get("stock_count"), "stock_items": [map_pool_row(row) for row in stock_items if isinstance(row, dict)], "hot_money_items": hot_money_items}, "dragon_tiger", "/api/a-share/special-data/dragon-tiger-list", request_id, stamp, date_text(data.get("trade_date")), False, len(stock_items), iso_now())


hithink_provider = HiThinkProvider()
