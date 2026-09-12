"""Batch research-data completion operations."""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime
from typing import Any


def error_status(value: Any) -> str:
    text = str(value or "").lower()
    if not text and isinstance(value, BaseException):
        text = type(value).__name__.lower()
    if any(marker in text for marker in ("权限", "permission", "积分", "auth")):
        return "permission_denied"
    if any(marker in text for marker in ("rate", "频繁", "限流", "budget")):
        return "rate_limited"
    if any(marker in text for marker in ("timeout", "timed out", "超时")):
        return "timeout"
    if any(marker in text for marker in ("parse", "解析", "json")):
        return "parse_error"
    if "empty" in text or "no data" in text or "无数据" in text:
        return "empty"
    return "failed"


def error_detail(exc: BaseException) -> dict[str, str]:
    """Keep a bounded, redacted error even when ``str(exc)`` is empty."""
    message = _redact_error(str(exc).strip() or repr(exc))
    return {
        "error_type": type(exc).__name__,
        "error_message": message[:240],
        "error": f"{type(exc).__name__}:{message[:160]}",
    }


def _redact_error(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)(token|access_token|api[_-]?key|password)\s*=\s*[^&\s,;]+", r"\1=[REDACTED]", text)
    text = re.sub(r"(?i)(authorization:\s*bearer\s+)[^\s]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(https?://[^\s?]+\?[^\s]+)", "[URL_REDACTED]", text)
    return text


def _coverage_status(*, complete: bool, has_data: bool) -> str:
    """Separate usable-complete data from a non-empty partial result."""
    if complete:
        return "available"
    return "partial" if has_data else "empty"


def _dated_coverage_status(
    *, complete: bool, has_data: bool, target_date: str, data_date: str
) -> str:
    """Expose an older-but-real packet as stale instead of generic partial."""
    if complete:
        return "available"
    if has_data and target_date and data_date and data_date < target_date:
        return "stale"
    return "partial" if has_data else "empty"


def _financial_refresh_components(
    metadata: dict[str, Any], statement_names: tuple[str, ...], target_date: str
) -> set[str]:
    """Identify only statement types whose cache needs a provider check."""
    if not metadata:
        return set(statement_names)
    target = str(target_date or "")[:10]
    refresh: set[str] = set()
    for name in statement_names:
        item = metadata.get(name) or {}
        fetched = str(item.get("latest_fetched_at") or "")[:10]
        if not fetched or (target and fetched < target):
            refresh.add(name)
    return refresh


async def sync_code(
    database: Any,
    code: str,
    required_bars: int,
    periods: int,
    flow_days: int,
    target_date: str = "",
) -> dict[str, Any]:
    """Backfill one symbol without changing any selection or trading rule."""
    from src.infrastructure.market_data.tushare_provider import tushare_provider

    started = time.perf_counter()
    result: dict[str, Any] = {"ts_code": code, "components": {}}
    component_started: dict[str, float] = {}
    component_finished: dict[str, float] = {}

    def request_attempts_since(start_index: int) -> list[dict[str, Any]]:
        try:
            recent = tushare_provider.runtime_stats().get("recent_attempts") or []
            return [dict(item) for item in recent[start_index:]]
        except Exception:
            return []

    def provider_attempt_index() -> int:
        try:
            return len(tushare_provider.runtime_stats().get("recent_attempts") or [])
        except Exception:
            return 0

    component_started["daily"] = time.perf_counter()
    daily_attempt_start = provider_attempt_index()
    coverage = (await asyncio.to_thread(
        database.get_bar_coverage, [code], required_bars
    ))["details"][0]
    if coverage["status"] == "sufficient":
        result["components"]["daily"] = {
            "status": "available", "source": "local", "coverage": coverage
        }
    else:
        try:
            payload = await tushare_provider.fetch_daily_history(
                code, count=min(1000, required_bars + 30)
            )
            stored = await asyncio.to_thread(
                database.upsert_tushare_daily_history, payload.data
            )
            after = (await asyncio.to_thread(
                database.get_bar_coverage, [code], required_bars
            ))["details"][0]
            result["components"]["daily"] = {
                "status": _coverage_status(
                    complete=after["status"] == "sufficient", has_data=bool(payload.data)
                ),
                "source": "tushare", "received": payload.row_count,
                "stored": stored.get("stored_count", 0), "coverage": after,
            }
        except Exception as exc:
            result["components"]["daily"] = {
                "status": error_status(exc),
                **error_detail(exc),
                "coverage": coverage,
            }
    component_finished["daily"] = time.perf_counter()
    result["components"]["daily"]["request_attempts"] = request_attempts_since(
        daily_attempt_start
    )

    component_started["adjustment_factor"] = time.perf_counter()
    factor_attempt_start = provider_attempt_index()
    factor_coverage = await asyncio.to_thread(
        database.get_adjustment_factor_coverage, code, required_bars
    )
    if factor_coverage["status"] == "sufficient":
        result["components"]["adjustment_factor"] = {
            "status": "available", "source": "local", "coverage": factor_coverage,
        }
    else:
        try:
            payload = await tushare_provider.fetch_adjustment_factors(
                code, count=min(1000, required_bars + 30)
            )
            stored = await asyncio.to_thread(
                database.upsert_adjustment_factors, payload.data
            )
            after = await asyncio.to_thread(
                database.get_adjustment_factor_coverage, code, required_bars
            )
            result["components"]["adjustment_factor"] = {
                "status": _coverage_status(
                    complete=after["status"] == "sufficient", has_data=bool(payload.data)
                ),
                "received": payload.row_count, "stored": stored,
                "data_date": payload.data_date,
                "coverage": after,
            }
        except Exception as exc:
            result["components"]["adjustment_factor"] = {
                "status": error_status(exc),
                **error_detail(exc),
                "coverage": factor_coverage,
            }
    component_finished["adjustment_factor"] = time.perf_counter()
    result["components"]["adjustment_factor"]["request_attempts"] = request_attempts_since(
        factor_attempt_start
    )

    component_started["financial_history"] = time.perf_counter()
    financial_attempt_start = provider_attempt_index()
    statement_names = ("income", "balancesheet", "cashflow", "fina_indicator")
    local_financials = await asyncio.to_thread(
        database.get_financial_history, code, periods
    )
    financial_complete = all(
        len(local_financials.get(name) or []) >= periods for name in statement_names
    )
    metadata_reader = getattr(database, "get_financial_history_metadata", None)
    has_metadata_reader = callable(metadata_reader)
    financial_metadata = (
        await asyncio.to_thread(metadata_reader, code) if has_metadata_reader else {}
    )
    refresh_components = (
        _financial_refresh_components(
            financial_metadata, statement_names, target_date
        )
        if has_metadata_reader else set()
    )
    needed_financial = tuple(
        name for name in statement_names
        if len(local_financials.get(name) or []) < periods
        or name in refresh_components
    )
    if financial_complete and not needed_financial:
        result["components"]["financial_history"] = {
            "status": "available", "source": "local",
            "period_counts": {
                name: len(local_financials.get(name) or []) for name in statement_names
            },
            "freshness": "verified",
            "latest_fetched_at": max(
                (
                    str(item.get("latest_fetched_at") or "")
                    for item in financial_metadata.values()
                    if isinstance(item, dict)
                ),
                default="",
            ),
        }
    else:
        try:
            payload = await tushare_provider.fetch_financial_history(
                code, periods, endpoints=needed_financial or statement_names
            )
            data = dict(payload.data or {})
            stored = await asyncio.to_thread(
                database.upsert_financial_history, code,
                data.get("statements") or {}, source="tushare",
                fetched_at=str(data.get("fetched_at") or datetime.now().isoformat()),
            )
            stored_financials = await asyncio.to_thread(
                database.get_financial_history, code, periods
            )
            period_counts = {
                name: len(stored_financials.get(name) or [])
                for name in statement_names
            }
            financial_complete = all(
                int(period_counts.get(name, 0) or 0) >= periods
                for name in statement_names
            )
            has_financial_data = any(
                isinstance(rows, list) and bool(rows)
                for rows in (data.get("statements") or {}).values()
            )
            result["components"]["financial_history"] = {
                "status": _coverage_status(
                    complete=financial_complete, has_data=has_financial_data
                ),
                "source": "tushare",
                "period_counts": period_counts,
                "stored": stored.get("stored_count", 0),
                "errors": data.get("errors") or [],
                "freshness": "verified" if financial_complete else "partial",
                "provider_period_counts": data.get("period_counts") or {},
            }
        except Exception as exc:
            result["components"]["financial_history"] = {
                "status": error_status(exc),
                **error_detail(exc),
            }
    component_finished["financial_history"] = time.perf_counter()
    result["components"]["financial_history"]["request_attempts"] = request_attempts_since(
        financial_attempt_start
    )

    component_started["fund_flow_history"] = time.perf_counter()
    flow_attempt_start = provider_attempt_index()
    local_flow = await asyncio.to_thread(
        database.get_fund_flow_history, code, flow_days
    )
    local_flow_date = str(local_flow[0].get("trade_date") or "") if local_flow else ""
    local_flow_complete = len(local_flow) >= flow_days and (
        not target_date or local_flow_date >= target_date
    )
    if local_flow_complete:
        result["components"]["fund_flow_history"] = {
            "status": "available", "source": "local", "row_count": len(local_flow),
            "data_date": local_flow_date, "target_date": target_date,
            "fresh": True,
        }
    else:
        try:
            payload = await tushare_provider.fetch_moneyflow_history(code, flow_days)
            stored = await asyncio.to_thread(
                database.upsert_fund_flow_history, list(payload.data or [])
            )
            after = await asyncio.to_thread(
                database.get_fund_flow_history, code, flow_days
            )
            after_date = str(after[0].get("trade_date") or "") if after else ""
            after_complete = len(after) >= flow_days and (
                not target_date or after_date >= target_date
            )
            result["components"]["fund_flow_history"] = {
                "status": _dated_coverage_status(
                    complete=after_complete,
                    has_data=bool(after),
                    target_date=target_date,
                    data_date=after_date or payload.data_date,
                ),
                "source": "tushare",
                "received": payload.row_count, "stored": stored,
                "row_count": len(after), "data_date": after_date or payload.data_date,
                "target_date": target_date, "fresh": after_complete,
            }
        except Exception as exc:
            result["components"]["fund_flow_history"] = {
                "status": error_status(exc),
                **error_detail(exc),
                "target_date": target_date,
            }
    component_finished["fund_flow_history"] = time.perf_counter()
    result["components"]["fund_flow_history"]["request_attempts"] = request_attempts_since(
        flow_attempt_start
    )
    statuses = {
        item.get("status")
        for item in result["components"].values()
    }
    result["complete"] = bool(statuses) and statuses.issubset({"available"})
    result["terminal"] = bool(statuses) and statuses.isdisjoint({
        "timeout", "rate_limited", "failed", "parse_error", "provider_error"
    })
    result["retryable"] = not result["complete"]
    for name, component in result["components"].items():
        component.setdefault("attempted", component.get("source") != "local")
        component.setdefault("error_type", "")
        component.setdefault("error_message", "")
        component.setdefault(
            "attempt_count", 0 if component.get("source") == "local" else 1
        )
        component.setdefault("terminal", component.get("status") not in {
            "timeout", "rate_limited", "failed", "parse_error", "provider_error"
        })
        component["elapsed_seconds"] = round(
            component_finished.get(name, time.perf_counter())
            - component_started.get(name, started),
            3,
        )
    result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    result["incomplete_components"] = sorted(
        name for name, item in result["components"].items()
        if item.get("status") != "available"
    )
    return result
